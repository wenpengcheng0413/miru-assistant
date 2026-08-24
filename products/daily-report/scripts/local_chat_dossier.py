#!/usr/bin/env python
"""Build a local, evidence-oriented dossier for manual full-chat review."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from miru.chat_analyzer.statistics import ChatMessageRecord, parse_chat_file


MEDIA_PREFIXES = ("[图片]", "[语音转文字]", "[表情]", "[视频]", "[链接]", "[文件]")

CATEGORIES = {
    "relationship": ("喜欢", "想你", "爱你", "爱你", "生气", "难过", "开心", "对不起", "抱歉", "吵", "分手", "在一起", "朋友", "陪", "想见", "见面"),
    "study_work": ("学校", "上课", "作业", "考试", "论文", "老师", "课程", "工作", "项目", "实习", "面试", "开会", "公司", "代码", "开发"),
    "life_plan": ("旅行", "出发", "回家", "搬家", "吃饭", "电影", "演出", "约", "周末", "生日", "过年", "假期", "酒店", "票"),
    "health_family": ("医院", "医生", "生病", "药", "身体", "发烧", "睡不着", "睡觉", "家里", "爸", "妈", "家人"),
    "money_logistics": ("钱", "转账", "报销", "快递", "地址", "买", "订单", "租", "车", "机场"),
}


def _normal_text(record: ChatMessageRecord) -> bool:
    content = record.content.strip()
    return bool(content) and not content.startswith(MEDIA_PREFIXES)


def _snippet(text: str, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _sessions(records: list[ChatMessageRecord], gap_seconds: int = 1800) -> list[list[ChatMessageRecord]]:
    if not records:
        return []
    output: list[list[ChatMessageRecord]] = []
    current = [records[0]]
    for record in records[1:]:
        if (record.timestamp - current[-1].timestamp).total_seconds() > gap_seconds:
            output.append(current)
            current = [record]
        else:
            current.append(record)
    output.append(current)
    return output


def _session_evidence(session: list[ChatMessageRecord]) -> dict:
    text_records = [record for record in session if _normal_text(record)]
    samples = sorted(text_records, key=lambda r: (len(r.content), r.timestamp), reverse=True)[:3]
    return {
        "start": session[0].timestamp.strftime("%Y-%m-%d %H:%M"),
        "end": session[-1].timestamp.strftime("%Y-%m-%d %H:%M"),
        "messages": len(session),
        "samples": [
            {"sender": item.sender, "text": _snippet(item.content)} for item in sorted(samples, key=lambda r: r.timestamp)
        ],
    }


def build_dossier(records: list[ChatMessageRecord], ocr: dict) -> dict:
    months: dict[str, list[ChatMessageRecord]] = defaultdict(list)
    category_hits: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        months[record.timestamp.strftime("%Y-%m")].append(record)
        if _normal_text(record):
            for category, terms in CATEGORIES.items():
                if any(term in record.content for term in terms):
                    category_hits[category].append(
                        {
                            "date": record.timestamp.strftime("%Y-%m-%d %H:%M"),
                            "sender": record.sender,
                            "text": _snippet(record.content),
                        }
                    )

    monthly: list[dict] = []
    for key, items in sorted(months.items()):
        days = Counter(item.timestamp.strftime("%Y-%m-%d") for item in items)
        top_sessions = sorted(_sessions(items), key=len, reverse=True)[:3]
        long_texts = sorted(
            (item for item in items if _normal_text(item)),
            key=lambda item: len(item.content),
            reverse=True,
        )[:4]
        monthly.append(
            {
                "month": key,
                "messages": len(items),
                "me": sum(item.is_self for item in items),
                "contact": sum(not item.is_self for item in items),
                "active_days": len(days),
                "top_days": days.most_common(3),
                "top_sessions": [_session_evidence(session) for session in top_sessions],
                "long_messages": [
                    {
                        "date": item.timestamp.strftime("%Y-%m-%d %H:%M"),
                        "sender": item.sender,
                        "text": _snippet(item.content, 400),
                    }
                    for item in sorted(long_texts, key=lambda item: item.timestamp)
                ],
            }
        )

    return {
        "total_messages": len(records),
        "period": {
            "start": records[0].timestamp.strftime("%Y-%m-%d"),
            "end": records[-1].timestamp.strftime("%Y-%m-%d"),
        },
        "monthly": monthly,
        "category_hit_counts": {category: len(items) for category, items in category_hits.items()},
        "category_evidence": {
            category: items[:80] for category, items in category_hits.items()
        },
        "ocr_images_with_text": sum(1 for item in ocr.get("items", []) if item.get("text")),
        "ocr_text_samples": [
            {
                "timestamp": item.get("timestamp", ""),
                "sender": item.get("sender", ""),
                "file": item.get("file", ""),
                "text": _snippet(str(item.get("text", "")), 400),
            }
            for item in ocr.get("items", [])
            if item.get("text")
        ][:180],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat", required=True, type=Path)
    parser.add_argument("--ocr", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    records = parse_chat_file(args.chat.read_text(encoding="utf-8"))
    ocr = json.loads(args.ocr.read_text(encoding="utf-8"))
    payload = build_dossier(records, ocr)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"messages": len(records), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
