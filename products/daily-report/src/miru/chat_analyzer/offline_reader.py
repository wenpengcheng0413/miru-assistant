"""
Miru Assistant — Chat Analyzer 离线数据库读取器。

从微信 4.x 加密分片数据库中直接读取消息（离线模式）。

与 collector/wechat_reader.py（在线模式）的区别:
    - 在线模式: 依赖微信进程运行 + 管理员权限 + 内存扫描密钥
    - 离线模式: 直接读取密钥文件 (all_keys.json / database_keys.yaml)，
      无需微信运行，按 wxid 定位会话表

会话表定位策略（已验证）:
    微信 4.x 每个会话是一张 Msg_{MD5(wxid)} 表，跨分片存储
    (message_0.db ~ message_5.db 可能都有同名表)。
    每个分片有自己的 Name2Id 表 (rowid → wxid)，
    real_sender_id 指向分片自己的 Name2Id rowid，
    是定位会话表的唯一可靠关联（local_id 每表独立，不能跨表反查）。

用法:
    db = OfflineWeChatDB()
    contact = db.resolve_contact("Krista")
    tables = db.find_session_tables(contact["wxid"])
    messages = db.read_all_messages(table_name, "message/message_0.db")
"""

import hashlib
import html
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from loguru import logger

from miru.chat_analyzer.models import ChatMessage

# ============================================================
# 常量
# ============================================================

# 消息分片文件（离线读取时全部尝试）
MESSAGE_SHARDS = [f"message/message_{i}.db" for i in range(6)]

# 微信消息类型（与 collector.wechat_reader 保持一致）
MSG_TYPE_TEXT = 1
MSG_TYPE_IMAGE = 3
MSG_TYPE_VOICE = 34
MSG_TYPE_VIDEO = 43
MSG_TYPE_EMOJI = 47
MSG_TYPE_APP = 49
MSG_TYPE_SYSTEM = 10000

# ZSTD 魔数
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


# ============================================================
# 纯函数
# ============================================================


def session_table_md5(wxid: str) -> str:
    """计算会话表名: Msg_{MD5(wxid)}。"""
    return hashlib.md5(wxid.encode()).hexdigest()


def decompress_zstd(data: bytes) -> bytes:
    """ZSTD 解压（非 ZSTD 数据原样返回）。"""
    if data[:4] == _ZSTD_MAGIC:
        import zstandard as zstd

        return zstd.ZstdDecompressor().decompress(data)
    return data


# 无可见文本的 XML 消息 → 友好类型占位（避免 "[非文本消息 类型47]" 进入词频）
_FALLBACK_LABELS = {
    3: "[图片]",
    34: "[语音]",
    43: "[视频]",
    47: "[表情]",
    49: "[链接/文件]",
    10000: "[系统消息]",
}


# 去标签用"合法标签"正则（标签名须字母开头），避免用户文本中的
# 裸尖括号（如 "1 < 2"）与远处 > 错误配对。
_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9_]*[^>]*>")


def _extract_xml_text(content: str) -> str:
    """从 XML 文本提取可见内容。

    - XML 声明（<?xml ...?>）与 CDATA 内容一并处理
    - CDATA 内容: 先反转义（&lt;tag&gt; 变 <tag>）再去标签（删净）
    - 外层结构:   先去标签（真实标签）再反转义（文本实体的 < > 不会被误删）
    """
    def _clean_cdata(m: re.Match[str]) -> str:
        seg = html.unescape(m.group(1))
        return _TAG_RE.sub("", seg)

    plain = re.sub(r"<\?xml[^>]*\?>", "", content, flags=re.I)
    plain = re.sub(r"<!\[CDATA\[(.*?)\]\]>", _clean_cdata, plain, flags=re.S)
    plain = _TAG_RE.sub("", plain)
    return html.unescape(plain).strip()


