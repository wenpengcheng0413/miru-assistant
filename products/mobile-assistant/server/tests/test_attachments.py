"""图片附件必须以原始字节交给视觉模型。"""
from __future__ import annotations

import base64
from pathlib import Path

from miru_server.attachments import image_content_block, image_dimensions, vision_image_blocks


def test_image_content_block_uses_original_bytes_and_detail(tmp_path: Path):
    image = tmp_path / "photo.jpg"
    raw = b"\xff\xd8\xff" + bytes(range(256))
    image.write_bytes(raw)

    block = image_content_block(image)

    payload = block["image_url"]
    assert payload["detail"] == "original"
    assert base64.b64decode(payload["url"].split(",", 1)[1]) == raw


def test_vision_image_blocks_adds_high_resolution_tiles(tmp_path: Path):
    from PIL import Image

    image = tmp_path / "screenshot.png"
    Image.new("RGB", (4096, 2300), "white").save(image)

    blocks = vision_image_blocks(image)

    image_blocks = [item for item in blocks if item["type"] == "image_url"]
    assert len(image_blocks) == 5  # 原图 + 4 个无缩放局部
    assert image_dimensions(image.read_bytes()) == (4096, 2300)
    assert all(item["image_url"]["detail"] == "original" for item in image_blocks)
