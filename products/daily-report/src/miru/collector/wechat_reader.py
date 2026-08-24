"""
Miru Assistant — 微信数据库消息读取器 (Task 5C)。

基于 Task 5B 输出的已解密临时数据库，读取结构化消息。

不实现:
    - 群过滤 (那是 filter/ 模块的事)
    - DeepSeek 调用
    - Repository 写入
    - 日报生成

核心能力:
    - 读取群/联系人列表 (contact.db)
    - 按群 + 时间范围读取消息 (message_0.db)
    - ZSTD 内容解压
    - 发送者名称解析 (real_sender_id → Name2Id → contact)
    - 输出结构化 WeChatMessage 列表
"""

import hashlib
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger


# ============================================================
# 数据模型
# ============================================================


@dataclass
class WeChatGroup:
    """微信群信息。"""
    username: str = ""              # 微信内部 ID (e.g. "123456789@chatroom")
    nickname: str = ""              # 群显示名称
    remark: str = ""                # 用户备注名
    member_count: int = 0           # 成员数量
    owner_username: str = ""        # 群主 username


@dataclass
class WeChatContact:
    """微信联系人信息。"""
    username: str = ""              # 微信内部 ID
    nickname: str = ""              # 昵称
    remark: str = ""                # 备注名
    alias: str = ""                 # 微信号
    display_name: str = ""          # 最佳显示名 (remark > nickname > alias)


@dataclass
class WeChatMessage:
    """单条微信消息。"""
    local_id: int = 0               # 本地 ID
    server_id: int = 0              # 服务端消息 ID (MsgSvrID — 去重键)
    local_type: int = 1             # 消息类型 (1=文本, 3=图片, ...)
    create_time: int = 0            # 创建时间 (Unix 时间戳)
    sort_seq: int = 0               # 排序序列号

    sender_id: int = 0              # 发送者数字 ID (Name2Id rowid)
    sender_name: str = ""           # 发送者显示名称 (已解析)
    content: str = ""               # 消息文本内容 (已解压)

    group_username: str = ""        # 所属群 username
    group_name: str = ""            # 所属群显示名称

    # 派生字段
    time_str: str = ""              # "HH:MM:SS" 格式化时间
    is_text: bool = True            # 是否为文本消息
    is_system: bool = False         # 是否为系统消息 (local_type=10000)


# ============================================================
# 数据库读取
# ============================================================


