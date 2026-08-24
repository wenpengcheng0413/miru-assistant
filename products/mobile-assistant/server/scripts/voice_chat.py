"""PC 麦克风全链路语音调试（替代 iPhone 验证：麦克风→STT→LLM→TTS→扬声器）。

依赖：pip install sounddevice
用法：
    cd products/mobile-assistant/server
    python scripts/voice_chat.py --token xxx
    回车 = 开始/结束说话（push-to-talk）；/quit 退出
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

try:
    import sounddevice as sd
    SD_OK = True
except ImportError:
    sd = None
    SD_OK = False

SAMPLE_RATE = 16000
BLOCK = 1600  # 100ms


async def main() -> None:
    if not SD_OK:
        print("需要 sounddevice：pip install sounddevice")
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ws/session")
    parser.add_argument("--token", default=os.environ.get("MIRU_SERVER_TOKEN", ""))
    args = parser.parse_args()

    # 请求 PCM 输出（24kHz，便于 sounddevice 直接播放）
    hello = {
        "type": "hello", "token": args.token, "device": "pc-mic",
        "mode": "voice", "synth_tts": True,
        "tts_format": "pcm", "tts_sample_rate": 24000,
    }
    async with websockets.connect(args.url, max_size=64 * 1024 * 1024) as ws:
        await ws.send(json.dumps(hello, ensure_ascii=False))

        # sounddevice 回调在 PortAudio 线程执行，必须用主事件循环投递（不能用 get_event_loop）
        loop = asyncio.get_running_loop()

        state = {"recording": False, "stream": None, "pending_audio": bytearray(),
                 "pending_fmt": "pcm", "pending_rate": 24000, "muted": False}
        play_queue: asyncio.Queue[tuple] = asyncio.Queue()

        def audio_callback(indata, frames, time_info, status):
            if state["recording"]:
                loop.call_soon_threadsafe(
                    lambda d=bytes(indata): asyncio.create_task(ws.send(d))
                )

        async def play_worker():
            while True:
                chunk, fmt, rate = await play_queue.get()
                if state["muted"]:
                    continue   # 静音模式：只显示文字，不播放
                if fmt == "pcm":
                    await asyncio.to_thread(sd.play, chunk, rate)
                    await asyncio.to_thread(sd.wait)
                else:
                    # mp3（edge-tts 兜底输出）→ ffplay 播放
                    import subprocess as sp
                    import tempfile
                    from pathlib import Path
                    tmp = Path(tempfile.gettempdir()) / "miru_sentence.mp3"
                    tmp.write_bytes(chunk)
                    await asyncio.to_thread(sp.run,
                        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(tmp)],
                        check=False)
                    tmp.unlink(missing_ok=True)

        async def reader():
            async for frame in ws:
                if isinstance(frame, (bytes, bytearray)):
                    state["pending_audio"].extend(frame)
                    continue
                # 文本事件到达 = 上一句音频帧结束 → 入播放队列
                if state["pending_audio"]:
                    await play_queue.put((
                        bytes(state["pending_audio"]),
                        state["pending_fmt"], state["pending_rate"],
                    ))
                    state["pending_audio"].clear()
                msg = json.loads(frame)
                mtype = msg.get("type")
                if mtype == "stt_partial":
                    print(f"\r👂 {msg['text']}", end="", flush=True)
                elif mtype == "stt_final":
                    print(f"\r👂 {msg['text']}（{msg.get('latency_ms')}ms）", flush=True)
                elif mtype == "llm_delta":
                    print(msg["text"], end="", flush=True)
                elif mtype == "sentence":
                    state["pending_fmt"] = msg.get("audio_format", "mp3")
                    state["pending_rate"] = msg.get("sample_rate", 24000)
                    print(f"\n🔊 [{state['pending_fmt']}] {msg['text']}", flush=True)
                elif mtype == "tool_start":
                    print(f"\n🔧 {msg['name']}…", flush=True)
                elif mtype == "tool_end":
                    print(f"   → {msg.get('summary')}", flush=True)
                elif mtype == "turn_end":
                    print(f"\n— 本轮费用 {msg.get('cost_rmb')} 元\n", flush=True)
                elif mtype == "error":
                    print(f"\n❌ {msg.get('message')}", flush=True)
                elif mtype == "hello_ok":
                    print(f"✅ 已连接（TTS: {msg['tts']}）\n回车=开始/结束说话，/quit 退出", flush=True)

        reader_task = asyncio.create_task(reader())
        player_task = asyncio.create_task(play_worker())

        def toggle():
            if not state["recording"]:
                state["stream"] = sd.RawInputStream(
                    samplerate=SAMPLE_RATE, blocksize=BLOCK, channels=1,
                    dtype="int16", callback=audio_callback,
                )
                state["stream"].start()
                state["recording"] = True
                print("\n🎙️ 录音中…（回车结束）", flush=True)
            else:
                state["stream"].stop()
                state["stream"].close()
                state["recording"] = False
                asyncio.create_task(ws.send(json.dumps({"type": "audio_end"})))
                print("\n⏹ 已结束，识别中…", flush=True)

        loop = asyncio.get_event_loop()
        print("\n命令：回车=开始/结束说话 | /mute=语音开关 | /quit=退出", flush=True)
        while True:
            try:
                line = await loop.run_in_executor(None, input)
            except EOFError:
                break
            cmd = line.strip()
            if cmd in ("/quit", "/exit"):
                break
            if cmd in ("/mute", "/unmute"):
                state["muted"] = not state["muted"]
                print("🔇 已静音（只显示文字）" if state["muted"] else "🔊 已恢复语音播放", flush=True)
                continue
            toggle()

        if state["recording"]:
            state["stream"].stop()
            state["stream"].close()
        reader_task.cancel()
        player_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
