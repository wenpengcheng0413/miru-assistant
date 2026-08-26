"""微信聊天分析工具 —— 复用现有 miru 包（src/miru/chat_analyzer）。

- import 全部 try/except 保护：后端迁到 Linux VPS 时这些工具自动不可用，其余功能不受影响
- 隐私档位（settings.tools.wechat.llm_visibility）：
    aggregates = 只给统计数字（默认）  samples = 加少量脱敏样例  raw = 原始文本（慎用）
- 离线读取（OfflineWeChatDB）不需要微信运行、不需要管理员权限
"""
from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..base import Tool, ToolContext, ToolResult
from ...attachments import image_content_block
from ...wechat_runtime import data_root_for, ensure_miru_import_path, runtime_diagnostics

logger = logging.getLogger(__name__)
_WECHAT_TZ = ZoneInfo("Asia/Shanghai")
_SYSTEM_USERNAMES = {
    "filehelper", "notifymessage", "fmessage", "floatbottle", "medianote",
    "newsapp", "weixin", "wxid_transfer", "brandsessionholder",
}

ensure_miru_import_path()
try:
    from miru.chat_analyzer.offline_reader import OfflineWeChatDB
    from miru.chat_analyzer.statistics import ChatMessageRecord, compute_statistics
    WECHAT_OK = True
except Exception as e:  # ImportError 或包内依赖缺失（pymem/pysilk 等）
    OfflineWeChatDB = None
    WECHAT_OK = False
    logger.info("现有 miru 包不可用，微信工具自动禁用: %s", e)


def _visibility(ctx: ToolContext) -> str:
    return ctx.services.config.tools.wechat.llm_visibility


_XML_KINDS = {
    "img": "图片", "videomsg": "视频", "appmsg": "链接/卡片",
    "emoji": "表情", "voicemsg": "语音", "location": "位置",
    "record": "聊天记录", "refermsg": "引用消息", "patmsg": "拍一拍",
    "finderFeed": "视频号",
}


def _clean_content(content: str, max_len: int = 500) -> str:
    """消息内容清洗（隐私 + 省 token）：
    - XML 媒体消息（含 aeskey 等敏感字段）→ 可读占位；链接尽量保留标题
    - 超长正文截断
    """
    content = (content or "").strip()
    if content.startswith("<?xml") or "<msg>" in content[:200]:
        title = re.search(r"<title>(.*?)</title>", content)
        if title and title.group(1).strip():
            return f"[链接: {title.group(1).strip()[:50]}]"
        m = re.search(r"<(" + "|".join(_XML_KINDS) + r")", content)
        return f"[{_XML_KINDS.get(m.group(1), '媒体消息') if m else '媒体消息'}]"
    if len(content) > max_len:
        return content[:max_len] + "…"
    return content


def _db(ctx: ToolContext) -> "OfflineWeChatDB":
    global WECHAT_OK, OfflineWeChatDB
    if not WECHAT_OK or OfflineWeChatDB is None:
        ensure_miru_import_path()
        try:
            from miru.chat_analyzer.offline_reader import OfflineWeChatDB as reader
            OfflineWeChatDB = reader
            WECHAT_OK = True
        except Exception as exc:
            diag = runtime_diagnostics(ctx.services.config)
            raise RuntimeError(
                f"WECHAT_DEPENDENCY_ERROR: 微信工具不可用：{exc}；"
                f"miru_path={diag.get('package_path') or '未找到'}；"
                f"data_dir={diag.get('data_dir') or '未找到'}"
            ) from exc
    data_root = data_root_for(ctx.services.config)
    # 同步构造放到线程里（内部有文件 IO）
    return OfflineWeChatDB(data_root or "")


async def _step(ctx: ToolContext, phase: str, title: str, detail: str = "", status: str = "done") -> None:
    """给手机端发送安全的执行摘要；不会包含模型隐藏推理。"""
    if not ctx.emit:
        return
    ctx.process_seq += 1
    await ctx.emit({
        "type": "process_step", "turn_id": ctx.turn_id, "seq": ctx.process_seq,
        "phase": phase, "title": title, "detail": detail, "status": status,
    })


def _is_system_contact(contact: dict) -> bool:
    username = str(contact.get("username") or "").lower()
    return username in _SYSTEM_USERNAMES or username.endswith("@openim")


def _search_contacts(
    db, query: str = "", limit: int = 20, include_system: bool = False
) -> list[dict]:
    """按昵称/备注/显示名模糊搜索（大小写不敏感）；query 为空返回前 N 条。"""
    contacts = db.get_contacts()
    if not include_system:
        contacts = [c for c in contacts if not _is_system_contact(c)]
    if not query:
        return contacts[:limit]
    q = query.lower()
    fields = ("nickname", "remark", "alias", "display_name")
    hits = [
        c for c in contacts
        if any(q in (c.get(f) or "").lower() for f in fields)
    ]
    # 昵称完全一致的排最前（如 "krista" 命中 "Krista"）
    hits.sort(key=lambda c: (c.get("nickname") or "").lower() != q)
    return hits[:limit]


def _resolve_contact(db, name: str) -> dict[str, str]:
    """解析联系人；失败时给模型返回安全的候选名称，便于自动纠错。"""
    try:
        return db.resolve_contact(name)
    except Exception as exc:
        candidates = _search_contacts(db, name, 5)
        names = [
            str(c.get("display_name") or c.get("nickname") or c.get("remark") or "")
            for c in candidates
        ]
        hint = f"；候选联系人: {', '.join(n for n in names if n)}" if names else ""
        raise RuntimeError(f"未找到联系人‘{name}’{hint}") from exc