class WeChatDBReader:
    """
    微信解密数据库读取器。

    从已解密的临时 SQLite 文件中读取群列表和消息。

    使用方式:
        reader = WeChatDBReader(contact_db_path, message_db_path)
        groups = reader.get_groups()
        messages = reader.get_messages(group_username, start_ts, end_ts)
    """

    # 消息类型常量
    MSG_TYPE_TEXT = 1
    MSG_TYPE_IMAGE = 3
    MSG_TYPE_VOICE = 34
    MSG_TYPE_VIDEO = 43
    MSG_TYPE_EMOJI = 47
    MSG_TYPE_APPMSG = 49      # 分享/链接/文件
    MSG_TYPE_SYSTEM = 10000   # 系统消息

    def __init__(self, contact_db_path: Path | str, message_db_path: Path | str,
                 msg_key: Optional[bytes] = None):
        """
        Args:
            contact_db_path: contact.db 路径 (已解密或加密)。
            message_db_path: message_0.db 路径 (可能加密)。
            msg_key: message_0.db 的 SQLCipher 密钥 (32 bytes)。
                     为 None 则表示 message_0.db 未加密。
        """
        self.contact_db_path = Path(contact_db_path)
        self.message_db_path = Path(message_db_path)
        self._msg_key = msg_key
        self._contact_conn: Optional[sqlite3.Connection] = None
        self._message_conn: Optional[sqlite3.Connection] = None

        # 缓存: username → display_name
        self._name_cache: dict[int, str] = {}

    @property
    def contact_conn(self) -> sqlite3.Connection:
        if self._contact_conn is None:
            try:
                self._contact_conn = sqlite3.connect(str(self.contact_db_path))
                self._contact_conn.row_factory = sqlite3.Row
            except sqlite3.Error:
                self._contact_conn = sqlite3.connect(":memory:")
                self._contact_conn.row_factory = sqlite3.Row
        return self._contact_conn

    @property
    def message_conn(self):
        """返回 message_0.db 连接 (可能是 sqlite3 或 sqlcipher3)。"""
        if self._message_conn is None:
            if self._msg_key:
                from sqlcipher3 import dbapi2 as sc3
                self._message_conn = sc3.connect(str(self.message_db_path))
                self._message_conn.execute(
                    f"PRAGMA key = \"x'{self._msg_key.hex()}'\""
                )
                self._message_conn.execute("PRAGMA cipher_compatibility = 4")
                # sqlcipher3 不支持 sqlite3.Row，保留默认 tuple row factory
            else:
                self._message_conn = sqlite3.connect(str(self.message_db_path))
                self._message_conn.row_factory = sqlite3.Row
        return self._message_conn

    def _fetch_col(self, row, col: str | int):
        """兼容 sqlcipher3 (tuple) 和 sqlite3.Row 的列访问。"""
        if isinstance(row, tuple):
            return row[col] if isinstance(col, int) else row[0]
        return row[col]

    def close(self) -> None:
        if self._contact_conn:
            self._contact_conn.close()
        if self._message_conn:
            self._message_conn.close()

    # ---- 联系人/群列表 ----

    def get_groups(self) -> list[WeChatGroup]:
        """
        读取所有微信群列表。

        WeChat 4.x: contact.db → chat_room 表
        WeChat 3.x: MicroMsg.db → Contact 表 (Type=2)
        """
        groups: list[WeChatGroup] = []
        conn = self.contact_conn

        # 尝试 4.x 的 chat_room 表
        try:
            rows = conn.execute(
                "SELECT chat_room_name, nick_name, remark, ext_buffer, owner "
                "FROM chat_room ORDER BY nick_name"
            ).fetchall()
            if rows:
                return [self._parse_group_row(dict(r)) for r in rows]
        except sqlite3.OperationalError:
            pass

        # Fallback: 3.x 的 Contact 表 (Type=2 也是群聊)
        try:
            rows = conn.execute(
                "SELECT UserName, NickName, Remark FROM Contact WHERE Type = 2"
            ).fetchall()
            if rows:
                return [
                    WeChatGroup(
                        username=r["UserName"],
                        nickname=r.get("NickName", ""),
                        remark=r.get("Remark", ""),
                    )
                    for r in rows
                ]
        except sqlite3.OperationalError:
            pass

        # 最后尝试: 通过 SessionTable 找群聊
        try:
            rows = conn.execute(
                "SELECT username, last_sender_display_name, summary "
                "FROM SessionTable WHERE username LIKE '%@chatroom%'"
            ).fetchall()
            return [
                WeChatGroup(username=r["username"], nickname="群聊_"+r["username"][:12])
                for r in rows
            ]
        except sqlite3.OperationalError:
            pass

        return groups

    def get_groups_from_msg_db(self) -> list[WeChatGroup]:
        """
        从 message_0.db 的 Name2Id 表读取群列表。
        当 contact.db 不可用时回退使用。
        """
        groups: list[WeChatGroup] = []
        conn = self.message_conn

        # 从 Name2Id 查找 @chatroom 条目
        try:
            rows = conn.execute(
                "SELECT user_name FROM Name2Id "
                "WHERE user_name LIKE '%@chatroom%' AND is_session = 1"
            ).fetchall()
            if rows:
                for r in rows:
                    # 兼容 sqlcipher3 (tuple) 和 sqlite3.Row
                    name = r[0] if isinstance(r, tuple) else r["user_name"]
                    groups.append(WeChatGroup(
                        username=name,
                        nickname=name.split("@")[0] if "@" in name else name,
                        remark="",
                    ))
                logger.info(f"  从 Name2Id 表找到 {len(groups)} 个群 (message_0.db)")
                return groups
        except Exception:
            pass

        return groups

    def _parse_group_row(self, row: dict) -> WeChatGroup:
        """解析 chat_room 行。"""
        g = WeChatGroup(
            username=row.get("chat_room_name", ""),
            nickname=row.get("nick_name", ""),
            remark=row.get("remark", ""),
            owner_username=row.get("owner", ""),
        )
        # 从 ext_buffer (protobuf) 中提取成员数量 (简化: 无法解析时置0)
        return g

    def get_contacts(self) -> list[WeChatContact]:
        """读取所有联系人列表 (用于 sender 名称解析)。"""
        contacts: list[WeChatContact] = []
        conn = self.contact_conn

        # 4.x: contact 表
        try:
            rows = conn.execute(
                "SELECT username, nick_name, remark, alias FROM contact"
            ).fetchall()
            if rows:
                for r in rows:
                    contacts.append(_parse_contact_row(dict(r)))
                return contacts
        except sqlite3.OperationalError:
            pass

        # 3.x: Contact 表
        try:
            rows = conn.execute(
                "SELECT UserName, NickName, Remark, Alias FROM Contact"
            ).fetchall()
            return [_parse_contact_row_legacy(dict(r)) for r in rows]
        except sqlite3.OperationalError:
            pass

        return contacts

    def _build_name_cache(self) -> None:
        """构建 sender_id → display_name 缓存 (使用 message_0.db 的 Name2Id)。"""
        if self._name_cache:
            return

        # Name2Id 在 message_0.db 中，不在 contact.db 中
        try:
            rows = self.message_conn.execute(
                "SELECT rowid, user_name FROM Name2Id"
            ).fetchall()
            # 兼容 sc3 (tuple) 和 sqlite3.Row
            if rows and isinstance(rows[0], tuple):
                id_to_username = {r[0]: r[1] for r in rows}
            else:
                id_to_username = {r["rowid"]: r["user_name"] for r in rows}
        except Exception:
            id_to_username = {}

        # 尝试从 contact.db 获取显示名（可能不可用，用 username 代替）
        username_to_name: dict[str, str] = {}
        try:
            rows = self.contact_conn.execute(
                "SELECT username, nick_name, remark, alias FROM contact"
            ).fetchall()
            for r in rows:
                if isinstance(r, tuple):
                    uname = r[0]
                    best = r[2] or r[1] or r[3] or uname  # remark > nick_name > alias
                else:
                    d = dict(r)
                    uname = d.get("username", "")
                    best = d.get("remark") or d.get("nick_name") or d.get("alias") or uname
                if uname:
                    username_to_name[uname] = best
        except Exception:
            pass  # contact.db 不可用，name_cache 使用原始 username

        # 组合: sender_id → display_name
        for sid, uname in id_to_username.items():
            self._name_cache[sid] = username_to_name.get(uname, uname)

        logger.debug(f"名称缓存已构建: {len(self._name_cache)} 条映射")

    def resolve_sender_name(self, sender_id: int) -> str:
        """将 sender_id 解析为显示名称。"""
        if not self._name_cache:
            self._build_name_cache()
        return self._name_cache.get(sender_id, f"用户_{sender_id}")

    # ---- 消息读取 ----

    def get_messages(
        self,
        group_username: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 1000,
    ) -> list[WeChatMessage]:
        """
        读取指定群的消息。

        Args:
            group_username: 群微信 ID (e.g. "123456789@chatroom")。
            start_time: 起始时间戳 (包含)。
            end_time: 结束时间戳 (包含)。
            limit: 最大消息数。

        Returns:
            WeChatMessage 列表，按 create_time ASC 排序。
        """
        # 找到消息表
        table_name = self._resolve_message_table(group_username)
        if table_name is None:
            logger.warning(f"未找到群 {group_username} 的消息表")
            return []

        conn = self.message_conn
        messages: list[WeChatMessage] = []

        # 构建查询
        query = f"SELECT * FROM [{table_name}] WHERE 1=1"
        params: list = []

        if start_time is not None:
            query += " AND create_time >= ?"
            params.append(start_time)
        if end_time is not None:
            query += " AND create_time <= ?"
            params.append(end_time)

        query += " ORDER BY create_time ASC, sort_seq ASC LIMIT ?"
        params.append(limit)

        try:
            rows = conn.execute(query, params).fetchall()
        except sqlite3.OperationalError as e:
            logger.error(f"查询消息表 {table_name} 失败: {e}")
            return []

        # 确保名称缓存就绪
        if not self._name_cache:
            self._build_name_cache()

        for row in rows:
            if isinstance(row, tuple):
                # sc3 返回 tuple，转为 dict
                row = self._tuple_to_row(row)
            else:
                row = dict(row)
            msg = self._parse_message_row(row, group_username)
            if msg is not None:
                messages.append(msg)

        logger.info(
            f"从 {group_username} 读取 {len(messages)} 条消息 "
            f"(表={table_name}, 时间={start_time or '*'}~{end_time or '*'})"
        )
        return messages

    def _resolve_message_table(self, group_username: str) -> Optional[str]:
        """
        解析群对应的消息表名。

        WeChat 4.x: Msg_{MD5(group_username)}
        WeChat 3.x: 通过 Name2Id 表 + MSG 表
        """
        conn = self.message_conn

        # 4.x: 通过 MD5 hash
        md5 = hashlib.md5(group_username.encode()).hexdigest()
        table_name = f"Msg_{md5}"
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE name = ?", (table_name,)
            )
            if cursor.fetchone():
                return table_name
        except sqlite3.OperationalError:
            pass

        # 备用搜索: 搜索所有 Msg_ 表
        try:
            all_tables = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name LIKE 'Msg_%'"
            ).fetchall()
            for t in all_tables:
                t_name = t[0] if isinstance(t, tuple) else t["name"]
                try:
                    cnt = conn.execute(
                        f"SELECT COUNT(*) FROM [{t_name}] LIMIT 1"
                    ).fetchone()
                    if cnt and cnt[0] > 0:
                        logger.debug(f"找到消息表: {t_name}")
                except Exception:
                    continue
        except Exception:
            pass

        return table_name  # 返回 MD5 表名，即使不存在

    # WeChat 4.x Msg_* 表真实列顺序 (从 PRAGMA table_info 获取)
    _MSG_COLUMNS = [
        "local_id",           # 0  INTEGER pk
        "server_id",          # 1  INTEGER
        "local_type",         # 2  INTEGER
        "sort_seq",           # 3  INTEGER
        "real_sender_id",     # 4  INTEGER
        "create_time",        # 5  INTEGER
        "status",             # 6  INTEGER
        "upload_status",      # 7  INTEGER
        "download_status",    # 8  INTEGER
        "server_seq",         # 9  INTEGER
        "origin_source",      # 10 INTEGER
        "source",             # 11 TEXT (ZSTD compressed XML metadata)
        "message_content",    # 12 TEXT (实际消息文本: "sender_id\\ncontent")
        "compress_content",   # 13 TEXT (ZSTD 压缩消息)
        "packed_info_data",   # 14 BLOB (protobuf)
        "wcdb_ct_msg",        # 15 INTEGER
        "wcdb_ct_source",     # 16 INTEGER
    ]

    def _tuple_to_row(self, row: tuple) -> dict:
        """将 sqlcipher3 返回的 tuple 转为 dict (使用真实列名映射)。"""
        cols = self._MSG_COLUMNS
        result = {}
        for i, val in enumerate(row):
            if i < len(cols):
                result[cols[i]] = val
        return result

    def _parse_message_row(
        self, row: dict, group_username: str
    ) -> Optional[WeChatMessage]:
        """
        解析消息行 → WeChatMessage。

        微信 4.x 消息表字段:
            local_id, server_id, local_type, real_sender_id,
            create_time, sort_seq, message_content, packed_info_data, status
        """
        local_type = row.get("local_type", 1)

        # 按过滤规则排除不需要的消息类型（但 Task 5C 不做过滤，只标记）
        is_text = local_type == self.MSG_TYPE_TEXT
        is_system = local_type == self.MSG_TYPE_SYSTEM

        # 解压并解析消息内容
        raw_content = row.get("message_content", "")
        if raw_content is None:
            raw_content = ""
        if isinstance(raw_content, bytes):
            # ZSTD 压缩或二进制格式
            sender_id, content = self._parse_content_bytes(raw_content, row)
        elif isinstance(raw_content, str) and raw_content.strip():
            # 字符串格式: "sender_id\ncontent" 或纯文本
            sender_id, content = self._parse_content_str(raw_content, row)
        else:
            # message_content 为空，尝试 compress_content 列
            raw_compress = row.get("compress_content", "")
            if isinstance(raw_compress, bytes) and raw_compress[:4] == b"\x28\xb5\x2f\xfd":
                try:
                    import zstandard as zstd
                    dctx = zstandard.ZstdDecompressor()
                    raw_compress = dctx.decompress(raw_compress)
                except Exception:
                    pass
            if isinstance(raw_compress, bytes):
                try:
                    raw_compress = raw_compress.decode("utf-8", errors="replace")
                except Exception:
                    raw_compress = ""
            if isinstance(raw_compress, str) and raw_compress.strip():
                sender_id, content = self._parse_content_str(raw_compress, row)
            else:
                sender_id = row.get("real_sender_id", 0)
                content = ""

        # 发送者解析
        sender_name = self.resolve_sender_name(sender_id) if sender_id else ""

        # 时间格式化
        create_time = row.get("create_time", 0)
        time_str = _format_timestamp(create_time)

        return WeChatMessage(
            local_id=row.get("local_id", 0),
            server_id=row.get("server_id", 0),
            local_type=local_type,
            create_time=create_time,
            sort_seq=row.get("sort_seq", 0),
            sender_id=sender_id,
            sender_name=sender_name,
            content=content,
            group_username=group_username,
            group_name="",
            time_str=time_str,
            is_text=is_text,
            is_system=is_system,
        )

    def _parse_content_str(
        self, text: str, row: dict
    ) -> tuple[int, str]:
        """
        解析字符串格式的消息内容。

        群消息格式: "sender_id\\nactual_content"
        """
        if "\n" in text:
            parts = text.split("\n", 1)
            try:
                sender_id = int(parts[0])
                return (sender_id, parts[1])
            except (ValueError, IndexError):
                pass
        return (row.get("real_sender_id", 0), text)

    def _parse_content_bytes(
        self, raw: bytes, row: dict
    ) -> tuple[int, str]:
        """
        解析二进制消息内容。

        Format:
            文本/未压缩: sender_id + "\n" + actual_content
            ZSTD 压缩: 魔数 0x28 0xB5 0x2F 0xFD 开头

        Returns:
            (sender_id, content_text)
        """
        # ZSTD 解压
        if raw[:4] == b"\x28\xB5\x2F\xFD":
            try:
                import zstandard as zstd
                dctx = zstd.ZstdDecompressor()
                raw = dctx.decompress(raw)
            except Exception as e:
                logger.debug(f"ZSTD 解压失败: {e}")
                return (0, "[解压失败]")

        # 解析 sender_id\ncontent 格式
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            return (row.get("real_sender_id", 0), "[解码失败]")

        # 群消息格式: "sender_id\ncontent"
        if "\n" in text:
            parts = text.split("\n", 1)
            try:
                sender_id = int(parts[0])
                content = parts[1]
                return (sender_id, content)
            except (ValueError, IndexError):
                pass

        # 直接消息 (非群聊或格式不同)
        return (row.get("real_sender_id", 0), text)

    def get_all_messages_today(
        self, group_username: str
    ) -> list[WeChatMessage]:
        """便捷方法: 读取指定群今天的所有消息。"""
        today_start = int(time.time()) // 86400 * 86400
        today_start -= 8 * 3600  # UTC+8 adjustment — use local midnight
        # Actually, let's use the correct local midnight
        import datetime
        now = datetime.datetime.now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ts = int(midnight.timestamp())
        end_ts = int(time.time())
        return self.get_messages(group_username, start_ts, end_ts)


