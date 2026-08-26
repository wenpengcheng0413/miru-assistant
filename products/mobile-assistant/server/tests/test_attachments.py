"""图片附件必须以原始字节交给视觉模型。"""
from __future__ import annotations

import base64
from pathlib import Path

from miru_server.attachments import image_content_block


def test_image_content_block_uses_original_bytes_and_detail(tmp_path: Path):
    image = tmp_path / "photo.jpg"
    raw = b"\xff\xd8\xff" + bytes(range(256))
    image.write_bytes(raw)

    block = image_content_block(image)

    payload = block["image_url"]
    assert payload["detail"] == "original"
    assert base64.b64decode(payload["url"].split(",", 1)[1]) == raw