def _self_wxid(db) -> str:
    """在 Name2Id 中排除所有联系人 username 与群（@chatroom）后，剩余唯一条目 = 自己。"""
    try:
        from miru.chat_analyzer.offline_reader import MESSAGE_SHARDS
    except ImportError:
        return ""
    contacts = {c["username"] for c in db.get_contacts()}
    seen: set[str] = set()
    for rel in MESSAGE_SHARDS:
        try:
            conn = db.open(rel)
        except Exception:
            continue
        try:
            seen.update(
                u or "" for (u,) in conn.execute("SELECT user_name FROM Name2Id").fetchall()
            )
        except sqlite3.OperationalError:
            continue
    candidates = [u for u in seen if u and u not in contacts and not u.endswith("@chatroom")]
    return candidates[0] if len(candidates) == 1 else ""


def _read_session_all_shards(db, wxid: str) -> list:
    """跨分片读取会话的全部消息（按时间升序合并）。

    按表名规则 Msg_{MD5(wxid)} 直接定位——群聊必须走这条路：
    find_session_tables 的启发式靠"对方 rowid 出现在 real_sender_id"，
    群消息里只有成员 rowid、没有群自己的 rowid，所以群表永远找不到。
    微信会把同一会话拆到多个分片，这里全部合并。
    """
    try:
        from miru.chat_analyzer.offline_reader import MESSAGE_SHARDS, session_table_md5
    except ImportError:
        return []
    name = f"Msg_{session_table_md5(wxid)}"
    messages: list = []
    for rel in MESSAGE_SHARDS:
        try:
            conn = db.open(rel)
        except Exception:
            continue
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
                (name,),
            ).fetchone()
        except sqlite3.OperationalError:
            continue
        if row:
            messages.extend(db.read_all_messages(name, rel))
    return sorted(messages, key=lambda m: m.timestamp)


def _resolve_session_messages(db, wxid: str) -> list:
    """读取会话消息：表名直查优先（群聊必须），发送者启发式兜底（旧路径）。"""
    messages = _read_session_all_shards(db, wxid)
    if messages:
        return messages
    tables = db.find_session_tables(wxid)
    if not tables:
        raise RuntimeError("未找到该会话记录")
    table, shard, _ = tables[0]
    return db.read_all_messages(table, shard)


def _messages_to_records(messages: list, self_wxid: str = "") -> list:
    records = []
    for m in messages:
        is_self = (m.sender == "我") or (self_wxid and m.sender_username == self_wxid)
        records.append(ChatMessageRecord(
            timestamp=datetime.fromtimestamp(m.timestamp),
            sender="我" if is_self else m.sender,
            content=m.content,
            is_self=is_self,
        ))
    return records


def _format_messages(messages: list, self_wxid: str = "") -> list[str]:
    """消息 → 可读行列表；自己（wxid）统一显示为"我"。"""
    lines = []
    for m in messages:
        t = datetime.fromtimestamp(m.timestamp).strftime("%m-%d %H:%M")
        is_self = (m.sender == "我") or (self_wxid and m.sender_username == self_wxid)
        who = "我" if is_self else (m.sender or "对方")
        lines.append(f"[{t}] {who}: {_clean_content(m.content)}")
    return lines


def _image_md5(raw: str) -> str:
    """从微信图片 XML 中提取 CDN md5（仅用于本地文件匹配）。"""
    match = re.search(r'\bmd5=["\']([0-9a-fA-F]{16,64})["\']', raw or "")
    return match.group(1).lower() if match else ""


def _export_image(extractor, wxid: str, message, export_dir: Path, used: set[Path]) -> tuple[Path | None, str]:
    """提取一条图片消息，优先使用完整原图，不能解码时才回退缩略图。"""
    md5 = _image_md5(getattr(message, "raw_content", "")) or _image_md5(getattr(message, "content", ""))
    # _t.dat 是微信为列表预览生成的低分辨率缩略图。此前它排在原图前面，
    # 会让视觉模型即使使用 detail=original 也只能看到模糊版本。
    candidates = extractor.locate_files(wxid, message.timestamp, md5)
    candidates += [p for p in extractor.locate_thumb(wxid, message.timestamp, md5) if p not in candidates]
    if not candidates:
        return None, "未找到对应的微信图片文件"
    # 同一会话可能有多条图片，优先挑离消息时间最近且尚未使用的文件。
    ordered = sorted(candidates, key=lambda p: abs(p.stat().st_mtime - message.timestamp) if p.exists() else 10**18)
    ordered += [p for p in candidates if p not in ordered]
    for dat_path in ordered:
        if dat_path in used:
            continue
        data = extractor.decrypt(dat_path)
        if not data:
            continue
        ext = extractor.sniff_format(data)
        if ext not in {"jpg", "png", "gif", "webp", "bmp"}:
            continue
        stem = f"wechat_{int(message.timestamp)}_{int(getattr(message, 'server_id', 0) or 0)}"
        out = export_dir / f"{stem}.{ext}"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        used.add(dat_path)
        return out, ""
    return None, "图片已找到但解密后格式不可供视觉模型读取"


