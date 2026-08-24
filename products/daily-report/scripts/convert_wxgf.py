#!/usr/bin/env python
"""
Miru Assistant — WXGF 图片批量转换工具。

微信 HEVC 私有格式 (.wxgf) → 标准 jpg（第一帧静态图）。
转换后更新 output/*/chat.txt 中的 [图片] media/img/xxx.wxgf 引用为 .jpg。

用法:
    python tools/convert_wxgf.py                 # 转换 output/ 下全部
    python tools/convert_wxgf.py output/Krista   # 指定目录
"""

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from loguru import logger  # noqa: E402


def convert_file(wxgf_path: Path) -> Path | None:
    """单个 wxgf → jpg（提取 HEVC NAL 流 → ffmpeg 第一帧）。"""
    try:
        data = wxgf_path.read_bytes()
        idx = data.find(b"\x00\x00\x00\x01")
        if idx < 0:
            return None
        hevc = data[idx:]
    except OSError:
        return None

    jpg_path = wxgf_path.with_suffix(".jpg")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "hevc", "-i", "-",
                "-frames:v", "1", str(jpg_path),
            ],
            input=hevc,
            capture_output=True,
            timeout=60,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return jpg_path if jpg_path.exists() else None


def update_chat_refs(chat_file: Path) -> int:
    """把 chat.txt 中 media/img/xxx.wxgf 引用更新为 .jpg（文件已存在时）。"""
    if not chat_file.exists():
        return 0
    text = chat_file.read_text(encoding="utf-8")
    updated = 0
    base = chat_file.parent  # 相对路径的解析基准

    def _replace(m: re.Match) -> str:
        nonlocal updated
        jpg = (base / m.group(1)).with_suffix(".jpg")
        if jpg.exists():
            updated += 1
            return f"[图片] {m.group(1)[:-5]}.jpg"
        return m.group(0)

    new_text = re.sub(r"\[图片\] (media/img/[^\]\s]+\.wxgf)", _replace, text)
    if updated:
        chat_file.write_text(new_text, encoding="utf-8")
    return updated


def main() -> int:
    roots = [Path(p) for p in sys.argv[1:]] or [PROJECT_ROOT / "output"]
    converted = 0
    failed = 0
    refs_updated = 0

    for root in roots:
        if not root.exists():
            print(f"[跳过] 目录不存在: {root}")
            continue
        wxgf_files = sorted(root.rglob("*.wxgf"))
        if not wxgf_files:
            print(f"[跳过] {root} 下无 .wxgf 文件")
            continue
        print(f"[开始] {root}: {len(wxgf_files)} 个 wxgf")
        for i, p in enumerate(wxgf_files, 1):
            if p.with_suffix(".jpg").exists():
                converted += 1  # 已转换过
                continue
            jpg = convert_file(p)
            if jpg:
                converted += 1
            else:
                failed += 1
                logger.warning(f"转换失败: {p.name}")
            if i % 500 == 0:
                print(f"  进度: {i}/{len(wxgf_files)} (成功 {converted})")

        # 更新 chat.txt 引用
        for chat in root.rglob("chat.txt"):
            n = update_chat_refs(chat)
            refs_updated += n
            if n:
                print(f"[引用] {chat.name} 更新 {n} 处 .wxgf → .jpg")

    print(f"\n完成: 转换 {converted} 张, 失败 {failed}, 更新引用 {refs_updated} 处")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
