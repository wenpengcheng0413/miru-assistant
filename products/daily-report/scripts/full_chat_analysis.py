#!/usr/bin/env python
"""Generate a full-period contact-chat report without discarding early history.

The original ``ChatAnalyzer`` intentionally protects the API by keeping only a
recent text window.  This utility is for an explicitly requested full-history
review: it analyses chronological slices, saves every intermediate result for
audit/resume, and then synthesises them with exact local statistics.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from miru.chat_analyzer.analyzer import ChatAnalyzer
from miru.chat_analyzer.statistics import ChatMessageRecord, parse_chat_file


CHUNK_CHARS = 18_000
STATE_VERSION = 1


SLICE_SYSTEM = """你是一名严谨的中文聊天记录分析助手。
只可依据提供的聊天片段；不补全事实、不臆测身份、不做心理诊断。
你会看到“我”和一位联系人。请用简体中文写一份不超过 1000 字的片段证据摘要，
并且为每个重要结论标出消息日期或日期范围。必须覆盖：
1. 发生的具体事件、约定、计划、成果或未决事项；
2. 主要话题及其变化；
3. 互动方式、情绪/关系信号（清楚区分直接证据与谨慎推断）；
4. 人物特征或需求信号（仅限聊天中可支持的观察）；
5. 图片 OCR 文字、语音转写在此片段中补充了什么；
6. 不确定或证据不足之处。
不要复述普通寒暄，也不要输出敏感的原文长引语。"""


FINAL_SYSTEM = """你是一名严谨、克制的中文聊天记录分析师。根据一位用户与
“肖杨”的全量私聊分片摘要和精确本地统计，写一份详细的 Markdown 综合报告。
必须只基于提供材料：不能把推断写成事实，不能进行医学/心理诊断，不能猜测
现实身份或未出现的信息。所有关键事件、关系阶段与画像判断均需给出日期或
日期范围；对证据不足的内容必须标明“推断”或“无法确认”。

