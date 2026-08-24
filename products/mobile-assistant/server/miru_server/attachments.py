"""附件安全落盘、类型识别与给模型构造图片块。"""
from __future__ import annotations

import base64
import hashlib
import re
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
    media_type, kind, _ = detect_type(path.read_bytes()[:32], path.name)
    if kind != "image":
        raise ValueError(f"不是图片: {path.name}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type};base64,{encoded}", "detail": "original"},
    }