def summarize_content(content: str, local_type: int) -> str:
    """
    将原始消息内容转为可读摘要。

    文本原样；XML 提取关键信息；空内容返回空串（由调用方填充类型占位）。
    文本中若含 XML 标记（如 "wxid_xxx\\n<msg>..." 前缀 + 多行 XML），
    也会提取可见文本，避免整段 XML 原样进入导出与词频。
    """
    if not content:
        return ""
    stripped = content.strip()
    if not stripped:
        return ""

    # 不以 < 开头 → 纯文本（可能含转义实体 / 前缀 + XML 标记）
    if not stripped.startswith("<"):
        unescaped = html.unescape(stripped)
        if unescaped.startswith("<"):
            return summarize_content(unescaped, local_type)
        # 文本内含 XML 标记（如 "某前缀\n<msg>..."）→ 提取可见文本
        if _TAG_RE.search(unescaped):
            plain = _extract_xml_text(unescaped)
            if plain:
                return plain[:200]
            return _FALLBACK_LABELS.get(local_type, f"[非文本消息 类型{local_type}]")
        return unescaped

    # 图片
    if "<img" in content:
        m = re.search(r'md5="([0-9a-f]{32})"', content)
        md5 = m.group(1)[:8] if m else ""
        return f"[图片] (md5={md5})" if md5 else "[图片]"
    # 语音
    if "<voicemsg" in content:
        m = re.search(r'voicelength = "(\d+)"', content)
        if m:
            return f"[语音] (时长 {int(m.group(1)) // 1000}s)"
        return "[语音]"
    # 视频
    if "<videomsg" in content:
        return "[视频]"
    # 链接/文件/小程序 (appmsg)
    if "<appmsg" in content:
        parts: list[str] = []
        tm = re.search(r"<title>([^<]*)</title>", content)
        if tm and tm.group(1).strip():
            parts.append(f"标题: {html.unescape(tm.group(1).strip())}")
        # 引用消息: refermsg 里的 displayname + content
        rm = re.search(
            r"<refermsg>.*?<displayname>([^<]*)</displayname>.*?<content>([^<]*)</content>",
            content,
            re.S,
        )
        if rm and (rm.group(1).strip() or rm.group(2).strip()):
            parts.append(
                f"引用 {html.unescape(rm.group(1).strip())}: "
                f"{html.unescape(rm.group(2).strip())}"
            )
        label = "文件" if "<fileext" in content or "<filename" in content else "链接"
        if parts:
            return f"[{label}] " + " | ".join(parts)
        return f"[{label}]"

    # 其他 XML: 提取可见文本
    plain = _extract_xml_text(stripped)
    if plain:
        return plain[:200]
    return _FALLBACK_LABELS.get(local_type, f"[非文本消息 类型{local_type}]")


# ============================================================
# 离线读取器
# ============================================================


