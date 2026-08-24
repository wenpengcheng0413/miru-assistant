"""一键端到端自检：健康 → 真实 LLM 对话 → 语音文件全链路 → 微信工具 → 成本报表。

用法（先进入 products/mobile-assistant/server）：
    venv/Scripts/python scripts/e2e_check.py --token <token>                 # 全部检查
    venv/Scripts/python scripts/e2e_check.py --token <token> --no-llm        # 跳过真实 LLM 调用（不花钱）
    venv/Scripts/python scripts/e2e_check.py --token <token> --wav test.wav  # 用指定语音文件

语音文件要求：16kHz 单声道 PCM16 wav；也可用 --make-wav "文本" 先由 edge-tts 生成。
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 控制台默认 GBK，强制 UTF-8 避免 emoji/¥ 打印崩溃
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx
import websockets

RESULTS: list[tuple[str, bool, str]] = []


def report(step: str, ok: bool, detail: str) -> None:
    RESULTS.append((step, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {step}: {detail}")


async def ws_chat(url: str, token: str, mode: str, synth: bool,
                  tts_format: str = "mp3", tts_rate: int = 32000,
                  audio_file: Path | None = None,
                  expect_tool: str | None = None,
                  conversation_id: str | None = None,
                  out_audio: Path | None = None) -> dict:
    """跑一轮 WS 会话（文字或语音文件），返回事件摘要。"""
    hello = {
        "type": "hello", "token": token, "device": "e2e",
        "mode": mode, "synth_tts": synth,
        "tts_format": tts_format, "tts_sample_rate": tts_rate,
    }
    if conversation_id:
        hello["conversation_id"] = conversation_id

    summary: dict = {"events": [], "session_id": "", "cost": 0.0,
                     "audio_bytes": 0, "final_text": "", "tool_calls": []}

    async with websockets.connect(url, max_size=64 * 1024 * 1024) as ws:
        await ws.send(json.dumps(hello, ensure_ascii=False))
        audio_buf = io.BytesIO()

        async def reader():
            async for frame in ws:
                if isinstance(frame, (bytes, bytearray)):
                    audio_buf.write(bytes(frame))
                    continue
                ev = json.loads(frame)
                t = ev.get("type")
                summary["events"].append(t)
                if t == "hello_ok":
                    summary["session_id"] = ev.get("session_id", "")
                elif t == "stt_final":
                    summary["final_text"] = ev.get("text", "")
                elif t == "tool_start":
                    summary["tool_calls"].append(ev.get("name", ""))
                elif t == "turn_end":
                    summary["cost"] = ev.get("cost_rmb", 0.0)
                if t in ("turn_end", "error"):
                    summary["error"] = ev.get("message", "") if t == "error" else ""
                    break

        reader_task = asyncio.create_task(reader())
        await asyncio.sleep(0.5)

        if mode == "voice" and audio_file:
            # 按 100ms 一帧实时节奏推送 PCM，模拟手机
            with wave.open(str(audio_file), "rb") as w:
                pcm = w.readframes(w.getnframes())
            for i in range(0, len(pcm), 3200):
                await ws.send(pcm[i:i + 3200])
                await asyncio.sleep(0.1)
            await ws.send(json.dumps({"type": "audio_end"}))
        else:
            await ws.send(json.dumps(
                {"type": "text_input", "text": "你好，请用一句话介绍你自己。"},
                ensure_ascii=False,
            ))

        await asyncio.wait_for(reader_task, timeout=90)
        summary["audio_bytes"] = audio_buf.tell()
        if out_audio and summary["audio_bytes"]:
            out_audio.write_bytes(audio_buf.getvalue())
    return summary


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ws/session")
    parser.add_argument("--token", default=os.environ.get("MIRU_SERVER_TOKEN", "dev-smoke-test-token"))
    parser.add_argument("--wav", default="", help="语音文件（16k PCM16 单声道）")
    parser.add_argument("--make-wav", default="", help="用 edge-tts 生成一句测试语音（如：今天天气怎么样）")
    parser.add_argument("--no-llm", action="store_true", help="跳过真实 LLM 调用")
    parser.add_argument("--no-voice", action="store_true", help="跳过语音链路")
    parser.add_argument("--with-wechat", action="store_true", help="测试微信联系人工具（需已授权）")
    parser.add_argument("--out", default="./data/e2e_tts_output.mp3", help="语音链路收到的 TTS 音频保存位置")
    args = parser.parse_args()

    rest = args.url.replace("ws://", "http://").replace("/ws/session", "")
    headers = {"Authorization": f"Bearer {args.token}"}

    # ---- 0. 生成测试语音 ----
    wav_path: Path | None = None
    if args.make_wav:
        wav_path = await make_test_wav(args.make_wav)
        if wav_path is None:
            report("生成测试语音", False, "edge-tts/ffmpeg 失败")
            return 1
        report("生成测试语音", True, f"{wav_path}（内容: {args.make_wav}）")
    elif args.wav:
        wav_path = Path(args.wav)
        if not wav_path.exists():
            report("语音文件", False, f"{wav_path} 不存在")
            return 1

    # ---- 1. 健康检查 ----
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{rest}/api/health", headers=headers)
            if r.status_code == 200:
                report("健康检查", True, str(r.json()))
            else:
                report("健康检查", False, f"HTTP {r.status_code}")
                return 1
    except Exception as e:
        report("健康检查", False, f"无法连接: {e}")
        return 1

    # ---- 2. 文字对话（真实 LLM，可跳过）----
    if not args.no_llm:
        s = await ws_chat(args.url, args.token, "text", False)
        if s["error"]:
            report("文字对话(LLM)", False, s["error"][:80])
        elif "llm_delta" in s["events"] and s["events"][-1] == "turn_end":
            report("文字对话(LLM)", True, f"事件{s['events'].count('llm_delta')}个增量 · 费用 ¥{s['cost']}")
        else:
            report("文字对话(LLM)", False, f"事件流异常: {s['events']}")

    # ---- 3. 微信联系人工具（需授权）----
    if args.with_wechat:
        s = await ws_chat_wechat(args.url, args.token)
        if "wechat_contact_list" in s["tool_calls"]:
            report("微信联系人工具", True,
                   f"调用了 {s['tool_calls']} · 事件{s['events'].count('llm_delta')}个增量")
        elif s["error"]:
            report("微信联系人工具", False, s["error"][:100])
        else:
            report("微信联系人工具", False, f"未触发工具调用: {s['events']}")

    # ---- 4. 语音文件全链路（STT→LLM→TTS）----
    if wav_path and not args.no_voice:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        s = await ws_chat(args.url, args.token, "voice", True,
                          audio_file=wav_path, out_audio=out)
        checks = {
            "stt_final 到达": "stt_final" in s["events"],
            "识别出文本": bool(s["final_text"]),
            "LLM 有流式输出": "llm_delta" in s["events"],
            "收到 TTS 音频": s["audio_bytes"] > 0,
            "turn_end 收尾": s["events"][-1] == "turn_end",
        }
        ok = all(checks.values())
        detail = (f"识别='{s['final_text'][:30]}' · TTS {s['audio_bytes']} 字节 · "
                  f"费用 ¥{s['cost']} · 保存于 {out}" if ok else
                  f"部分失败: { {k: v for k, v in checks.items() if not v} }")
        report("语音文件全链路", ok, detail)

    # ---- 5. 成本报表 ----
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{rest}/api/cost/report?days=7", headers=headers)
            data = r.json()
            report("成本报表", True,
                   f"近7天 ¥{data['total_rmb']} · 按服务商: {data['by_provider']}")
    except Exception as e:
        report("成本报表", False, str(e))

    print()
    failed = [r for r in RESULTS if not r[1]]
    print(f"=== 结果: {len(RESULTS) - len(failed)}/{len(RESULTS)} 通过 ===")
    return 1 if failed else 0


async def ws_chat_wechat(url: str, token: str) -> dict:
    """专门测微信工具：问联系人列表。"""
    hello = {"type": "hello", "token": token, "device": "e2e",
             "mode": "text", "synth_tts": False}
    summary: dict = {"events": [], "tool_calls": [], "error": ""}
    async with websockets.connect(url, max_size=64 * 1024 * 1024) as ws:
        await ws.send(json.dumps(hello, ensure_ascii=False))

        async def reader():
            async for frame in ws:
                if isinstance(frame, (bytes, bytearray)):
                    continue
                ev = json.loads(frame)
                t = ev.get("type")
                summary["events"].append(t)
                if t == "tool_start":
                    summary["tool_calls"].append(ev.get("name", ""))
                if t in ("turn_end", "error"):
                    if t == "error":
                        summary["error"] = ev.get("message", "")
                    break

        reader_task = asyncio.create_task(reader())
        await asyncio.sleep(0.3)
        await ws.send(json.dumps(
            {"type": "text_input", "text": "我有哪些微信联系人？列举 5 个。"},
            ensure_ascii=False,
        ))
        await asyncio.wait_for(reader_task, timeout=90)
    return summary


async def make_test_wav(text: str) -> Path | None:
    """edge-tts 生成语音 → ffmpeg 转 16k PCM16 wav。"""
    import edge_tts
    tmp = Path(tempfile.gettempdir()) / f"miru_e2e_{int(time.time())}"
    mp3 = tmp.with_suffix(".mp3")
    wav = tmp.with_suffix(".wav")
    try:
        audio = b""
        async for chunk in edge_tts.Communicate(text, voice="zh-CN-XiaoxiaoNeural").stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
        mp3.write_bytes(audio)
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(mp3), "-ar", "16000", "-ac", "1",
             "-c:a", "pcm_s16le", str(wav)],
            capture_output=True, timeout=60,
        )
        if r.returncode != 0:
            print("ffmpeg 失败:", r.stderr.decode("utf-8", "replace")[:200])
            return None
        mp3.unlink(missing_ok=True)
        return wav
    except Exception as e:
        print("生成测试语音失败:", e)
        return None


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
