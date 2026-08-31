"""Privacy-scoped read-only WeChat adapter executed only on Windows."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


_XML_KINDS = {
    "img": "图片",
    "videomsg": "视频",
    "appmsg": "链接/卡片",
    "emoji": "表情",
    "voicemsg": "语音",
    "location": "位置",
    "record": "聊天记录",
    "refermsg": "引用消息",
    "patmsg": "拍一拍",
}

_MESSAGE_KINDS = {
    1: "text",
    3: "image",
    34: "voice",
    43: "video",
    47: "emoji",
    49: "app",
    10000: "system",
}

_STT_LOCK = threading.Lock()
_VOICE_TRANSCRIPT_CACHE: dict[int, str] = {}


class WeChatAdapterError(Exception):
    def __init__(self, error_code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.retryable = retryable


def _reader_class():
    here = Path(__file__).resolve()
    source = here.parents[3] / "daily-report" / "src"
    if not (source / "miru").is_dir():
        raise WeChatAdapterError("wechat_dependency_missing", "微信读取组件不可用")
    value = str(source)
    if value not in sys.path:
        sys.path.insert(0, value)
    # The legacy reader uses Loguru and its default sink includes detected
    # account paths. The node guardian must remain value-free, so disable that
    # sink before importing any ``miru`` module.
    try:
        from loguru import logger as legacy_logger

        legacy_logger.remove()
    except Exception:
        pass
    try:
        from miru.chat_analyzer.offline_reader import OfflineWeChatDB
    except Exception as exc:
        raise WeChatAdapterError("wechat_dependency_missing", "微信读取组件不可用") from exc
    return OfflineWeChatDB


def _voice_extractor_class():
    _reader_class()
    try:
        from miru.chat_analyzer.media.voice import VoiceExtractor
    except Exception as exc:
        raise WeChatAdapterError("wechat_voice_dependency_missing", "微信语音解码组件不可用") from exc
    return VoiceExtractor


def _image_extractor_class():
    _reader_class()
    try:
        from miru.chat_analyzer.media.image import ImageExtractor
    except Exception as exc:
        raise WeChatAdapterError("wechat_image_dependency_missing", "微信图片解密组件不可用") from exc
    return ImageExtractor


def _sensevoice_engine(model_dir: str):
    try:
        from .speech import sensevoice_engine

        return sensevoice_engine(model_dir)
    except Exception as exc:
        raise WeChatAdapterError("wechat_stt_unavailable", "本机微信语音识别不可用") from exc


def _clean_content(value: Any, max_chars: int = 300) -> str:
    content = str(value or "").strip()
    if content.startswith("<?xml") or "<msg>" in content[:200]:
        title = re.search(r"<title>(.*?)</title>", content, flags=re.S)
        if title and title.group(1).strip():
            text = re.sub(r"\s+", " ", title.group(1).strip())[:80]
            return f"[链接: {text}]"
        match = re.search(r"<(" + "|".join(_XML_KINDS) + r")", content)
        return f"[{_XML_KINDS.get(match.group(1), '媒体消息') if match else '媒体消息'}]"
    content = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", content)
    return content[:max_chars] + ("…" if len(content) > max_chars else "")


def _image_md5(value: Any) -> str:
    raw = str(value or "")
    match = re.search(r"(?:cdnmidimgurl|md5|cdnthumburl)=['\"][^'\"]*?([a-fA-F0-9]{32})", raw)
    if not match:
        match = re.search(r"\b([a-fA-F0-9]{32})\b", raw)
    return match.group(1).lower() if match else ""


def _image_source(path: Path) -> str:
    stem = path.stem.lower()
    if stem.endswith("_h"):
        return "high_definition"
    if stem.endswith("_t"):
        return "thumbnail"
    return "original"


def _image_candidate_key(path: Path, timestamp: float) -> tuple[int, int, float, int]:
    """Prefer HD/original variants while using time distance to prevent cross-image matches."""
    tier = {"high_definition": 0, "original": 1, "thumbnail": 2}[_image_source(path)]
    try:
        stat = path.stat()
        delta = abs(stat.st_mtime - timestamp)
        return int(delta // 300), tier, delta, -stat.st_size
    except OSError:
        # Test doubles and transient files may not expose stat; retain deterministic
        # quality ordering and let decrypt() decide whether the candidate is usable.
        return 10**12, tier, 10**12, 0


def _decode_wxgf_to_jpeg(data: bytes) -> bytes | None:
    """Decode WeChat's WXGF/HEVC original locally before it leaves the Home Node."""
    start = data.find(b"\x00\x00\x00\x01")
    if start < 0 or not shutil.which("ffmpeg"):
        return None
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "hevc", "-i", "-", "-frames:v", "1",
                "-f", "image2pipe", "-vcodec", "mjpeg", "-",
            ],
            input=data[start:],
            capture_output=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (
        result.stdout
        if result.returncode == 0 and result.stdout.startswith(b"\xff\xd8\xff")
        else None
    )