class OfflineWeChatDB:
    """
    离线微信数据库读取器（解密 + 定位 + 读取）。

    密钥来源优先级:
        1. 账号目录下 all_keys.json（微信完整密钥清单）
        2. config/database_keys.yaml（Miru 提取的分片密钥）

    数据库为明文时（微信 3.x 或测试模拟库）自动回退标准 sqlite3。
    """

    def __init__(self, data_root: str | Path = ""):
        """
        Args:
            data_root: 微信数据目录。
                为空时自动检测（find_wechat_data_dir）；
                也可直接传入账号目录（含 db_storage/message）。
        """
        self.account_dir = self._locate_account_dir(data_root)
        self.storage = self.account_dir / "db_storage" if self.account_dir else None
        self._keys: dict[str, str] = {}
        self._conns: dict[str, Any] = {}

    # ---- 目录与密钥 ----

    @staticmethod
    def _locate_account_dir(data_root: str | Path) -> Path:
        """定位含 db_storage/message 的微信账号目录。"""
        root = Path(data_root) if data_root else None
        if root is None:
            from miru.collector.diagnostics import find_wechat_data_dir

            info = find_wechat_data_dir()
            if info.found:
                candidate = Path(info.path)
                # find_wechat_data_dir 返回的可能是账号目录或根目录
                if (candidate / "db_storage" / "message").exists():
                    return candidate
                root = candidate
            else:
                raise FileNotFoundError(info.error or "未找到微信数据目录")
        else:
            root = root if root.is_dir() else root.parent

        # 扫描根下的 wxid_* 账号目录
        if root and (root / "db_storage" / "message").exists():
            return root
        if root:
            candidates: list[tuple[Path, bool]] = []
            for entry in sorted(root.iterdir()):
                if not entry.is_dir() or not entry.name.startswith("wxid_"):
                    continue
                if (entry / "db_storage" / "message").exists():
                    candidates.append((entry, (entry / "all_keys.json").exists()))
            if candidates:
                # 有 all_keys.json 的优先；否则取字典序最大的
                candidates.sort(key=lambda t: (t[1], t[0].name), reverse=True)
                return candidates[0][0]
        raise FileNotFoundError(
            f"未找到微信账号目录（含 db_storage/message）: {root or '(自动检测)'}\n"
            "请在 settings.yaml 中设置 wechat.data_dir"
        )

    def load_keys(self) -> dict[str, str]:
        """加载数据库密钥 {相对路径: enc_key}。"""
        if self._keys:
            return self._keys

        # 1. 账号目录 all_keys.json（微信完整清单）
        ak_file = self.account_dir / "all_keys.json"
        if ak_file.exists():
            try:
                raw = json.loads(ak_file.read_text(encoding="utf-8"))
                self._keys = {k: v["enc_key"] for k, v in raw.items()}
                logger.info(f"加载密钥: {ak_file.name} ({len(self._keys)} 个数据库)")
                return self._keys
            except Exception as e:
                logger.warning(f"all_keys.json 解析失败: {e}")

        # 2. config/database_keys.yaml（Miru 提取的分片密钥）
        import yaml

        cfg_path = Path(__file__).resolve().parent.parent.parent.parent / "config" / "database_keys.yaml"
        if cfg_path.exists():
            try:
                y = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
                self._keys = {f"message/{k}": v for k, v in y.get("keys", {}).items()}
                logger.info(f"加载密钥: database_keys.yaml ({len(self._keys)} 个数据库)")
                return self._keys
            except Exception as e:
                logger.warning(f"database_keys.yaml 解析失败: {e}")

        logger.warning("未找到任何密钥文件（数据库须为明文，如微信 3.x）")
        return self._keys

    # ---- 连接 ----

    def open(self, rel: str) -> sqlite3.Connection:
        """
        打开加密/明文数据库连接（结果缓存）。

        Args:
            rel: 相对 db_storage 的路径，如 "message/message_0.db"。

        Raises:
            FileNotFoundError: 数据库文件不存在。
        """
        if rel in self._conns:
            return self._conns[rel]

        if self.storage is None:
            raise FileNotFoundError("未定位到微信数据目录")

        db_path = self.storage / rel
        if not db_path.exists():
            raise FileNotFoundError(f"数据库不存在: {db_path}")

        key = self.load_keys().get(rel, "")
        if key:
            from sqlcipher3 import dbapi2 as sc3

            try:
                conn = sc3.connect(str(db_path))
                conn.execute(f'PRAGMA key = "x\'{key}\'"')
                conn.execute("PRAGMA cipher_memory_security = OFF")
                # 触发一次读以验证密钥（HMAC 失败会在此抛出）
                conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
            except Exception as e:
                logger.debug(f"{rel} 密钥打开失败（尝试明文）: {e}")
                try:
                    conn.close()
                except Exception:
                    pass
                conn = sqlite3.connect(str(db_path))
        else:
            conn = sqlite3.connect(str(db_path))

        self._conns[rel] = conn
        return conn

    def close(self) -> None:
        """关闭全部连接。"""
        for conn in self._conns.values():
            try:
                conn.close()
            except Exception:
                pass
        self._conns.clear()

    # ---- 联系人 ----

    def get_contacts(self) -> list[dict[str, str]]:
        """contact.db 全部联系人（含显示名解析）。"""
        try:
            conn = self.open("contact/contact.db")
            rows = conn.execute(
                "SELECT username, alias, remark, nick_name FROM contact"
            ).fetchall()
        except (FileNotFoundError, sqlite3.OperationalError) as e:
            logger.warning(f"contact.db 不可用: {e}")
            return []

        contacts: list[dict[str, str]] = []
        for r in rows:
            username, alias, remark, nick = (r[0], r[1], r[2], r[3])
            contacts.append(
                {
                    "username": username or "",
                    "alias": alias or "",
                    "remark": remark or "",
                    "nickname": nick or "",
                    "display_name": remark or nick or alias or username or "",
                }
            )
        return contacts

    def resolve_contact(self, name: str) -> dict[str, str]:
        """按名称/微信号/备注/昵称解析联系人（模糊匹配，大小写不敏感）。"""
        contacts = self.get_contacts()
        q = name.lower()
        fields = ("display_name", "alias", "remark", "nickname", "username")

        exact = [c for c in contacts if q in {(c[f] or "").lower() for f in fields}]
        if len(exact) == 1:
            return exact[0]
        # 模糊匹配: 任一字段包含查询词
        fuzzy = [
            c for c in contacts
            if any(q in (c[f] or "").lower() for f in fields)
        ]
        if fuzzy:
            fuzzy.sort(key=lambda c: len(c["display_name"]))
            return fuzzy[0]
        if exact:
            return exact[0]
        raise LookupError(f"未找到联系人 '{name}'（数据库共 {len(contacts)} 个联系人）")

    # ---- 会话表定位 ----

    def find_session_tables(self, wxid: str) -> list[tuple[str, str, int]]:
        """
        在 6 个分片中定位与该 wxid 相关的全部会话表。

        策略（每个分片独立）:
            1. 分片 Name2Id: wxid → rowid
            2. 每张 Msg_* 表: real_sender_id = rowid 的行数 > 0 → 会话表

        Returns:
            [(table_name, shard_rel, sender_hit_count), ...]。
        """
        found: list[tuple[str, str, int]] = []
        for rel in MESSAGE_SHARDS:
            try:
                conn = self.open(rel)
            except (FileNotFoundError, sqlite3.OperationalError) as e:
                logger.debug(f"分片 {rel} 打开失败: {e}")
                continue
            try:
                row = conn.execute(
                    "SELECT rowid FROM Name2Id WHERE user_name = ?", (wxid,)
                ).fetchone()
            except sqlite3.OperationalError:
                continue
            if not row:
                continue
            sender_id = row[0]
            try:
                tables = [
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
                    ).fetchall()
                ]
            except sqlite3.OperationalError:
                continue
            for t in tables:
                try:
                    n = conn.execute(
                        f"SELECT COUNT(*) FROM [{t}] WHERE real_sender_id = ?", (sender_id,)
                    ).fetchone()[0]
                    if n > 0:
                        found.append((t, rel, n))
                except sqlite3.OperationalError:
                    continue
        return found

    def find_direct_session_tables(self, wxid: str) -> list[tuple[str, str, int]]:
        """定位一对一私聊会话在所有消息分片中的表。

        直接会话表名是 ``Msg_{MD5(wxid)}``。不能复用
        :meth:`find_session_tables`：后者按 ``real_sender_id`` 反查时，也会
        命中联系人在共同群聊里的发言，适合"查找出现过该联系人"，却不适合
        导出两人私聊记录。

        返回格式与 ``find_session_tables`` 保持一致；第三项为表中消息总数，
        仅供日志与诊断使用。
        """
        table_name = f"Msg_{session_table_md5(wxid)}"
        found: list[tuple[str, str, int]] = []
        for rel in MESSAGE_SHARDS:
            try:
                conn = self.open(rel)
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,),
                ).fetchone()
                if not exists:
                    continue
                count = conn.execute(
                    f'SELECT COUNT(*) FROM "{table_name}"'
                ).fetchone()[0]
                found.append((table_name, rel, int(count)))
            except (FileNotFoundError, sqlite3.OperationalError) as e:
                logger.debug(f"分片 {rel} 打开或查询失败: {e}")
        return found

    # ---- 消息读取 ----

    def list_message_tables(self, shard_rel: str) -> set[str]:
        """返回消息分片中的会话表名，不读取历史消息内容。"""
        try:
            conn = self.open(shard_rel)
            rows = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name LIKE 'Msg_%'"
            ).fetchall()
            return {str(row[0]) for row in rows if row and row[0]}
        except (FileNotFoundError, sqlite3.Error) as exc:
            logger.debug("消息分片 %s 的会话表不可读: %s", shard_rel, exc)
            return set()

    def read_all_messages(self, table: str, shard_rel: str) -> list[ChatMessage]:
        """
        读取会话表的全部消息（时间升序），sender 名称按分片解析。

        Args:
            table: Msg_* 表名。
            shard_rel: 分片相对路径（如 "message/message_1.db"）。

        Returns:
            ChatMessage 列表（按 create_time ASC, sort_seq ASC 排序）。
        """
        return self._read_messages_query(table, shard_rel)

    def read_messages_since(
        self,
        table: str,
        shard_rel: str,
        since: int,
        until: int | None = None,
    ) -> list[ChatMessage]:
        """只读取时间窗口内的消息，避免为近期统计加载整张会话表。"""
        return self._read_messages_query(table, shard_rel, since=since, until=until)

    def _read_messages_query(
        self,
        table: str,
        shard_rel: str,
        since: int | None = None,
        until: int | None = None,
    ) -> list[ChatMessage]:
        conn = self.open(shard_rel)

        # 分片 Name2Id: rowid → username
        id_to_username: dict[int, str] = {}
        try:
            for rid, uname in conn.execute("SELECT rowid, user_name FROM Name2Id").fetchall():
                id_to_username[rid] = uname or ""
        except sqlite3.OperationalError:
            pass
        # username → 显示名 (contact.db)
        username_to_name = {c["username"]: c["display_name"] for c in self.get_contacts()}

        cols_row = conn.execute(f"PRAGMA table_info([{table}])").fetchall()
        cols = [c[1] for c in cols_row]
        where: list[str] = []
        params: list[int] = []
        if since is not None and "create_time" in cols:
            where.append("create_time >= ?")
            params.append(int(since))
        if until is not None and "create_time" in cols:
            where.append("create_time <= ?")
            params.append(int(until))
        predicate = f" WHERE {' AND '.join(where)}" if where else ""
        order = "create_time ASC, sort_seq ASC" if "sort_seq" in cols else "create_time ASC"
        rows = conn.execute(
            f"SELECT * FROM [{table}]{predicate} ORDER BY {order}", params
        ).fetchall()

        msgs: list[ChatMessage] = []
        for r in rows:
            d = dict(zip(cols, r))
            sender_id, content = self._parse_content(r, cols, d)
            sid = sender_id or d.get("real_sender_id") or 0
            uname = id_to_username.get(sid, "")
            sender_name = username_to_name.get(uname, uname or f"用户_{sid}")
            msgs.append(
                ChatMessage(
                    timestamp=int(d.get("create_time") or 0),
                    sender=sender_name,
                    sender_id=sid,
                    sender_username=uname,
                    content=content,
                    raw_content=str(d.get("message_content") or ""),
                    msg_type=int(d.get("local_type") or 0),
                    server_id=int(d.get("server_id") or 0),
                    conversation=self._conversation_id(table, shard_rel),
                    source=f"{shard_rel}/{table}",
                )
            )
        return msgs

    @staticmethod
    def _conversation_id(table: str, shard_rel: str) -> str:
        """会话标识（表名的 wxid 部分，仅用于区分会话）。"""
        return f"{shard_rel}:{table}"

    @staticmethod
    def _parse_content(
        row: tuple, cols: list[str], d: dict[str, Any]
    ) -> tuple[int, str]:
        """
        解析 message_content / compress_content → (sender_id, content)。

        微信 4.x 内容格式:
            - 文本: "sender_id\\ncontent"（sender_id 为数字）
            - 压缩: ZSTD 魔数 0x28 0xB5 0x2F 0xFD 开头
        """
        candidates: list[Any] = []
        raw = d.get("message_content")
        if isinstance(raw, (bytes, str)) and raw not in (b"", ""):
            candidates.append(raw)
        cc = d.get("compress_content")
        if isinstance(cc, (bytes, str)) and cc not in (b"", ""):
            candidates.append(cc)

        for c in candidates:
            if isinstance(c, bytes):
                try:
                    c = decompress_zstd(c)
                    text = c.decode("utf-8", errors="replace")
                except Exception:
                    continue
            else:
                text = c
            if not text or not text.strip():
                continue
            # "sender_id\ncontent" 格式；微信 4.x 群消息可能是 "wxid_xxx:\ncontent"
            if "\n" in text:
                head, _, rest = text.partition("\n")
                try:
                    return int(head.strip()), rest.strip()
                except ValueError:
                    if re.match(r"^wxid_[A-Za-z0-9]+[:：]?$", head.strip()):
                        return int(d.get("real_sender_id") or 0), rest.strip()
            return int(d.get("real_sender_id") or 0), text.strip()
        return int(d.get("real_sender_id") or 0), ""
