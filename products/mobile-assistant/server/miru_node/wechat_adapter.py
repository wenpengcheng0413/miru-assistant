"""Privacy-scoped read-only WeChat adapter executed only on Windows."""
from __future__ import annotations

from datetime import datetime, timezone
import base64
import hashlib
import json
import re
from pathlib import Path
import sys
import time
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


class WeChatNodeAdapter:
    def __init__(
        self,
        data_root: str = "",
        *,
        reader_factory: Callable[[str], Any] | None = None,
        max_days: int = 90,
        max_results: int = 20,
    ) -> None:
        self.data_root = data_root
        self.reader_factory = reader_factory
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
