"""图片附件必须以原始字节交给视觉模型。"""
from __future__ import annotations

import base64
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from miru_server.attachments import (
    image_content_block,
    image_dimensions,
    save_upload,
    vision_image_blocks,
)
from miru_server.config import AttachmentConfig


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


@pytest.mark.asyncio
async def test_upload_is_refused_at_critical_disk_pressure(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "miru_server.attachments.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=100, free=9),
    )
    upload = UploadFile(file=io.BytesIO(b"safe"), filename="note.txt")

    with pytest.raises(HTTPException) as raised:
        await save_upload(upload, tmp_path / "attachments", AttachmentConfig())

    assert raised.value.status_code == 507
    assert not list((tmp_path / "attachments").rglob("*.txt"))


@pytest.mark.asyncio
async def test_upload_is_refused_above_attachment_soft_quota(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "miru_server.attachments.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=100, free=100),
    )
    monkeypatch.setattr(
        "miru_server.attachments._stored_bytes",
        lambda _path: 1024 * 1024 * 1024,
    )
    upload = UploadFile(file=io.BytesIO(b"safe"), filename="note.txt")

    with pytest.raises(HTTPException) as raised:
        await save_upload(
            upload,
            tmp_path / "attachments",
            AttachmentConfig(soft_quota_gb=1),
        )

    assert raised.value.status_code == 507