class WeChatNodeAdapter:
    def __init__(
        self,
        data_root: str = "",
        *,
        reader_factory: Callable[[str], Any] | None = None,
        voice_extractor_factory: Callable[[Any], Any] | None = None,
        image_extractor_factory: Callable[[Any], Any] | None = None,
        stt_factory: Callable[[str], Any] | None = None,
        stt_model_dir: str = "./data/models/sensevoice",
        max_days: int = 90,
        max_results: int = 20,
    ) -> None:
        self.data_root = data_root
        self.reader_factory = reader_factory
        self.voice_extractor_factory = voice_extractor_factory
        self.image_extractor_factory = image_extractor_factory
        self.stt_factory = stt_factory
        self.stt_model_dir = stt_model_dir
        self.max_days = max(1, min(int(max_days), 90))
        self.max_results = max(1, min(int(max_results), 20))

    def _open(self):
        factory = self.reader_factory or _reader_class()
        try:
            return factory(self.data_root)
        except WeChatAdapterError:
            raise
        except FileNotFoundError as exc:
            raise WeChatAdapterError("wechat_data_missing", "未找到本机微信数据") from exc
        except PermissionError as exc:
            raise WeChatAdapterError("wechat_permission_denied", "本机微信数据不可读") from exc
        except Exception as exc:
            raise WeChatAdapterError("wechat_reader_unavailable", "微信读取器不可用") from exc

    @staticmethod
    def _exact_contact(
        db: Any,
        contact: str,
        *,
        allow_group: bool = False,
    ) -> dict[str, str]:
        try:
            contacts = db.get_contacts()
        except Exception as exc:
            raise WeChatAdapterError("wechat_contacts_unavailable", "微信联系人不可读") from exc
        query = contact.casefold()
        fields = ("display_name", "remark", "nickname", "alias", "username")
        matches = [
            item for item in contacts
            if any(str(item.get(field) or "").casefold() == query for field in fields)
        ]
        unique = {str(item.get("username") or ""): item for item in matches}
        if not unique:
            raise WeChatAdapterError("contact_not_found", "未找到完全匹配的联系人")
        if len(unique) != 1:
            raise WeChatAdapterError("contact_ambiguous", "联系人名称不唯一，请使用精确备注或微信号")
        result = next(iter(unique.values()))
        username = str(result.get("username") or "")
        if not username:
            raise WeChatAdapterError("contact_not_found", "未找到完全匹配的联系人或群聊")
        if username.endswith("@chatroom") and not allow_group:
            raise WeChatAdapterError("contact_scope_denied", "该能力暂不支持群聊")
        return result

    @staticmethod
    def _read_window(db: Any, username: str, days: int) -> list[Any]:
        try:
            tables = db.find_direct_session_tables(username)
        except Exception as exc:
            raise WeChatAdapterError("wechat_session_unavailable", "微信会话索引不可读") from exc
        since = int(time.time()) - days * 86_400
        messages: list[Any] = []
        for table, shard, _ in tables:
            try:
                messages.extend(db.read_messages_since(table, shard, since))
            except Exception:
                continue
        messages.sort(
            key=lambda item: (
                int(getattr(item, "timestamp", 0)),
                int(getattr(item, "server_id", 0)),
            )
        )
        return messages

    @staticmethod
    def _cursor_scope(contact: str, days: int) -> str:
        value = f"{contact.casefold()}\n{days}".encode("utf-8")
        return hashlib.sha256(value).hexdigest()[:16]

    @classmethod
    def _decode_cursor(cls, cursor: str, *, contact: str, days: int) -> int:
        if not cursor:
            return 0
        if not isinstance(cursor, str) or len(cursor) > 160:
            raise WeChatAdapterError("invalid_cursor", "会话游标无效")
        try:
            padding = "=" * (-len(cursor) % 4)
            payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
            offset = int(payload["offset"])
            scope = str(payload["scope"])
        except Exception as exc:
            raise WeChatAdapterError("invalid_cursor", "会话游标无效") from exc
        if offset < 0 or offset > 1_000_000 or scope != cls._cursor_scope(contact, days):
            raise WeChatAdapterError("invalid_cursor", "会话游标与当前查询不匹配")
        return offset

    @classmethod
    def _encode_cursor(cls, offset: int, *, contact: str, days: int) -> str:
        raw = json.dumps(
            {"offset": offset, "scope": cls._cursor_scope(contact, days)},
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _sender_label(item: Any, *, username: str, is_group: bool) -> str:
        sender_username = str(getattr(item, "sender_username", "") or "")
        if not is_group:
            return "contact" if sender_username == username else "self"
        sender = str(getattr(item, "sender", "") or "").strip()
        if sender == "我":
            return "self"
        # Never let unresolved WeChat identifiers cross the node boundary.
        if not sender or sender.casefold().startswith("wxid_") or "@chatroom" in sender:
            return "group_member"
        sender = re.sub(r"[\x00-\x1f]", "", sender)[:80]
        return sender or "group_member"

    def search_messages(self, *, contact: str, keyword: str, days: int = 30, limit: int = 10) -> dict:
        contact = str(contact or "").strip()
        keyword = str(keyword or "").strip()
        if not (1 <= len(contact) <= 80) or not (1 <= len(keyword) <= 100):
            raise WeChatAdapterError("invalid_tool_arguments", "联系人或关键词格式无效")
        days = max(1, min(int(days), self.max_days))
        limit = max(1, min(int(limit), self.max_results))
        db = self._open()
        try:
            resolved = self._exact_contact(db, contact, allow_group=True)
            username = str(resolved["username"])
            is_group = username.endswith("@chatroom")
            messages = self._read_window(db, username, days)
            query = keyword.casefold()
            hits = [item for item in messages if query in str(getattr(item, "content", "")).casefold()]
            samples = []
            for item in hits[-limit:]:
                samples.append({
                    "time": datetime.fromtimestamp(
                        int(getattr(item, "timestamp", 0)), timezone.utc
                    ).isoformat(),
                    "sender": self._sender_label(
                        item,
                        username=username,
                        is_group=is_group,
                    ),
                    "content": _clean_content(getattr(item, "content", "")),
                })
            return {
                "contact": contact,
                "conversation_type": "group" if is_group else "direct",
                "keyword": keyword,
                "days": days,
                "total_hits": len(hits),
                "samples": samples,
                "truncated": len(hits) > len(samples),
            }
        finally:
            try:
                db.close()
            except Exception:
                pass

    def conversation_messages(
        self,
        *,
        contact: str,
        days: int = 30,
        limit: int = 20,
        cursor: str = "",
    ) -> dict:
        """Return one bounded page, newest page first and chronological within a page."""
        contact = str(contact or "").strip()
        if not (1 <= len(contact) <= 80):
            raise WeChatAdapterError("invalid_tool_arguments", "联系人或群聊格式无效")
        days = max(1, min(int(days), self.max_days))
        limit = max(1, min(int(limit), self.max_results))
        offset = self._decode_cursor(str(cursor or ""), contact=contact, days=days)
        db = self._open()
        try:
            resolved = self._exact_contact(db, contact, allow_group=True)
            username = str(resolved["username"])
            is_group = username.endswith("@chatroom")
            messages = self._read_window(db, username, days)
            end = max(0, len(messages) - offset)
            start = max(0, end - limit)
            page = messages[start:end]
            rows = []
            for item in page:
                msg_type = int(getattr(item, "msg_type", 0) or 0)
                rows.append({
                    "time": datetime.fromtimestamp(
                        int(getattr(item, "timestamp", 0)), timezone.utc
                    ).isoformat(),
                    "sender": self._sender_label(
                        item,
                        username=username,
                        is_group=is_group,
                    ),
                    "message_type": _MESSAGE_KINDS.get(msg_type, "other"),
                    "content": _clean_content(getattr(item, "content", ""), max_chars=360),
                })
            consumed = offset + len(page)
            has_more = start > 0
            return {
                "contact": contact,
                "conversation_type": "group" if is_group else "direct",
                "days": days,
                "messages": rows,
                "has_more": has_more,
                "next_cursor": (
                    self._encode_cursor(consumed, contact=contact, days=days)
                    if has_more
                    else ""
                ),
            }
        finally:
            try:
                db.close()
            except Exception:
                pass

    def transcribe_voice(
        self,
        *,
        contact: str,
        days: int = 30,
        limit: int = 10,
        cursor: str = "",
    ) -> dict:
        """Decode and transcribe a bounded page of WeChat voice locally."""
        contact = str(contact or "").strip()
        if not (1 <= len(contact) <= 80):
            raise WeChatAdapterError("invalid_tool_arguments", "联系人或群聊格式无效")
        days = max(1, min(int(days), self.max_days))
        limit = max(1, min(int(limit), min(self.max_results, 10)))
        scope_contact = f"voice:{contact}"
        offset = self._decode_cursor(str(cursor or ""), contact=scope_contact, days=days)
        db = self._open()
        try:
            resolved = self._exact_contact(db, contact, allow_group=True)
            username = str(resolved["username"])
            is_group = username.endswith("@chatroom")
            voices = [
                item for item in self._read_window(db, username, days)
                if int(getattr(item, "msg_type", 0) or 0) == 34
                and int(getattr(item, "server_id", 0) or 0) > 0
            ]
            end = max(0, len(voices) - offset)
            start = max(0, end - limit)
            page = voices[start:end]
            extractor_cls = self.voice_extractor_factory or _voice_extractor_class()
            extractor = extractor_cls(db)
            ids = [int(getattr(item, "server_id", 0)) for item in page]
            try:
                voice_data = extractor.iter_voice_ids(ids)
            except Exception:
                voice_data = {}
            engine = None
            rows = []
            for item in page:
                server_id = int(getattr(item, "server_id", 0))
                transcript = _VOICE_TRANSCRIPT_CACHE.get(server_id, "")
                error = ""
                if not transcript:
                    silk = voice_data.get(server_id)
                    if not silk:
                        error = "voice_data_missing"
                    else:
                        try:
                            pcm = extractor.decode_to_pcm_cached(server_id, silk)
                        except Exception:
                            pcm = None
                        if not pcm:
                            error = "voice_decode_failed"
                        else:
                            if engine is None:
                                factory = self.stt_factory or _sensevoice_engine
                                engine = factory(self.stt_model_dir)
                            try:
                                # The recognizer is not assumed thread-safe. This also
                                # prevents simultaneous voice jobs doubling peak memory.
                                with _STT_LOCK:
                                    transcript = str(engine.transcribe(pcm, 16000) or "").strip()
                            except Exception:
                                error = "voice_transcription_failed"
                            if transcript:
                                if len(_VOICE_TRANSCRIPT_CACHE) >= 500:
                                    _VOICE_TRANSCRIPT_CACHE.pop(next(iter(_VOICE_TRANSCRIPT_CACHE)))
                                _VOICE_TRANSCRIPT_CACHE[server_id] = transcript[:1000]
                rows.append({
                    "time": datetime.fromtimestamp(
                        int(getattr(item, "timestamp", 0)), timezone.utc
                    ).isoformat(),
                    "sender": self._sender_label(
                        item,
                        username=username,
                        is_group=is_group,
                    ),
                    "transcript": transcript[:1000],
                    "error": error,
                })
            consumed = offset + len(page)
            has_more = start > 0
            return {
                "contact": contact,
                "conversation_type": "group" if is_group else "direct",
                "days": days,
                "voice_messages": rows,
                "transcribed": sum(bool(item["transcript"]) for item in rows),
                "has_more": has_more,
                "next_cursor": (
                    self._encode_cursor(consumed, contact=scope_contact, days=days)
                    if has_more
                    else ""
                ),
            }
        finally:
            try:
                db.close()
            except Exception:
                pass

    def extract_original_images(
        self,
        *,
        contact: str,
        days: int = 7,
        limit: int = 3,
        cursor: str = "",
    ) -> dict:
        """Decrypt a bounded image page locally; bytes stay private to the node client."""
        contact = str(contact or "").strip()
        if not (1 <= len(contact) <= 80):
            raise WeChatAdapterError("invalid_tool_arguments", "联系人或群聊格式无效")
        days = max(1, min(int(days), self.max_days))
        limit = max(1, min(int(limit), 3))
        scope_contact = f"image:{contact}"
        offset = self._decode_cursor(str(cursor or ""), contact=scope_contact, days=days)
        db = self._open()
        try:
            resolved = self._exact_contact(db, contact, allow_group=True)
            username = str(resolved["username"])
            is_group = username.endswith("@chatroom")
            images = [
                item for item in self._read_window(db, username, days)
                if int(getattr(item, "msg_type", 0) or 0) == 3
            ]
            end = max(0, len(images) - offset)
            start = max(0, end - limit)
            page = images[start:end]
            extractor_cls = self.image_extractor_factory or _image_extractor_class()
            try:
                extractor = extractor_cls(getattr(db, "account_dir"))
            except Exception as exc:
                raise WeChatAdapterError("wechat_image_unavailable", "本机微信原图读取不可用") from exc
            rows = []
            used: set[Path] = set()
            for item in page:
                timestamp = int(getattr(item, "timestamp", 0))
                md5 = _image_md5(getattr(item, "content", "")) or _image_md5(
                    getattr(item, "raw_content", "")
                )
                row = {
                    "time": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
                    "sender": self._sender_label(item, username=username, is_group=is_group),
                    "media_type": "",
                    "size_bytes": 0,
                    "match": "",
                    "error": "",
                    "_bytes": b"",
                    "_extension": "",
                }
                try:
                    candidates = extractor.locate_files(username, timestamp, md5)
                    locate_thumb = getattr(extractor, "locate_thumb", None)
                    if callable(locate_thumb):
                        candidates += [
                            path for path in locate_thumb(username, timestamp, md5)
                            if path not in candidates
                        ]
                    exact = [
                        path for path in candidates
                        if path.stem == md5 or path.stem.startswith(f"{md5}_")
                    ] if md5 else []
                    # A filename MD5 match is stronger evidence than mtime.  Keep
                    # exact variants together and choose HD/original quality
                    # inside that group; only use time matching when WeChat did
                    # not retain a usable exact candidate.
                    ordered = sorted(
                        exact,
                        key=lambda path: _image_candidate_key(path, timestamp),
                    )
                    ordered += sorted(
                        (path for path in candidates if path not in exact),
                        key=lambda path: _image_candidate_key(path, timestamp),
                    )
                    data, extension, selected = None, "", None
                    for candidate in ordered:
                        if candidate in used:
                            continue
                        try:
                            delta = abs(os.path.getmtime(candidate) - timestamp)
                        except OSError:
                            delta = 0 if candidate in exact else 10**12
                        if candidate not in exact and delta > 3600:
                            continue
                        candidate_data = extractor.decrypt(candidate)
                        if not candidate_data:
                            continue
                        candidate_extension = extractor.sniff_format(candidate_data)
                        if candidate_extension == "wxgf":
                            candidate_data = _decode_wxgf_to_jpeg(candidate_data)
                            candidate_extension = "jpg" if candidate_data else ""
                        if candidate_extension not in {"jpg", "png", "gif", "webp"}:
                            continue
                        data, extension, selected = candidate_data, candidate_extension, candidate
                        used.add(candidate)
                        break
                    row["match"] = (
                        "md5_exact" if selected in exact else
                        (f"time_nearest_1h_{_image_source(selected)}" if selected else "")
                    )
                except Exception:
                    data, extension = None, ""
                if not data:
                    row["error"] = "image_decrypt_failed"
                elif extension not in {"jpg", "png", "gif", "webp"}:
                    row["error"] = "image_format_not_displayable"
                elif len(data) > 10 * 1024 * 1024:
                    row["error"] = "image_too_large"
                else:
                    row["media_type"] = "image/jpeg" if extension == "jpg" else f"image/{extension}"
                    row["size_bytes"] = len(data)
                    row["_bytes"] = data
                    row["_extension"] = f".{extension}"
                rows.append(row)
            consumed = offset + len(page)
            has_more = start > 0
            return {
                "contact": contact,
                "conversation_type": "group" if is_group else "direct",
                "days": days,
                "images": rows,
                "has_more": has_more,
                "next_cursor": (
                    self._encode_cursor(consumed, contact=scope_contact, days=days)
                    if has_more
                    else ""
                ),
            }
        finally:
            try:
                db.close()
            except Exception:
                pass