报告须包含：
1. 覆盖范围、数据质量与局限；
2. 关系与互动演变时间线（分阶段，说明每阶段的依据）；
3. 重要事情、计划、承诺、共同议题和结果；
4. 量化互动画像（频率、发起、回复、时段、媒体）；
5. 双方在这段关系中的沟通风格、需求和边界（证据与推断分开）；
6. 情感基调、支持方式、摩擦或变化（避免诊断式标签）；
7. 图片 OCR、语音转写和文档情况如何影响解读；
8. 对当前关系的谨慎总结，以及需要人工回看原图/原始消息才能确认的点。
写得具体、完整、可审计；不要出现“模型”“提示词”等技术过程表述。"""


def _call(client: Any, system: str, user: str, max_tokens: int) -> str:
    """Call the configured compatible Chat Completions API with short retries."""
    last_error = ""
    for attempt in range(3):
        try:
            kwargs: dict[str, Any] = {
                "model": client.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
                "max_tokens": max_tokens,
            }
            # V4 supports this parameter, but retry without it for compatible APIs.
            try:
                response = client._client.chat.completions.create(
                    **kwargs, extra_body={"thinking": {"type": "disabled"}}
                )
            except Exception as exc:
                if "thinking" not in str(exc).lower():
                    raise
                response = client._client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""
            if content.strip():
                return content.strip()
            last_error = "API 返回空内容"
        except Exception as exc:  # keep the resumable state intact
            last_error = str(exc)
        if attempt < 2:
            time.sleep(4 * (attempt + 1))
    raise RuntimeError(last_error or "AI 调用失败")


def _load_ocr(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            str(item.get("file", "")): str(item.get("text", "")).strip()
            for item in payload.get("items", [])
            if str(item.get("text", "")).strip()
        }
    except (OSError, json.JSONDecodeError):
        return {}


def _render_record(record: ChatMessageRecord, ocr: dict[str, str]) -> str:
    content = record.content
    if content.startswith("[图片] media/img/"):
        file_name = content.removeprefix("[图片] ").split()[0]
        recognized = ocr.get(file_name, "")
        if recognized:
            content += f"\n[图片文字识别] {recognized}"
    return f"[{record.timestamp:%Y-%m-%d %H:%M}] {record.sender}: {content}"


def _chunk_records(records: list[ChatMessageRecord], ocr: dict[str, str]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current: list[str] = []
    current_records: list[ChatMessageRecord] = []
    current_size = 0
    for record in records:
        line = _render_record(record, ocr)
        if current and current_size + len(line) + 1 > CHUNK_CHARS:
            chunks.append(
                {
                    "id": len(chunks) + 1,
                    "start": current_records[0].timestamp.strftime("%Y-%m-%d"),
                    "end": current_records[-1].timestamp.strftime("%Y-%m-%d"),
                    "message_count": len(current_records),
                    "text": "\n".join(current),
                }
            )
            current, current_records, current_size = [], [], 0
        current.append(line)
        current_records.append(record)
        current_size += len(line) + 1
    if current:
        chunks.append(
            {
                "id": len(chunks) + 1,
                "start": current_records[0].timestamp.strftime("%Y-%m-%d"),
                "end": current_records[-1].timestamp.strftime("%Y-%m-%d"),
                "message_count": len(current_records),
                "text": "\n".join(current),
            }
        )
    return chunks


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": STATE_VERSION, "chunks": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("version") == STATE_VERSION and isinstance(state.get("chunks"), dict):
            return state
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": STATE_VERSION, "chunks": {}}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _facts(records: list[ChatMessageRecord], statistics: dict[str, Any], timeline: dict[str, Any], ocr: dict[str, str]) -> dict[str, Any]:
    by_month: Counter[str] = Counter(r.timestamp.strftime("%Y-%m") for r in records)
    image_count = sum(r.content.startswith("[图片]") for r in records)
    voice_count = sum(r.content.startswith("[语音转文字]") for r in records)
    return {
        "record_count": len(records),
        "period": statistics.get("period", {}),
        "active_days": len(statistics.get("messages_by_day", {})),
        "messages_by_person": {
            "me": statistics.get("sent_by_me", 0),
            "contact": statistics.get("sent_by_them", 0),
        },
        "message_length": statistics.get("message_length", {}),
        "response_times": statistics.get("response_times", {}),
        "daily_initiation": statistics.get("initiation", {}),
        "peak_months": by_month.most_common(12),
        "top_words": statistics.get("top_words", []),
        "continuous_conversation_events": timeline.get("total_events", 0),
        "media": {
            "images": image_count,
            "voice_transcripts": voice_count,
            "images_with_ocr_text": len(ocr),
            "documents_detected": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="全量联系人聊天记录分片分析")
    parser.add_argument("--contact", required=True)
    parser.add_argument("--chat", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--ocr-file", type=Path, default=None)
    args = parser.parse_args()

    if not args.chat.exists():
        print(f"聊天文件不存在: {args.chat}", file=sys.stderr)
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = parse_chat_file(args.chat.read_text(encoding="utf-8"))
    if not records:
        print("聊天文件为空，无法分析", file=sys.stderr)
        return 2
    ocr = _load_ocr(args.ocr_file)
    chunks = _chunk_records(records, ocr)

    statistics_path = args.output_dir / "statistics.json"
    timeline_path = args.output_dir / "timeline.json"
    statistics = json.loads(statistics_path.read_text(encoding="utf-8")) if statistics_path.exists() else {}
    timeline = json.loads(timeline_path.read_text(encoding="utf-8")) if timeline_path.exists() else {}
    facts = _facts(records, statistics, timeline, ocr)

    analyzer = ChatAnalyzer(config_path=args.config)
    client = analyzer._build_client()
    if client is None:
        print("未配置可用的 AI 服务", file=sys.stderr)
        return 2

    state_path = args.output_dir / "full_analysis_chunks.json"
    state = _load_state(state_path)
    state["contact"] = args.contact
    state["record_count"] = len(records)
    state["chunk_count"] = len(chunks)

    for chunk in chunks:
        key = str(chunk["id"])
        if key in state["chunks"] and state["chunks"][key].get("analysis"):
            continue
        user = (
            f"联系人：{args.contact}\n"
            f"片段：#{chunk['id']}，{chunk['start']} 至 {chunk['end']}，"
            f"{chunk['message_count']} 条消息。\n\n聊天记录：\n{chunk['text']}"
        )
        print(f"分析片段 {chunk['id']}/{len(chunks)}", flush=True)
        analysis = _call(client, SLICE_SYSTEM, user, max_tokens=1800)
        state["chunks"][key] = {
            "start": chunk["start"],
            "end": chunk["end"],
            "message_count": chunk["message_count"],
            "analysis": analysis,
        }
        _save_state(state_path, state)

    ordered = [state["chunks"][str(chunk["id"])] for chunk in chunks]
    evidence = "\n\n".join(
        f"## 片段 {i + 1}（{item['start']} 至 {item['end']}，{item['message_count']} 条）\n"
        f"{item['analysis']}"
        for i, item in enumerate(ordered)
    )
    final_user = (
        f"联系人：{args.contact}\n"
        f"精确统计：\n{json.dumps(facts, ensure_ascii=False, indent=2)}\n\n"
        f"按时间顺序覆盖全部消息的证据摘要：\n{evidence}"
    )
    print("汇总全量分析报告", flush=True)
    report = _call(client, FINAL_SYSTEM, final_user, max_tokens=9000)
    report_path = args.output_dir / "full_analysis_report.md"
    header = (
        f"# 与{args.contact}的全量聊天记录综合分析\n\n"
        f"- 覆盖消息：{len(records)} 条\n"
        f"- 覆盖时期：{records[0].timestamp:%Y-%m-%d} 至 {records[-1].timestamp:%Y-%m-%d}\n"
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n\n"
    )
    report_path.write_text(header + report.strip() + "\n", encoding="utf-8")
    print(json.dumps({"success": True, "chunks": len(chunks), "report": str(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
