"""
Miru Assistant — 消息读取器单元测试 (Task 5C)。

测试覆盖:
    - WeChatGroup / WeChatMessage 数据模型
    - WeChatDBReader 从模拟数据库读取群列表
    - 消息读取 (含时间过滤)
    - ZSTD 内容解压
    - 发送者名称解析 (Name2Id)
    - read_recent_messages / list_groups 顶层 API
"""

import hashlib
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from miru.collector.wechat_reader import (
    WeChatContact,
    WeChatDBReader,
    WeChatGroup,
    WeChatMessage,
    _format_timestamp,
    _parse_contact_row,
    list_groups,
    read_recent_messages,
)


# ============================================================
# Helpers — 创建模拟的微信数据库结构
# ============================================================


def _make_contact_db(db_path: Path) -> None:
    """创建一个模拟微信 4.x contact.db。"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # chat_room 表
    conn.execute("""
        CREATE TABLE chat_room (
            chat_room_name TEXT,
            nick_name TEXT,
            remark TEXT,
            owner TEXT,
            ext_buffer BLOB
        )
    """)
    conn.execute(
        "INSERT INTO chat_room VALUES (?, ?, ?, ?, ?)",
        ("111@chatroom", "班群", "", "teacher1", b""),
    )
    conn.execute(
        "INSERT INTO chat_room VALUES (?, ?, ?, ?, ?)",
        ("222@chatroom", "AI交流群", "AI", "", b""),
    )
    conn.execute(
        "INSERT INTO chat_room VALUES (?, ?, ?, ?, ?)",
        ("333@chatroom", "课程群", "", "", b""),
    )

    # contact 表 (用于 sender 名称解析)
    conn.execute("""
        CREATE TABLE contact (
            username TEXT,
            nick_name TEXT,
            remark TEXT,
            alias TEXT
        )
    """)
    conn.execute(
        "INSERT INTO contact VALUES (?, ?, ?, ?)",
        ("user_zhang", "张三", "", "zhangsan"),
    )
    conn.execute(
        "INSERT INTO contact VALUES (?, ?, ?, ?)",
        ("user_li", "李四", "助教小李", ""),
    )

    # Name2Id 表
    conn.execute("CREATE TABLE Name2Id (user_name TEXT)")
    conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (1, 'user_zhang')")
    conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (2, 'user_li')")

    conn.commit()
    conn.close()


def _make_message_db(db_path: Path) -> None:
    """创建一个模拟微信 4.x message_0.db。"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # 为群 "111@chatroom" 创建消息表
    md5 = hashlib.md5("111@chatroom".encode()).hexdigest()
    table_name = f"Msg_{md5}"
    conn.execute(f"""
        CREATE TABLE [{table_name}] (
            local_id INTEGER,
            server_id INTEGER,
            local_type INTEGER DEFAULT 1,
            real_sender_id INTEGER DEFAULT 0,
            create_time INTEGER,
            sort_seq INTEGER,
            message_content BLOB,
            packed_info_data BLOB,
            status INTEGER DEFAULT 4
        )
    """)

    # 插入测试消息
    now = int(time.time())
    test_msgs = [
        (1, 10001, 1, 1, now - 3600, 1, "1\n同学们，明天下午的课调到周五", None, 4),
        (2, 10002, 1, 2, now - 3500, 2, "2\n收到，谢谢老师", None, 4),
        (3, 10003, 1, 1, now - 3400, 3, "1\n另外实验报告下周一交", None, 4),
        (4, 10004, 3, 1, now - 1000, 4, None, None, 4),  # 图片消息
        (5, 10005, 10000, 0, now - 500, 5, "某某加入了群聊", None, 4),  # 系统消息
        (6, 10006, 1, 2, now, 6, "2\n好的", None, 4),
    ]

    for msg in test_msgs:
        conn.execute(
            f"INSERT INTO [{table_name}] VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            msg,
        )

    conn.commit()
    conn.close()


# ============================================================
# Test: Data Models
# ============================================================


class TestDataModels:
    """测试数据模型。"""

    def test_wechat_group_defaults(self):
        g = WeChatGroup()
        assert g.username == ""
        assert g.nickname == ""

    def test_wechat_message_defaults(self):
        m = WeChatMessage()
        assert m.is_text is True
        assert m.is_system is False
        assert m.server_id == 0

    def test_wechat_message_fields(self):
        m = WeChatMessage(
            local_id=1,
            server_id=9999,
            local_type=1,
            create_time=1234567890,
            sender_name="张三",
            content="你好",
            group_username="111@chatroom",
        )
        assert m.is_text is True
        assert m.sender_name == "张三"