class WechatContactListTool(Tool):
    name = "wechat_contact_list"
    description = (
        "查找微信联系人（离线读取，本地处理）。"
        "用户提到的人名可能对应昵称或备注，且大小写随意——用 query 参数在本机模糊搜索，"
        "返回候选的联系人（含显示名/昵称/备注）。不给 query 则返回列表前若干条。"
        "联系人列表里包含微信群（群名同样可搜）；要列出全部群用 wechat_group_list。"
        "后续要分析某人的聊天时，直接用这里命中的显示名调用 wechat_chat_stats。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索词（昵称/备注/显示名片段，大小写不敏感）"},
            "limit": {"type": "integer", "description": "最多返回条数", "default": 20},
            "include_system": {"type": "boolean", "description": "是否包含系统账号，默认 false", "default": False},
        },
    }

    async def run(
        self, ctx: ToolContext, query: str = "", limit: int = 20, include_system: bool = False
    ) -> ToolResult:
        limit = max(1, min(int(limit), 100))
        def _do():
            db = _db(ctx)
            try:
                return _search_contacts(db, query, limit, include_system)
            finally:
                db.close()
        try:
            contacts = await asyncio.to_thread(_do)
        except Exception as e:
            return ToolResult.failure(f"微信联系人读取失败: {e}")
        # 隐私：只送名字类字段（显示名/昵称/备注），wxid 不外发
        data = [
            {
                "name": c.get("display_name") or "",
                "nickname": c.get("nickname") or "",
                "remark": c.get("remark") or "",
            }
            for c in contacts
        ]
        summary = f"命中 {len(data)} 个联系人" if query else f"已读取前 {len(data)} 个联系人"
        return ToolResult.success(data, summary=summary)


class WechatRecentActivityTool(Tool):
    name = "wechat_recent_activity"
    timeout_s = 120.0
    description = (
        "统计最近一段时间内和我实际发生过消息的微信联系人或群聊。"
        "用户问‘最近一小时和谁说过话/谁联系过我’时直接使用；无需先调用联系人列表。"
        "只返回聚合统计，不返回聊天原文。默认 minutes=60，可覆盖最近 1 到 1440 分钟。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "minutes": {"type": "integer", "description": "最近多少分钟，默认 60", "default": 60, "minimum": 1, "maximum": 1440},
            "limit": {"type": "integer", "description": "最多返回多少个会话，默认 50", "default": 50, "minimum": 1, "maximum": 200},
            "include_groups": {"type": "boolean", "description": "是否包含群聊，默认 true", "default": True},
        },
    }

    async def run(
        self,
        ctx: ToolContext,
        minutes: int = 60,
        limit: int = 50,
        include_groups: bool = True,
    ) -> ToolResult:
        minutes = max(1, min(int(minutes), 1440))
        limit = max(1, min(int(limit), 200))
        now = int(time.time())
        since = now - minutes * 60
        await _step(ctx, "wechat", "正在统计最近聊天", f"最近 {minutes} 分钟，跨全部联系人和群聊")

        def _do() -> dict[str, Any]:
            db = _db(ctx)
            try:
                contacts = db.get_contacts()
                contact_by_username = {
                    str(c.get("username") or ""): c
                    for c in contacts
                    if c.get("username") and not _is_system_contact(c)
                }
                if not include_groups:
                    contact_by_username = {
                        u: c for u, c in contact_by_username.items()
                        if not u.endswith("@chatroom")
                    }
                try:
                    from miru.chat_analyzer.offline_reader import MESSAGE_SHARDS, session_table_md5
                except ImportError as exc:
                    raise RuntimeError(f"WECHAT_READER_ERROR: 无法加载消息读取器: {exc}") from exc

                self_wxid = _self_wxid(db)
                # 先枚举每个分片的 Msg_* 表，再只查询实际存在的联系人会话。
                table_to_username = {
                    f"Msg_{session_table_md5(username)}": username
                    for username in contact_by_username
                }
                rows_by_username: dict[str, list] = defaultdict(list)
                warnings: list[str] = []
                scanned_shards = 0
                seen_messages: set[tuple] = set()
                for rel in MESSAGE_SHARDS:
                    path = Path(db.account_dir) / "db_storage" / rel
                    if not path.exists():
                        warnings.append(f"缺少消息分片: {rel}")
                        continue
                    scanned_shards += 1
                    tables = db.list_message_tables(rel)
                    for table in tables & table_to_username.keys():
                        username = table_to_username[table]
                        try:
                            messages = db.read_messages_since(table, rel, since, now)
                        except Exception as exc:
                            warnings.append(f"分片 {rel} 的会话读取失败: {type(exc).__name__}")
                            continue
                        for message in messages:
                            key = (
                                username,
                                int(message.server_id or 0),
                            ) if message.server_id else (
                                username, int(message.timestamp), message.sender_username,
                                message.content,
                            )
                            if key in seen_messages:
                                continue
                            seen_messages.add(key)
                            rows_by_username[username].append(message)

                conversations = []
                for username, messages in rows_by_username.items():
                    if not messages:
                        continue
                    contact = contact_by_username.get(username, {})
                    ordered = sorted(messages, key=lambda message: message.timestamp)
                    from_me = sum(
                        1 for message in ordered
                        if message.sender == "我" or (self_wxid and message.sender_username == self_wxid)
                    )
                    conversations.append({
                        "name": contact.get("display_name") or contact.get("nickname") or username,
                        "nickname": contact.get("nickname") or "",
                        "remark": contact.get("remark") or "",
                        "is_group": username.endswith("@chatroom"),
                        "message_count": len(ordered),
                        "from_me": from_me,
                        "from_others": len(ordered) - from_me,
                        "first_at": datetime.fromtimestamp(ordered[0].timestamp, _WECHAT_TZ).isoformat(),
                        "last_at": datetime.fromtimestamp(ordered[-1].timestamp, _WECHAT_TZ).isoformat(),
                    })
                conversations.sort(key=lambda item: (-item["message_count"], item["name"]))
                return {
                    "window_start": datetime.fromtimestamp(since, _WECHAT_TZ).isoformat(),
                    "window_end": datetime.fromtimestamp(now, _WECHAT_TZ).isoformat(),
                    "timezone": "Asia/Shanghai",
                    "total_messages": sum(item["message_count"] for item in conversations),
                    "conversation_count": len(conversations),
                    "conversations": conversations[:limit],
                    "source": "snapshot" if data_root_for(ctx.services.config) != (ctx.services.config.tools.wechat.data_root or "") else "database",
                    "scanned_shards": scanned_shards,
                    "partial": bool(warnings),
                    "warnings": warnings,
                }
            finally:
                db.close()

        try:
            data = await asyncio.to_thread(_do)
        except Exception as exc:
            return ToolResult.failure(f"微信最近聊天统计失败: {exc}")
        return ToolResult.success(
            data,
            summary=f"最近 {minutes} 分钟涉及 {data['conversation_count']} 个会话，共 {data['total_messages']} 条消息",
        )


