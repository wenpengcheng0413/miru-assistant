"""终端文字聊天调试客户端（验证后端全链路，无需 iPhone）。

用法：
    cd products/mobile-assistant/server
    python scripts/ws_chat.py                     # 连 ws://127.0.0.1:8765/ws/session
    python scripts/ws_chat.py --token xxx --persona miru
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

# Windows 控制台默认 GBK，强制 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websockets


async def reader(ws) -> None:
    """打印服务端事件；二进制帧（TTS 音频）跳过。"""
    async for frame in ws:
        if isinstance(frame, (bytes, bytearray)):
            continue
        try:
            msg = json.loads(frame)
        except json.JSONDecodeError:
            continue
        mtype = msg.get("type")
        if mtype == "llm_delta":
            print(msg["text"], end="", flush=True)
        elif mtype == "sentence":
            print(f"\n🔊 [语音句] {msg['text']}")
        elif mtype == "tool_start":
            print(f"\n🔧 调用工具 {msg['name']} {json.dumps(msg.get('args', {}), ensure_ascii=False)}")
        elif mtype == "tool_end":
            print(f"   → {'✅' if msg.get('ok') else '❌'} {msg.get('summary')} ({msg.get('duration_ms')}ms)")
        elif mtype == "turn_end":
            print(f"\n— 本轮结束 · 费用 {msg.get('cost_rmb')} 元 · {json.dumps(msg.get('usage', {}), ensure_ascii=False)}")
            print("", flush=True)
        elif mtype == "server_note":
            print(f"\n📌 {msg['text']}")
        elif mtype == "error":
            print(f"\n❌ [{msg.get('code')}] {msg.get('message')}")
        elif mtype == "hello_ok":
            print(f"✅ 已连接：session={msg['session_id'][:8]}… persona={msg['persona']}")
        elif mtype in ("stt_partial", "stt_final", "user_text", "pong"):
            pass


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ws/session")
    parser.add_argument("--token", default=os.environ.get("MIRU_SERVER_TOKEN", ""))
    parser.add_argument("--persona", default="")
    parser.add_argument("--conversation", default="", help="续接已有会话 ID")
    args = parser.parse_args()

    hello = {
        "type": "hello", "token": args.token, "device": "terminal",
        "mode": "text", "synth_tts": False,
    }
    if args.persona:
        hello["persona"] = args.persona
    if args.conversation:
        hello["conversation_id"] = args.conversation

    async with websockets.connect(args.url, max_size=64 * 1024 * 1024) as ws:
        await ws.send(json.dumps(hello, ensure_ascii=False))
        reader_task = asyncio.create_task(reader(ws))
        print("输入消息后回车（Ctrl+C 退出）：")
        loop = asyncio.get_event_loop()
        while True:
            try:
                text = await loop.run_in_executor(None, input, "你> ")
            except EOFError:
                break
            text = text.strip()
            if not text:
                continue
            if text in ("/quit", "/exit"):
                break
            await ws.send(json.dumps({"type": "text_input", "text": text}, ensure_ascii=False))
        reader_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