# ============================================================
# Test: Contact Row Parsing
# ============================================================


class TestContactParsing:
    """联系人行解析。"""

    def test_parse_v4_contact(self):
        row = {
            "username": "user123",
            "nick_name": "小红",
            "remark": "班花",
            "alias": "xiaohong",
        }
        c = _parse_contact_row(row)
        assert c.username == "user123"
        assert c.display_name == "班花"  # remark 优先

    def test_parse_contact_no_remark(self):
        row = {
            "username": "user456",
            "nick_name": "小明",
            "remark": "",
            "alias": "",
        }
        c = _parse_contact_row(row)
        assert c.display_name == "小明"  # nickname fallback


# ============================================================
# Test: Timestamp Formatting
# ============================================================


class TestTimestampFormat:
    """时间格式化。"""

    def test_format_normal(self):
        result = _format_timestamp(1234567890)  # 2009-02-14 07:31:30 UTC
        assert ":" in result

    def test_format_zero(self):
        assert _format_timestamp(0) == "00:00:00"


# ============================================================
# Test: Group Reading
# ============================================================


class TestGroupReading:
    """群列表读取。"""

    def test_get_groups(self, tmp_path):
        """从模拟 contact.db 读取群列表。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db(ct_db)
        _make_message_db(msg_db)

        reader = WeChatDBReader(ct_db, msg_db)
        groups = reader.get_groups()
        reader.close()

        assert len(groups) == 3
        names = [g.nickname for g in groups]
        assert "班群" in names
        assert "AI交流群" in names
        assert "课程群" in names

    def test_empty_db(self, tmp_path):
        """空数据库返回空列表。"""
        ct_db = tmp_path / "empty.db"
        msg_db = tmp_path / "empty_msg.db"
        ct_db.write_text("")

        reader = WeChatDBReader(ct_db, msg_db)
        groups = reader.get_groups()
        assert groups == []

    def test_list_groups_top_level(self, tmp_path):
        """顶层 API list_groups。"""
        ct_db = tmp_path / "contact.db"
        _make_contact_db(ct_db)
        msg_db = tmp_path / "msg.db"
        _make_message_db(msg_db)

        # list_groups 只需要 contact_db
        groups = list_groups(ct_db)
        assert len(groups) >= 2


# ============================================================
# Test: Message Reading
# ============================================================


class TestMessageReading:
    """消息读取。"""

    def test_get_messages_all(self, tmp_path):
        """读取所有消息。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db(ct_db)
        _make_message_db(msg_db)

        reader = WeChatDBReader(ct_db, msg_db)
        msgs = reader.get_messages("111@chatroom")
        reader.close()

        assert len(msgs) == 6
        # 按时间升序
        assert msgs[0].content == "同学们，明天下午的课调到周五"
        assert msgs[-1].content == "好的"

    def test_get_messages_time_filter(self, tmp_path):
        """时间过滤。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db(ct_db)
        _make_message_db(msg_db)

        reader = WeChatDBReader(ct_db, msg_db)

        now = int(time.time())
        # 只查询最近 1 小时内的消息
        msgs = reader.get_messages(
            "111@chatroom",
            start_time=now - 2000,
            end_time=now,
        )
        reader.close()

        assert len(msgs) == 3  # 图片 + 系统 + 最后一条

    def test_get_messages_nonexistent_group(self, tmp_path):
        """不存在的群返回空列表。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db(ct_db)
        _make_message_db(msg_db)

        reader = WeChatDBReader(ct_db, msg_db)
        msgs = reader.get_messages("nonexistent@chatroom")
        reader.close()

        assert msgs == []

    def test_message_types(self, tmp_path):
        """消息类型标记正确。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db(ct_db)
        _make_message_db(msg_db)

        reader = WeChatDBReader(ct_db, msg_db)
        msgs = reader.get_messages("111@chatroom")
        reader.close()

        text_msgs = [m for m in msgs if m.is_text]
        img_msgs = [m for m in msgs if m.local_type == 3]
        sys_msgs = [m for m in msgs if m.is_system]

        assert len(text_msgs) == 4  # 文本
        assert len(img_msgs) == 1   # 图片
        assert len(sys_msgs) == 1   # 系统消息

    def test_sender_name_resolved(self, tmp_path):
        """发送者名称正确解析。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db(ct_db)
        _make_message_db(msg_db)

        reader = WeChatDBReader(ct_db, msg_db)
        msgs = reader.get_messages("111@chatroom")
        reader.close()

        # 第一条消息发送者是 user_zhang (sender_id=1) → 张三
        first = msgs[0]
        assert first.sender_name in ("张三", "zhangsan")

    def test_read_recent_messages(self, tmp_path):
        """顶层 API 读最近消息。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db(ct_db)
        _make_message_db(msg_db)

        recent = read_recent_messages(ct_db, msg_db, "111@chatroom", count=3)
        assert len(recent) == 3
        # 应该是最后 3 条
        assert recent[-1].content == "好的"


# ============================================================
# Test: Content Parsing
# ============================================================


class TestContentParsing:
    """消息内容解析。"""

    def test_parse_sender_id_prefix(self, tmp_path):
        """解析 "sender_id\\ncontent" 格式。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db(ct_db)
        _make_message_db(msg_db)

        reader = WeChatDBReader(ct_db, msg_db)
        msgs = reader.get_messages("111@chatroom")
        reader.close()

        # 第一条消息: "1\n同学们..."
        first = msgs[0]
        assert first.sender_id == 1
        assert "调" in first.content

    def test_zstd_detection(self, tmp_path):
        """ZSTD 压缩内容检测。"""
        import zstandard as zstd

        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db(ct_db)
        _make_message_db(msg_db)

        # 手动插入一条 ZSTD 压缩的消息内容
        conn = sqlite3.connect(str(msg_db))
        md5 = hashlib.md5("111@chatroom".encode()).hexdigest()
        table = f"Msg_{md5}"

        raw = "1\n这是压缩后的测试消息"
        cctx = zstd.ZstdCompressor()
        compressed = cctx.compress(raw.encode())

        conn.execute(
            f"INSERT INTO [{table}] VALUES (99, 99999, 1, 1, ?, 99, ?, NULL, 4)",
            (int(time.time()), compressed),
        )
        conn.commit()
        conn.close()

        reader = WeChatDBReader(ct_db, msg_db)
        msgs = reader.get_messages("111@chatroom")
        reader.close()

        zstd_msg = [m for m in msgs if m.server_id == 99999]
        assert len(zstd_msg) == 1
        assert zstd_msg[0].content == "这是压缩后的测试消息"