class WechatChatStatsTool(Tool):
    name = "wechat_chat_stats"
    timeout_s = 60.0
    description = (
        "统计与某个联系人或群的聊天数据：消息总数、双方发送数、主动发起次数、回复比例、"
        "时间分布、高频词。用户问'我最近和 XX 聊天多吗/关系怎么样'时使用。"
        "contact 可为联系人显示名或群名（群名先用 wechat_group_list / wechat_contact_list 确认）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "contact": {"type": "string", "description": "联系人或群显示名（先从 wechat_contact_list / wechat_group_list 确认）"},
            "limit": {"type": "integer", "description": "最多读取最近 N 条消息", "default": 5000},
        },
        "required": ["contact"],
    }

    async def run(self, ctx: ToolContext, contact: str, limit: int = 5000) -> ToolResult:
        limit = max(1, min(int(limit), 20_000))
        def _do():
            db = _db(ctx)
            try:
                info = _resolve_contact(db, contact)
                messages = _resolve_session_messages(db, info["username"])
                return messages[-limit:], _self_wxid(db)
            finally:
                db.close()
        try:
            messages, self_wxid = await asyncio.to_thread(_do)
        except Exception as e:
            return ToolResult.failure(f"聊天记录读取失败: {e}")
        stats = compute_statistics(_messages_to_records(messages, self_wxid), contact_name=contact)
        if _visibility(ctx) == "raw":
            stats["_recent_messages"] = [
                f"[{datetime.fromtimestamp(m.timestamp):%m-%d %H:%M}] {m.sender}: {m.content}"
                for m in messages[-20:]
            ]
        return ToolResult.success(stats, summary=f"已统计与 {contact} 的 {len(messages)} 条消息")


class WechatSearchMessagesTool(Tool):
    name = "wechat_search_messages"
    description = (
        "按关键词搜索与某联系人或群的聊天记录（本地搜索，默认只返回匹配条数与少量样例）。"
        "contact 可为联系人显示名或群名（群名先用 wechat_group_list / wechat_contact_list 确认）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "contact": {"type": "string"},
            "keyword": {"type": "string"},
            "limit": {"type": "integer", "description": "返回样例条数", "default": 10},
        },
        "required": ["contact", "keyword"],
    }

    async def run(self, ctx: ToolContext, contact: str, keyword: str, limit: int = 10) -> ToolResult:
        def _do():
            db = _db(ctx)
            try:
                info = _resolve_contact(db, contact)
                messages = _resolve_session_messages(db, info["username"])
                return messages, _self_wxid(db)
            finally:
                db.close()
        try:
            messages, self_wxid = await asyncio.to_thread(_do)
        except Exception as e:
            return ToolResult.failure(f"聊天记录读取失败: {e}")

        hits = [m for m in messages if keyword in m.content]
        if _visibility(ctx) == "aggregates":
            data = {"total_hits": len(hits), "samples": []}
        else:
            data = {
                "total_hits": len(hits),
                "samples": _format_messages(hits[-limit:], self_wxid),
            }
        return ToolResult.success(data, summary=f"关键词'{keyword}'命中 {len(hits)} 条")


