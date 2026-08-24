#!/usr/bin/env python
"""Attach chat timestamps and senders to an existing image OCR index."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from miru.chat_analyzer.statistics import parse_chat_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat", type=Path, required=True)
    parser.add_argument("--ocr", type=Path, required=True)
    args = parser.parse_args()

    records = parse_chat_file(args.chat.read_text(encoding="utf-8"))
    context: dict[str, tuple[str, str]] = {}
    for record in records:
        match = re.match(r"^\[图片\]\s+(media/img/\S+)", record.content)
        if match:
            context[match.group(1)] = (
                record.timestamp.strftime("%Y-%m-%d %H:%M"),
                record.sender,
            )

    payload = json.loads(args.ocr.read_text(encoding="utf-8"))
    matched = 0
    for item in payload.get("items", []):
        file_name = str(item.get("file", ""))
        if file_name in context:
            item["timestamp"], item["sender"] = context[file_name]
            matched += 1
    payload["context_matched"] = matched
    payload["context_unmatched"] = len(payload.get("items", [])) - matched
    args.ocr.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"matched": matched, "unmatched": payload["context_unmatched"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