# ============================================================
# Test: Name Resolution
# ============================================================


class TestNameResolution:
    """发送者名称解析。"""

    def test_resolve_sender_from_name2id(self, tmp_path):
        """通过 Name2Id + contact 解析发送者名称。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db(ct_db)
        _make_message_db(msg_db)

        reader = WeChatDBReader(ct_db, msg_db)
        reader._build_name_cache()

        # sender_id=1 → user_zhang → "张三"
        name = reader.resolve_sender_name(1)
        assert name == "张三" or name == "zhangsan"

        # sender_id=2 → user_li → "助教小李" (remark 优先)
        name = reader.resolve_sender_name(2)
        assert name == "助教小李"

    def test_resolve_unknown_sender(self, tmp_path):
        """未知 sender_id 返回占位符。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db(ct_db)
        _make_message_db(msg_db)

        reader = WeChatDBReader(ct_db, msg_db)
        name = reader.resolve_sender_name(99999)
        assert "99999" in name


# ============================================================
# Test: WeChatDBReader Lifecycle
# ============================================================


class TestReaderLifecycle:
    """Reader 生命周期。"""

    def test_close(self, tmp_path):
        """close() 正常关闭连接。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db(ct_db)
        _make_message_db(msg_db)

        reader = WeChatDBReader(ct_db, msg_db)
        _ = reader.get_groups()  # 建立连接
        reader.close()
        # 无异常 = 通过

    def test_lazy_connection(self, tmp_path):
        """连接是懒初始化的。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db(ct_db)
        _make_message_db(msg_db)

        reader = WeChatDBReader(ct_db, msg_db)
        assert reader._contact_conn is None
        assert reader._message_conn is None

        _ = reader.get_groups()
        assert reader._contact_conn is not None
        reader.close()