class WechatRecentMessagesTool(Tool):
    name = "wechat_recent_messages"
    timeout_s = 60.0
    max_result_chars = 30000
    description = (
        "读取与某联系人或群最近几天的聊天记录**全文**（含时间与说话人，本地读取）。"
        "用户说'查聊天记录 / 最近聊了什么 / 把聊天内容读一遍再分析 / 我们聊了啥'时用它——"
        "它比 wechat_search_messages（关键词检索）信息完整得多。"
        "contact 可为联系人显示名或群名（群名先用 wechat_group_list / wechat_contact_list 确认）。"
        "拿到全文后结合 wechat_chat_stats 做内容级分析（话题、语气、最近变化）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "contact": {"type": "string", "description": "联系人或群显示名（先 wechat_contact_list / wechat_group_list 确认）"},
            "days": {"type": "integer", "description": "最近几天，默认 7", "default": 7},
            "limit": {"type": "integer", "description": "最多返回条数，默认 100，上限 500", "default": 100},
        },
        "required": ["contact"],
    }

    async def run(self, ctx: ToolContext, contact: str, days: int = 7, limit: int = 100) -> ToolResult:
        limit = max(1, min(limit, 500))

        def _do():
            db = _db(ctx)
            try:
                info = _resolve_contact(db, contact)
                messages = _resolve_session_messages(db, info["username"])
                cutoff = time.time() - days * 86400
                recent = [m for m in messages if m.timestamp >= cutoff]
                return recent[-limit:], _self_wxid(db)
            finally:
                db.close()

        try:
            messages, self_wxid = await asyncio.to_thread(_do)
        except Exception as e:
            return ToolResult.failure(f"聊天记录读取失败: {e}")

        # 隐私档位：aggregates 只给计数；samples/raw 给全文（用户显式要求内容分析时）
        if _visibility(ctx) == "aggregates":
            return ToolResult.success(
                {"message_count": len(messages)},
                summary=f"档位为 aggregates，仅返回计数（{len(messages)} 条）",
            )

        return ToolResult.success(
            {"days": days, "message_count": len(messages), "messages": _format_messages(messages, self_wxid)},
            summary=f"已读取最近 {days} 天的 {len(messages)} 条消息全文",
        )


class WechatTranscribeVoiceTool(Tool):
    """把微信语音在本机解码、转写，并以可引用的文本交给后续分析。"""

    name = "wechat_transcribe_voice"
    timeout_s = 300.0
    max_result_chars = 30000
    description = (
        "转写与某联系人或群的微信语音消息。语音 SILK 解码和语音识别均在本机完成，"
        "返回每条语音的时间、发送者和转写文本。用户问'语音里说了什么/把语音内容也纳入分析'时使用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "contact": {"type": "string", "description": "联系人或群显示名"},
            "days": {"type": "integer", "description": "最近几天，默认 30", "default": 30},
            "limit": {"type": "integer", "description": "最多转写几条，默认 20，最大 500", "default": 20},
        },
        "required": ["contact"],
    }

    async def run(self, ctx: ToolContext, contact: str, days: int = 30, limit: int = 20) -> ToolResult:
        days = max(1, min(days, 3650))
        limit = max(1, min(limit, 500))

        await _step(ctx, "wechat", "正在检查微信离线快照", "默认读取最近一次同步的数据")

        def _do() -> tuple[list[dict], int]:
            from miru.chat_analyzer.media.voice import VoiceExtractor
            from ...db.models import WechatVoiceTranscript

            db = _db(ctx)
            try:
                info = _resolve_contact(db, contact)
                cutoff = time.time() - days * 86400
                voices = [
                    message for message in _resolve_session_messages(db, info["username"])
                    if message.msg_type == 34 and message.timestamp >= cutoff and message.server_id
                ][-limit:]
                self_wxid = _self_wxid(db)
                extractor = VoiceExtractor(db)
                output: list[dict] = []
                voice_data = extractor.iter_voice_ids([int(m.server_id) for m in voices if m.server_id])
                for index, message in enumerate(voices, 1):
                    with ctx.services.db() as session:
                        cached = session.get(WechatVoiceTranscript, message.server_id)
                    text = cached.transcript if cached else ""
                    error = ""
                    if not text:
                        silk = voice_data.get(int(message.server_id))
                        if not silk:
                            error = "未找到语音原始数据"
                        else:
                            pcm = extractor.decode_to_pcm_cached(message.server_id, silk)
                            if not pcm:
                                error = "语音解码失败"
                            else:
                                try:
                                    text = (ctx.services.stt.transcribe(pcm, 16000) or "").strip()
                                except Exception as e:
                                    error = f"本机语音识别失败：{str(e)[:80]}"
                        if text:
                            with ctx.services.db() as session:
                                session.merge(WechatVoiceTranscript(
                                    server_id=message.server_id,
                                    transcript=text,
                                    engine=ctx.services.stt.name,
                                ))
                                session.commit()
                    is_self = (message.sender == "我") or (
                        self_wxid and message.sender_username == self_wxid
                    )
                    output.append({
                        "server_id": message.server_id,
                        "time": datetime.fromtimestamp(message.timestamp).strftime("%Y-%m-%d %H:%M"),
                        "sender": "我" if is_self else (message.sender or "对方"),
                        "transcript": text,
                        "error": error,
                    })
                    if index % 5 == 0:
                        # 线程中不能直接 await；进度由外层按结果数量补充。
                        logger.info("微信语音转写进度 %d/%d", index, len(voices))
                return output, len(voices)
            finally:
                db.close()

        try:
            rows, total = await asyncio.to_thread(_do)
        except Exception as e:
            return ToolResult.failure(f"微信语音转写失败: {e}")
        ok = sum(1 for row in rows if row["transcript"])
        await _step(ctx, "voice", f"已完成 {ok}/{total} 条语音转写", "失败项已保留原因")
        return ToolResult.success(
            {"contact": contact, "days": days, "voice_total": total, "transcribed": ok, "items": rows},
            summary=f"已转写 {ok}/{total} 条微信语音（本机处理）",
        )


