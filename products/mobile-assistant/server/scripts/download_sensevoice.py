"""下载 SenseVoice 本地 STT 模型（走 hf-mirror 国内镜像）并可选自测。

用法：
    cd products/mobile-assistant/server
    python scripts/download_sensevoice.py                # 下载 model.onnx + tokens.txt
    python scripts/download_sensevoice.py --vad          # 附带 silero VAD（预留）
    python scripts/download_sensevoice.py --test test.wav
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

# Windows 控制台默认 GBK，强制 UTF-8 避免 emoji 打印崩溃
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL_REPO = "csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
VAD_REPO = "csukuangfj/sherpa-onnx-vad-resample-damping-v1-2024-03-01"
MIRROR = "https://hf-mirror.com"

FILES = {
    "model.onnx": f"{MODEL_REPO}/resolve/main/model.onnx",
    "tokens.txt": f"{MODEL_REPO}/resolve/main/tokens.txt",
}


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"下载 {url} …")
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / 1e6:.1f} / {total / 1e6:.1f} MB ({done * 100 // total}%)", end="")
        if total:
            print()
    print(f"✅ {dest}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", default="./data/models/sensevoice")
    parser.add_argument("--vad", action="store_true", help="同时下载 silero VAD 模型")
    parser.add_argument("--test", help="下载后用该 wav 文件自测识别")
    args = parser.parse_args()

    dest = Path(args.dest)
    for filename, repo_path in FILES.items():
        target = dest / filename
        if target.exists() and target.stat().st_size > 1000:
            print(f"已存在，跳过: {target}")
            continue
        download(f"{MIRROR}/{repo_path}", target)

    if args.vad:
        vad_dest = Path("./data/models") / "silero_vad.onnx"
        if not vad_dest.exists():
            download(f"{MIRROR}/{VAD_REPO}/resolve/main/silero_vad.onnx", vad_dest)

    print(f"\n模型目录: {dest.resolve()}")
    print("在 server/config/settings.yaml 中确认 stt.engine: sensevoice 与 stt.model_dir 即可启用。")

    if args.test:
        test_file = Path(args.test)
        if not test_file.exists():
            print(f"自测文件不存在: {test_file}")
            sys.exit(1)
        import wave
        with wave.open(str(test_file), "rb") as w:
            pcm = w.readframes(w.getnframes())
            sample_rate = w.getframerate()
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from miru_server.config import AppConfig
        from miru_server.stt.sensevoice import SenseVoiceSTT
        cfg = AppConfig.model_validate({"stt": {"model_dir": str(dest), "num_threads": 4}})
        engine = SenseVoiceSTT(cfg.stt)
        print(f"\n自测识别结果: {engine.transcribe(pcm, sample_rate)}")


if __name__ == "__main__":
    main()