# ============================================================
# 工具函数
# ============================================================


def _parse_contact_row(row: dict) -> WeChatContact:
    """解析微信 4.x contact 行。"""
    c = WeChatContact(
        username=row.get("username", ""),
        nickname=row.get("nick_name", ""),
        remark=row.get("remark", ""),
        alias=row.get("alias", ""),
    )
    c.display_name = c.remark or c.nickname or c.alias or c.username
    return c


def _parse_contact_row_legacy(row: dict) -> WeChatContact:
    """解析微信 3.x Contact 行。"""
    c = WeChatContact(
        username=row.get("UserName", ""),
        nickname=row.get("NickName", ""),
        remark=row.get("Remark", ""),
        alias=row.get("Alias", ""),
    )
    c.display_name = c.remark or c.nickname or c.alias or c.username
    return c


def _format_timestamp(ts: int) -> str:
    """Unix 时间戳 → "HH:MM:SS"。"""
    import datetime
    if ts == 0:
        return "00:00:00"
    try:
        dt = datetime.datetime.fromtimestamp(ts)
        return dt.strftime("%H:%M:%S")
    except (OSError, ValueError):
        return str(ts)


# ============================================================
# 顶层便捷 API
# ============================================================


def read_recent_messages(
    contact_db_path: Path,
    message_db_path: Path,
    group_username: str,
    count: int = 20,
) -> list[WeChatMessage]:
    """
    快速读取指定群的最近 N 条消息。

    这是 Task 5C 的主要入口。

    Args:
        contact_db_path: 已解密的 contact.db 路径。
        message_db_path: 已解密的 message_0.db 路径。
        group_username: 群微信 ID。
        count: 消息数量。

    Returns:
        最近 N 条消息（时间倒序 → 调用方反转后可得到时间正序）。
    """
    reader = WeChatDBReader(contact_db_path, message_db_path)
    try:
        # 读取全部消息然后取最后 N 条
        all_msgs = reader.get_messages(group_username, limit=5000)
        return all_msgs[-count:] if len(all_msgs) > count else all_msgs
    finally:
        reader.close()


def list_groups(
    contact_db_path: Path,
) -> list[WeChatGroup]:
    """
    读取所有群列表。

    Args:
        contact_db_path: 已解密的 contact.db 路径。

    Returns:
        微信群列表。
    """
    reader = WeChatDBReader(contact_db_path, Path(contact_db_path))
    try:
        return reader.get_groups()
    finally:
        reader.close()