class WechatImageAnalysisTool(Tool):
    """本地解密微信图片，并在用户明确要求时交给 DeepSeek Vision。"""

    name = "wechat_image_analysis"
    timeout_s = 300.0
    max_result_chars = 30000
    description = (
        "【图片请求必须使用】查看微信聊天中的照片具体内容。用户提到‘照片/图片/截图/图里有什么’，"
        "尤其是‘我和哥哥、Krista发的照片’这类一个或多个联系人的请求时，禁止只调用文字聊天工具或根据上下文猜测；"
        "请直接调用本工具（多个联系人用‘、’或逗号分隔）；"
        "先在本机从微信 .dat 文件提取并解密图片，再逐张发送给配置的 DeepSeek 视觉模型分析。"
        "图片原始文件不会回传手机或作为聊天全文，只有视觉描述返回。contact 可为联系人或群名。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "contact": {"type": "string", "description": "联系人或群显示名"},
            "days": {"type": "integer", "description": "最近几天，默认 7，最大 365", "default": 7},
            "limit": {"type": "integer", "description": "最多分析图片数，默认 5，最大 20", "default": 5},
        },
        "required": ["contact"],
    }

    async def run(self, ctx: ToolContext, contact: str, days: int = 7, limit: int = 5) -> ToolResult:
        # 支持“哥哥、Krista”这种自然表达，避免模型必须拆成多轮工具调用。
        contacts = [p.strip() for p in re.split(r"\s*(?:、|,|，|和|及|以及|与)\s*", contact or "") if p.strip()]
        if len(contacts) > 1:
            results = [await self.run(ctx, item, days, limit) for item in contacts]
            merged_items: list[dict] = []
            errors: list[str] = []
            for item, result in zip(contacts, results):
                if result.ok and isinstance(result.data, dict):
                    merged_items.extend(
                        dict(entry, contact=item)
                        for entry in result.data.get("items", [])
                        if isinstance(entry, dict)
                    )
                elif result.error:
                    errors.append(f"{item}：{result.error}")
            return ToolResult.success(
                {"contacts": contacts, "days": days, "items": merged_items,
                 "image_count": len(merged_items), "analyzed": sum(bool(x.get("analyzed")) for x in merged_items),
                 "warnings": errors},
                summary=f"已分析 {len(contacts)} 个联系人共 {sum(bool(x.get('analyzed')) for x in merged_items)} 张图片",
            )
        days = max(1, min(int(days), 365))
        limit = max(1, min(int(limit), 20))
        await _step(ctx, "wechat", "正在提取微信图片", f"{contact}，最近 {days} 天，最多 {limit} 张")

        def _extract() -> tuple[dict, list[Path], list[str]]:
            from miru.chat_analyzer.media.image import ImageExtractor

            db = _db(ctx)
            try:
                info = _resolve_contact(db, contact)
                cutoff = time.time() - days * 86400
                messages = [
                    m for m in _resolve_session_messages(db, info["username"])
                    if m.msg_type == 3 and m.timestamp >= cutoff
                ][-limit:]
                safe_conversation = re.sub(r"[^A-Za-z0-9_.-]", "_", ctx.conversation_id or "conversation")[:80]
                export_dir = Path(ctx.services.config.config_dir).parent / "data" / "wechat_media" / safe_conversation
                extractor = ImageExtractor(db.account_dir)
                used: set[Path] = set()
                rows: list[dict] = []
                paths: list[Path] = []
                warnings: list[str] = []
                self_wxid = _self_wxid(db)
                for message in messages:
                    path, warning = _export_image(extractor, info["username"], message, export_dir, used)
                    sender = "我" if (message.sender == "我" or (self_wxid and message.sender_username == self_wxid)) else (message.sender or "对方")
                    row = {
                        "time": datetime.fromtimestamp(message.timestamp, _WECHAT_TZ).strftime("%Y-%m-%d %H:%M"),
                        "sender": sender,
                        "ok": bool(path),
                    }
                    if path:
                        row["_path"] = path
                        paths.append(path)
                    else:
                        row["error"] = warning or "图片提取失败"
                        warnings.append(f"{row['time']}：{row['error']}")
                    rows.append(row)
                return {"contact": contact, "days": days, "image_count": len(messages), "items": rows}, paths, warnings
            finally:
                db.close()

        try:
            data, paths, warnings = await asyncio.to_thread(_extract)
        except Exception as exc:
            return ToolResult.failure(f"微信图片读取失败：{exc}")
        if not paths:
            return ToolResult.success(
                {**data, "analyzed": 0, "warnings": warnings or ["时间范围内没有可解密的图片"]},
                summary=f"{contact} 最近 {days} 天没有可分析的图片",
            )

        await _step(ctx, "vision", f"正在分析 {len(paths)} 张图片", "图片仅发送给配置的视觉模型")
        for row, path in zip((r for r in data["items"] if r.get("_path")), paths):
            try:
                block = image_content_block(path)
                prompt = (
                    "请用中文客观描述这张微信图片的具体内容。优先说明人物/物体、文字、场景和可确认的细节；"
                    "看不清或无法确认的内容请明确说看不清，不要猜测。控制在 200 字以内。"
                )
                row["description"] = await ctx.services.llm.vision_chat(
                    [{"role": "user", "content": [{"type": "text", "text": prompt}, block]}],
                    model=ctx.services.config.llm.vision_model,
                    max_tokens=500,
                )
                row["analyzed"] = bool(row["description"])
                if not row["description"]:
                    row["error"] = "视觉模型返回空内容"
            except Exception as exc:
                row["error"] = f"视觉模型分析失败：{str(exc)[:160]}"
                row["analyzed"] = False
            finally:
                row.pop("_path", None)
        data["analyzed"] = sum(1 for item in data["items"] if item.get("analyzed"))
        data["warnings"] = warnings
        return ToolResult.success(data, summary=f"已提取并分析 {data['analyzed']}/{len(paths)} 张微信图片")


