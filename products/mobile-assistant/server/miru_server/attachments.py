"""附件安全落盘、类型识别与给模型构造图片块。"""
from __future__ import annotations

import base64
import hashlib
import io
import math
import re
import struct
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from .config import AttachmentConfig

_IMAGE_TYPES = {
    b"\xff\xd8\xff": ("image/jpeg", "image", ".jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", "image", ".png"),
    b"GIF87a": ("image/gif", "image", ".gif"),
    b"GIF89a": ("image/gif", "image", ".gif"),
}
_OFFICE_EXTENSIONS = {
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "document"),
    ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "presentation"),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "spreadsheet"),
    ".xls": ("application/vnd.ms-excel", "spreadsheet"),
    ".csv": ("text/csv", "spreadsheet"),
    ".txt": ("text/plain", "text"),
    ".md": ("text/markdown", "text"),
}


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w.\-() \u4e00-\u9fff]", "_", Path(name or "附件").name).strip(". ")
    return (cleaned or "附件")[:120]


def detect_type(data: bytes, filename: str) -> tuple[str, str, str]:
    """不信任客户端 MIME；用文件头和白名单扩展名判定。"""
    for magic, result in _IMAGE_TYPES.items():
        if data.startswith(magic):
            return result
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "image", ".webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf", "document", ".pdf"
    extension = Path(filename).suffix.lower()
    if extension in _OFFICE_EXTENSIONS:
        media_type, kind = _OFFICE_EXTENSIONS[extension]
        return media_type, kind, extension
    raise HTTPException(415, "仅支持 JPG、PNG、GIF、WebP、PDF、Word、Excel、PPT、CSV、TXT、Markdown")


async def save_upload(upload: UploadFile, root: str | Path, config: AttachmentConfig) -> dict:
    max_bytes = max(config.max_file_mb, 1) * 1024 * 1024
    data = await upload.read(max_bytes + 1)
    if not data:
        raise HTTPException(400, "上传的文件为空")
    if len(data) > max_bytes:
        raise HTTPException(413, f"文件超过 {config.max_file_mb}MB 限制")
    filename = safe_filename(upload.filename or "附件")
    media_type, kind, extension = detect_type(data, filename)
    attachment_id = uuid.uuid4().hex
    folder = Path(root) / attachment_id
    folder.mkdir(parents=True, exist_ok=False)
    final_name = filename if Path(filename).suffix else f"{filename}{extension}"
    path = folder / final_name
    path.write_bytes(data)
    return {
        "id": attachment_id,
        "filename": final_name,
        "media_type": media_type,
        "kind": kind,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "local_path": str(path),
    }


def image_content_block(path: str | Path) -> dict:
    """DeepSeek Vision 的 OpenAI 兼容 image_url 数据块。"""
    path = Path(path)
    data = path.read_bytes()
    media_type, kind, _ = detect_type(data[:32], path.name)
    if kind != "image":
        raise ValueError(f"不是图片: {path.name}")
    return _image_block(data, media_type)


def image_metadata(path: str | Path) -> dict:
    """返回图片实际字节、格式与像素尺寸，用于说明视觉输入质量。"""
    path = Path(path)
    data = path.read_bytes()
    media_type, kind, _ = detect_type(data[:32], path.name)
    if kind != "image":
        raise ValueError(f"不是图片: {path.name}")
    width, height = image_dimensions(data)
    return {
        "media_type": media_type,
        "size_bytes": len(data),
        "width": width,
        "height": height,
    }


def vision_image_blocks(path: str | Path, tile_edge: int = 2048, max_tiles: int = 4) -> list[dict]:
    """原图始终发送；超大图额外发送无缩放局部，帮助模型读取小字与细节。"""
    path = Path(path)
    data = path.read_bytes()
    media_type, kind, _ = detect_type(data[:32], path.name)
    if kind != "image":
        raise ValueError(f"不是图片: {path.name}")
    blocks = [_image_block(data, media_type)]
    width, height = image_dimensions(data)
    if not width or not height or (width <= tile_edge and height <= tile_edge):
        return blocks

    # Pillow 只用于生成附加局部；失败时原图仍会照常发送给视觉模型。
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(data))
        image.load()
        columns = max(1, math.ceil(width / tile_edge))
        rows = max(1, math.ceil(height / tile_edge))
        while columns * rows > max_tiles:
            if columns >= rows and columns > 1:
                columns -= 1
            elif rows > 1:
                rows -= 1
            else:
                break
        for row in range(rows):
            for column in range(columns):
                left = width * column // columns
                top = height * row // rows
                right = width * (column + 1) // columns
                bottom = height * (row + 1) // rows
                crop = image.crop((left, top, right, bottom))
                if crop.mode not in {"RGB", "L"}:
                    crop = crop.convert("RGB")
                encoded = io.BytesIO()
                crop.save(encoded, format="JPEG", quality=100, subsampling=0)
                blocks.append({
                    "type": "text",
                    "text": f"以下是原图的高清局部 {row * columns + column + 1}/{rows * columns}，请结合全图读取细节和文字。",
                })
                blocks.append(_image_block(encoded.getvalue(), "image/jpeg"))
    except Exception:
        # 局部图是增强项，不能因图片解码器缺失影响原图分析。
        return blocks[:1]
    return blocks


def image_dimensions(data: bytes) -> tuple[int | None, int | None]:
    """不引入图像库即可读取常见图片的像素尺寸。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if data.startswith(b"BM") and len(data) >= 26:
        width, height = struct.unpack("<ii", data[18:26])
        return abs(width), abs(height)
    if data.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            while index < len(data) and data[index] == 0xFF:
                index += 1
            if index >= len(data):
                break
            marker = data[index]
            index += 1
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(data):
                break
            segment_length = int.from_bytes(data[index:index + 2], "big")
            if segment_length < 2 or index + segment_length > len(data):
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                return (
                    int.from_bytes(data[index + 5:index + 7], "big"),
                    int.from_bytes(data[index + 3:index + 5], "big"),
                )
            index += segment_length
    return None, None


def _image_block(data: bytes, media_type: str) -> dict:
    encoded = base64.b64encode(data).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type};base64,{encoded}", "detail": "original"},
    }