class WechatRecentContactsTool(Tool):
    name = "wechat_recent_contacts"
    description = (
        "列出本地微信快照中最近可用的联系人和群聊。默认最多返回前 5 个，"
        "用于先确认目标，再调用 wechat_conversation_digest。微信无需保持运行。"
    )
    parameters = {"type": "object", "properties": {
        "limit": {"type": "integer", "default": 5, "description": "最多返回条数，默认 5"},
    }}

    async def run(self, ctx: ToolContext, limit: int = 5) -> ToolResult:
        limit = max(1, min(limit, 100))
        await _step(ctx, "wechat", "正在读取联系人", "来源为本地离线快照")
        def _do():
            db = _db(ctx)
            try:
                contacts = [c for c in db.get_contacts() if not _is_system_contact(c)]
                return contacts[:limit], len(contacts)
            finally:
                db.close()
        try:
            contacts, total = await asyncio.to_thread(_do)
        except Exception as exc:
            return ToolResult.failure(f"微信联系人读取失败: {exc}")
        data = [{"name": c.get("display_name") or c.get("nickname") or c.get("remark") or "", "nickname": c.get("nickname") or "", "remark": c.get("remark") or "", "is_group": bool((c.get("username") or "").endswith("@chatroom"))} for c in contacts]
        return ToolResult.success({"contacts": data, "returned": len(data), "total": total, "limit": limit}, summary=f"已读取 {len(data)}/{total} 个联系人")


class WechatConversationDigestTool(Tool):
    name = "wechat_conversation_digest"
    # include_voice=true may load the local STT model and process hundreds of items.
    timeout_s = 300.0
    max_result_chars = 30000
    description = (
        "读取并分析指定微信联系人或群聊。detail=stats 只返回统计；用户明确要求查看全文、总结对话时，"
        "必须使用 detail=full。include_voice=true 会自动读取并转写语音，微信无需在线。长记录请继续使用 wechat_dataset_page。"
    )
    parameters = {"type": "object", "properties": {
        "contact": {"type": "string", "description": "联系人昵称、备注或群名"},
        "days": {"type": "integer", "default": 7},
        "limit": {"type": "integer", "default": 500, "maximum": 5000},
        "detail": {"type": "string", "enum": ["stats", "full"], "default": "stats"},
        "include_voice": {"type": "boolean", "default": False},
    }, "required": ["contact"]}

    async def run(self, ctx: ToolContext, contact: str, days: int = 7, limit: int = 500, detail: str = "stats", include_voice: bool = False) -> ToolResult:
        days = max(1, min(days, 3650)); limit = max(1, min(limit, 5000))
        await _step(ctx, "wechat", "正在读取聊天记录", f"{contact}，最近 {days} 天")
        def _do():
            db = _db(ctx)
            try:
                info = _resolve_contact(db, contact)
                messages = _resolve_session_messages(db, info["username"])
                cutoff = time.time() - days * 86400
                return [m for m in messages if m.timestamp >= cutoff][-limit:], _self_wxid(db)
            finally:
                db.close()
        try:
            messages, self_wxid = await asyncio.to_thread(_do)
        except Exception as exc:
            return ToolResult.failure(f"微信聊天读取失败: {exc}")
        stats = compute_statistics(_messages_to_records(messages, self_wxid), contact_name=contact)
        data: dict[str, Any] = {"contact": contact, "days": days, "message_count": len(messages), "stats": stats, "source": "snapshot" if data_root_for(ctx.services.config) != (ctx.services.config.tools.wechat.data_root or "") else "database"}
        if detail == "full":
            data["messages"] = _format_messages(messages, self_wxid)
        if include_voice:
            voice_result = await WechatTranscribeVoiceTool().run(ctx, contact, days, min(limit, 500))
            data["voice"] = voice_result.data if voice_result.ok else {"error": voice_result.error}
        return ToolResult.success(data, summary=f"已读取 {len(messages)} 条消息（{detail}）")


class WechatDatasetPageTool(Tool):
    name = "wechat_dataset_page"
    timeout_s = 60.0
    max_result_chars = 12000
    description = "对指定联系人聊天记录分页读取，每页约 6000 字符；用于长聊天的分段分析，dataset_id 由上一页返回。"
    parameters = {"type": "object", "properties": {
        "contact": {"type": "string"}, "days": {"type": "integer", "default": 30},
        "page": {"type": "integer", "default": 1}, "page_size_chars": {"type": "integer", "default": 6000, "maximum": 9000},
    }, "required": ["contact"]}

    async def run(self, ctx: ToolContext, contact: str, days: int = 30, page: int = 1, page_size_chars: int = 6000) -> ToolResult:
        page = max(1, page); page_size_chars = max(1000, min(page_size_chars, 9000))
        def _do():
            db = _db(ctx)
            try:
                info = _resolve_contact(db, contact); msgs = _resolve_session_messages(db, info["username"])
                cutoff = time.time() - max(1, days) * 86400
                return _format_messages([m for m in msgs if m.timestamp >= cutoff], _self_wxid(db))
            finally:
                db.close()
        try:
            lines = await asyncio.to_thread(_do)
        except Exception as exc:
            return ToolResult.failure(f"微信聊天分页读取失败: {exc}")
        pages: list[str] = []; current = ""
        for line in lines:
            if current and len(current) + len(line) + 1 > page_size_chars:
                pages.append(current); current = ""
            current += ("\n" if current else "") + line
        if current or not pages: pages.append(current)
        text = pages[page - 1] if page <= len(pages) else ""
        return ToolResult.success({"dataset_id": f"wechat:{contact}:{days}", "page": page, "total_pages": len(pages), "message_count": len(lines), "content": text, "has_more": page < len(pages)}, summary=f"已读取第 {page}/{len(pages)} 页")


class WechatGroupListTool(Tool):
    name = "wechat_group_list"
    description = (
        "列出本机微信的全部群聊名称（离线读取 contact 库，本地处理）。"
        "用户问'我有哪些群'、或让你查某个群但名字记不全时使用。"
        "拿到准确群名后，配合 wechat_group_digest / wechat_recent_messages 读群消息。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "最多返回群数", "default": 50},
        },
    }

    async def run(self, ctx: ToolContext, limit: int = 50) -> ToolResult:
        def _do():
            db = _db(ctx)
            try:
                groups = [
                    c for c in db.get_contacts()
                    if (c.get("username") or "").endswith("@chatroom")
                ]
                return [
                    {
                        "name": c.get("display_name") or c.get("nickname") or "",
                        "nickname": c.get("nickname") or "",
                        "remark": c.get("remark") or "",
                    }
                    for c in groups[:limit]
                ]
            finally:
                db.close()
        try:
            groups = await asyncio.to_thread(_do)
        except Exception as e:
            return ToolResult.failure(f"群列表读取失败: {e}")
        return ToolResult.success(groups, summary=f"共找到 {len(groups)} 个群")


class WechatGroupDigestTool(Tool):
    name = "wechat_group_digest"
    description = (
        "生成微信群消息摘要。优先读本地已有的导出文件（output/<群名>/chat.txt）；"
        "没有导出文件时**直接读微信数据库**（群名先用 wechat_group_list / wechat_contact_list 确认，"
        "微信在运行中数据才最新——无需任何在线导出）。"
        "用户问'XX群今天/最近聊了什么/有什么值得看的'时使用。"
        "注意：本工具需要具体群名，不能枚举'哪些群活跃'。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "group": {"type": "string", "description": "群名（先用 wechat_group_list 确认准确名称）"},
            "date": {"type": "string", "description": "日期 YYYY-MM-DD，仅对导出文件生效，默认今天"},
            "days": {"type": "integer", "description": "直读数据库时取最近几天，默认 7", "default": 7},
            "output_dir": {"type": "string", "description": "导出目录", "default": "output"},
        },
        "required": ["group"],
    }

    async def run(self, ctx: ToolContext, group: str, date: str = "", days: int = 7, output_dir: str = "output") -> ToolResult:
        # 1) 导出文件优先（历史归档数据）
        def _do_export():
            chat_file = Path(output_dir) / group / "chat.txt"
            if not chat_file.exists():
                return None
            from miru.chat_analyzer.statistics import parse_chat_file
            records = parse_chat_file(chat_file.read_text(encoding="utf-8"))
            day = date or datetime.now().strftime("%Y-%m-%d")
            todays = [r for r in records if r.timestamp.strftime("%Y-%m-%d") == day]
            return todays or records[-200:]

        # 2) 无导出 → 直读微信数据库（群在 contact.db，username 以 @chatroom 结尾）
        def _do_db() -> tuple[list, str]:
            db = _db(ctx)
            try:
                info = _resolve_contact(db, group)
                messages = _resolve_session_messages(db, info["username"])
                cutoff = time.time() - days * 86400
                recent = [m for m in messages if m.timestamp >= cutoff]
                return recent[-200:], _self_wxid(db)
            finally:
                db.close()

        try:
            records = await asyncio.to_thread(_do_export)
        except Exception as e:
            return ToolResult.failure(f"群消息读取失败: {e}")

        if records is None:
            try:
                messages, self_wxid = await asyncio.to_thread(_do_db)
            except Exception as e:
                return ToolResult.failure(
                    f"群'{group}'没有导出文件，数据库直读也失败（{e}）。"
                    "请先用 wechat_group_list 确认准确群名，并保持微信在运行中。"
                )
            stats = compute_statistics(_messages_to_records(messages, self_wxid), contact_name=group)
            data = {"available": True, "source": "db", "days": days,
                    "message_count": len(messages), "stats": stats}
            if _visibility(ctx) != "aggregates":
                data["samples"] = _format_messages(messages[-30:], self_wxid)
            return ToolResult.success(data, summary=f"已直读群'{group}'最近 {days} 天消息 {len(messages)} 条")

        # 导出文件路径：records 已是 ChatMessageRecord（含 is_self 标记）
        stats = compute_statistics(records, contact_name=group)
        data = {"available": True, "source": "export", "message_count": len(records), "stats": stats}
        if _visibility(ctx) != "aggregates":
            data["samples"] = [
                f"[{r.timestamp:%H:%M}] {r.sender}: {r.content[:100]}" for r in records[-30:]
            ]
        return ToolResult.success(data, summary=f"已读群'{group}'导出消息 {len(records)} 条")
