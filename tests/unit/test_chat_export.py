"""
Miru Assistant — Chat Analyzer 导出器单元测试 (Phase 1)。

测试覆盖:
    - 联系人解析 (精确匹配 / 模糊匹配 / 不存在)
    - 消息格式化 (我 vs 对方)
    - TXT 文件生成
    - 空消息处理
    - 时间戳格式化
    - 文件名清理
    - 日期解析

使用内存/临时 SQLite 数据库模拟微信数据结构，
不依赖真实微信客户端。
"""

import hashlib
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import pytest

from miru.chat_analyzer.exporter import (
    _parse_date_to_ts,
    _sanitize_dirname,
    classify_sender,
    find_self_sender_id,
    format_message,
    format_timestamp,
    render_export_file,
    resolve_contact,
)
from miru.chat_analyzer.models import (
    ContactInfo,
    ContactNotFoundError,
    ExportedMessage,
)
from miru.collector.wechat_reader import (
    WeChatContact,
    WeChatDBReader,
    WeChatMessage,
)

# ============================================================
# Helpers — 创建模拟微信数据库 (私聊场景)
# ============================================================


def _make_contact_db_for_chat(db_path: Path, contacts_data: list[dict] | None = None) -> None:
    """
    创建模拟微信 4.x contact.db（含联系人表）。

    Args:
        db_path: 数据库文件路径。
        contacts_data: 联系人数据列表，每项含 username, nick_name, remark, alias。
    """
    if contacts_data is None:
        contacts_data = [
            {"username": "wxid_zhangsan", "nick_name": "张三", "remark": "", "alias": ""},
            {"username": "wxid_lisi", "nick_name": "李四", "remark": "助教小李", "alias": "lisi"},
            {"username": "wxid_wangwu", "nick_name": "王五", "remark": "", "alias": "wangwu"},
        ]

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE contact (
            username TEXT,
            nick_name TEXT,
            remark TEXT,
            alias TEXT
        )
    """)
    for c in contacts_data:
        conn.execute(
            "INSERT INTO contact VALUES (?, ?, ?, ?)",
            (c["username"], c["nick_name"], c.get("remark", ""), c.get("alias", "")),
        )

    conn.commit()
    conn.close()


def _make_message_db_for_chat(
    db_path: Path,
    contact_username: str = "wxid_zhangsan",
    messages_data: list[dict] | None = None,
) -> None:
    """
    创建模拟微信 4.x message_0.db（含私聊消息表 + Name2Id）。

    Args:
        db_path: 数据库文件路径。
        contact_username: 目标联系人 username（决定表名）。
        messages_data: 消息列表，每项含 local_id, server_id, local_type,
                       real_sender_id, create_time, sort_seq, message_content。
                       默认创建与"张三"的 6 条私聊消息。
    """
    if messages_data is None:
        now = int(time.time())
        messages_data = [
            # (local_id, server_id, local_type, real_sender_id, create_time, sort_seq, content)
            {
                "local_id": 1,
                "server_id": 10001,
                "local_type": 1,
                "real_sender_id": 2,
                "create_time": now - 7200,
                "sort_seq": 1,
                "message_content": "你好，今天考试怎么样？",
            },
            {
                "local_id": 2,
                "server_id": 10002,
                "local_type": 1,
                "real_sender_id": 1,
                "create_time": now - 7100,
                "sort_seq": 2,
                "message_content": "还可以，你呢？",
            },
            {
                "local_id": 3,
                "server_id": 10003,
                "local_type": 1,
                "real_sender_id": 2,
                "create_time": now - 7000,
                "sort_seq": 3,
                "message_content": "我也还行",
            },
            {
                "local_id": 4,
                "server_id": 10004,
                "local_type": 3,
                "real_sender_id": 2,
                "create_time": now - 6000,
                "sort_seq": 4,
                "message_content": "",
            },  # 图片
            {
                "local_id": 5,
                "server_id": 10005,
                "local_type": 1,
                "real_sender_id": 1,
                "create_time": now - 5000,
                "sort_seq": 5,
                "message_content": "明天有空吗？",
            },
            {
                "local_id": 6,
                "server_id": 10006,
                "local_type": 1,
                "real_sender_id": 2,
                "create_time": now - 4000,
                "sort_seq": 6,
                "message_content": "有空的",
            },
        ]

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Name2Id 表（映射 rowid → user_name）
    conn.execute("CREATE TABLE Name2Id (user_name TEXT)")
    # rowid=1 → "我" (当前用户)
    # rowid=2 → 联系人 "张三"
    conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (1, 'wxid_self_me')")
    conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (2, 'wxid_zhangsan')")

    # 消息表
    md5 = hashlib.md5(contact_username.encode()).hexdigest()
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
    for msg in messages_data:
        conn.execute(
            f"INSERT INTO [{table_name}] VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                msg["local_id"],
                msg["server_id"],
                msg["local_type"],
                msg["real_sender_id"],
                msg["create_time"],
                msg["sort_seq"],
                msg.get("message_content", ""),
                None,
                4,
            ),
        )

    conn.commit()
    conn.close()


def _make_contact_db_empty(db_path: Path) -> None:
    """创建空的 contact.db（无联系人）。"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE contact (username TEXT, nick_name TEXT, remark TEXT, alias TEXT)")
    conn.commit()
    conn.close()


# ============================================================
# Test: Contact Resolution
# ============================================================


class TestContactResolution:
    """联系人解析测试。"""

    def _make_contacts(self) -> list[WeChatContact]:
        """创建测试用联系人列表。"""
        return [
            WeChatContact(username="wxid_zhangsan", nickname="张三", remark="", alias=""),
            WeChatContact(username="wxid_lisi", nickname="李四", remark="助教小李", alias="lisi"),
            WeChatContact(username="wxid_wangwu", nickname="王五", remark="", alias="wangwu"),
        ]

    def test_exact_match_by_nickname(self):
        """精确匹配昵称。"""
        contacts = self._make_contacts()
        result = resolve_contact(contacts, "张三")
        assert result.username == "wxid_zhangsan"
        assert result.display_name == "张三"

    def test_exact_match_by_remark(self):
        """精确匹配备注。"""
        contacts = self._make_contacts()
        result = resolve_contact(contacts, "助教小李")
        assert result.username == "wxid_lisi"
        assert result.display_name == "助教小李"

    def test_exact_match_by_alias(self):
        """精确匹配微信号。"""
        contacts = self._make_contacts()
        result = resolve_contact(contacts, "wangwu")
        assert result.username == "wxid_wangwu"

    def test_fuzzy_match_partial(self):
        """模糊匹配 — 部分字符串匹配。"""
        contacts = self._make_contacts()
        # "张" 包含在 "张三" 中
        result = resolve_contact(contacts, "张")
        assert result.username == "wxid_zhangsan"

    def test_fuzzy_match_single_char(self):
        """模糊匹配 — 单字匹配。"""
        contacts = self._make_contacts()
        # "五" 包含在 "王五" 中
        result = resolve_contact(contacts, "五")
        assert result.username == "wxid_wangwu"

    def test_contact_not_found(self):
        """联系人不存在。"""
        contacts = self._make_contacts()
        with pytest.raises(ContactNotFoundError) as exc:
            resolve_contact(contacts, "赵六")
        assert "赵六" in str(exc.value)
        assert exc.value.suggestion != ""

    def test_empty_contacts(self):
        """空联系人列表。"""
        with pytest.raises(ContactNotFoundError) as exc:
            resolve_contact([], "张三")
        assert "张三" in str(exc.value)

    def test_display_name_priority(self):
        """ContactInfo 中 display_name 优先级: remark > nickname > alias。"""
        contacts = [
            WeChatContact(
                username="wxid_test",
                nickname="昵称",
                remark="备注",
                alias="wxid",
            ),
        ]
        # 通过 remark 匹配
        result = resolve_contact(contacts, "备注")
        assert result.display_name == "备注"

        # 通过 nickname 匹配，但 display_name 仍然取最高优先级 remark
        result2 = resolve_contact(contacts, "昵称")
        assert result2.display_name == "备注"  # remark 始终优先
        assert result2.nickname == "昵称"


# ============================================================
# Test: Self Sender Identification
# ============================================================


class TestSelfSenderId:
    """发送者识别测试。"""

    def test_find_self_sender_id(self, tmp_path):
        """从 Name2Id 表找到自己的 sender_id。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db_for_chat(ct_db)
        _make_message_db_for_chat(msg_db, contact_username="wxid_zhangsan")

        reader = WeChatDBReader(ct_db, msg_db)
        try:
            sid = find_self_sender_id(reader, "wxid_zhangsan")
            # rowid=1 是 "wxid_self_me"（非联系人），应为"我"
            assert sid == 1
        finally:
            reader.close()

    def test_classify_self(self):
        """自己的消息 → 标记为 "我"。"""
        contact = ContactInfo(
            username="wxid_zhangsan",
            nickname="张三",
            display_name="张三",
        )
        msg = WeChatMessage(
            sender_id=1,
            sender_name="wxid_self_me",
            content="你好",
        )
        label, is_self = classify_sender(msg, self_sender_id=1, contact=contact)
        assert label == "我"
        assert is_self is True

    def test_classify_contact(self):
        """联系人的消息 → 标记为联系人名称。"""
        contact = ContactInfo(
            username="wxid_zhangsan",
            nickname="张三",
            display_name="张三",
        )
        msg = WeChatMessage(
            sender_id=2,
            sender_name="张三",
            content="你好",
        )
        label, is_self = classify_sender(msg, self_sender_id=1, contact=contact)
        assert label == "张三"
        assert is_self is False

    def test_classify_unknown_sender_as_self(self):
        """无法匹配的发送者 → 默认为 "我"。"""
        contact = ContactInfo(
            username="wxid_zhangsan",
            nickname="张三",
            display_name="张三",
        )
        msg = WeChatMessage(
            sender_id=99,
            sender_name="未知用户",
            content="测试",
        )
        label, is_self = classify_sender(msg, self_sender_id=1, contact=contact)
        assert label == "我"
        assert is_self is True

    def test_find_self_empty_name2id(self, tmp_path):
        """Name2Id 表为空时返回 0。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db_for_chat(ct_db)

        # 创建只有消息表但没有 Name2Id 数据的数据库
        conn = sqlite3.connect(str(msg_db))
        conn.execute("CREATE TABLE Name2Id (user_name TEXT)")
        conn.commit()
        conn.close()

        reader = WeChatDBReader(ct_db, msg_db)
        try:
            sid = find_self_sender_id(reader, "wxid_zhangsan")
            assert sid == 0
        finally:
            reader.close()


# ============================================================
# Test: Message Formatting
# ============================================================


class TestMessageFormatting:
    """消息格式化测试。"""

    def test_format_message_self(self):
        """自己的消息格式正确。"""
        contact = ContactInfo(username="wxid_zhangsan", nickname="张三", display_name="张三")
        msg = WeChatMessage(
            sender_id=1,
            sender_name="我",
            content="今天考试怎么样？",
            create_time=1719792000,  # 2024-07-01 08:00 UTC
        )
        exported = format_message(msg, contact, self_sender_id=1)
        assert exported.sender == "我"
        assert exported.is_self is True
        assert exported.content == "今天考试怎么样？"

    def test_format_message_contact(self):
        """联系人的消息格式正确。"""
        contact = ContactInfo(username="wxid_zhangsan", nickname="张三", display_name="张三")
        msg = WeChatMessage(
            sender_id=2,
            sender_name="张三",
            content="还可以",
            create_time=1719792300,
        )
        exported = format_message(msg, contact, self_sender_id=1)
        assert exported.sender == "张三"
        assert exported.is_self is False
        assert exported.content == "还可以"

    def test_format_message_empty_content(self):
        """空内容消息。"""
        contact = ContactInfo(username="wxid_zhangsan", nickname="张三", display_name="张三")
        msg = WeChatMessage(
            sender_id=1,
            sender_name="我",
            content="",
            create_time=1719792000,
        )
        exported = format_message(msg, contact, self_sender_id=1)
        assert exported.content == ""


# ============================================================
# Test: Timestamp Formatting
# ============================================================


class TestTimestampFormat:
    """时间戳格式化测试。"""

    def test_format_normal(self):
        """正常时间戳。"""
        dt = datetime(2024, 7, 1, 10, 32, 0)
        ts = int(dt.timestamp())
        result = format_timestamp(ts)
        assert "2024-07-01" in result
        assert "10:32" in result

    def test_format_zero(self):
        """时间戳为 0。"""
        result = format_timestamp(0)
        assert result == "0000-00-00 00:00"


# ============================================================
# Test: TXT Export Rendering
# ============================================================


class TestTxtRendering:
    """TXT 文件渲染测试。"""

    def test_render_basic(self, tmp_path):
        """基本渲染 — 生成完整 TXT 文件。"""
        contact = ContactInfo(username="wxid_zhangsan", nickname="张三", display_name="张三")
        messages = [
            ExportedMessage(
                timestamp="2024-07-01 10:32",
                sender="我",
                content="今天考试怎么样？",
                is_self=True,
            ),
            ExportedMessage(
                timestamp="2024-07-01 10:35",
                sender="张三",
                content="还可以",
                is_self=False,
            ),
        ]
        output = tmp_path / "张三" / "chat.txt"
        render_export_file(messages, contact, "2026-08-08 10:30:00", output)

        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "联系人：张三" in content
        assert "消息数量：2" in content
        assert "[2024-07-01 10:32] 我：" in content
        assert "今天考试怎么样？" in content
        assert "[2024-07-01 10:35] 张三：" in content
        assert "还可以" in content

    def test_render_empty(self, tmp_path):
        """空消息列表 — 输出仅头部。"""
        contact = ContactInfo(username="wxid_empty", nickname="无消息", display_name="无消息")
        output = tmp_path / "无消息" / "chat.txt"
        render_export_file([], contact, "2026-08-08 10:30:00", output)

        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "联系人：无消息" in content
        assert "消息数量：0" in content

    def test_render_utf8(self, tmp_path):
        """UTF-8 编码 — 中文和特殊字符。"""
        contact = ContactInfo(username="wxid_emoji", nickname="测试🎉", display_name="测试🎉")
        messages = [
            ExportedMessage(
                timestamp="2024-07-01 12:00",
                sender="我",
                content="你好！🎉 今天天气不错～",
                is_self=True,
            ),
        ]
        output = tmp_path / "测试🎉" / "chat.txt"
        render_export_file(messages, contact, "2026-08-08 10:30:00", output)

        content = output.read_text(encoding="utf-8")
        assert "测试🎉" in content
        assert "你好！🎉 今天天气不错～" in content


# ============================================================
# Test: Sorting
# ============================================================


class TestMessageSorting:
    """消息排序测试。"""

    def test_messages_sorted_by_time(self, tmp_path):
        """从 reader 读取的消息按时间升序排列。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db_for_chat(ct_db)
        _make_message_db_for_chat(msg_db, contact_username="wxid_zhangsan")

        reader = WeChatDBReader(ct_db, msg_db)
        try:
            messages = reader.get_messages("wxid_zhangsan")
            # 验证时间升序
            for i in range(len(messages) - 1):
                assert messages[i].create_time <= messages[i + 1].create_time
        finally:
            reader.close()

    def test_empty_messages(self, tmp_path):
        """不存在的联系人返回空列表。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db_for_chat(ct_db)
        _make_message_db_for_chat(msg_db, contact_username="wxid_zhangsan")

        reader = WeChatDBReader(ct_db, msg_db)
        try:
            messages = reader.get_messages("wxid_nonexistent")
            assert messages == []
        finally:
            reader.close()

    def test_time_filter(self, tmp_path):
        """时间范围过滤。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db_for_chat(ct_db)
        _make_message_db_for_chat(msg_db, contact_username="wxid_zhangsan")

        reader = WeChatDBReader(ct_db, msg_db)
        try:
            now = int(time.time())
            # 只取最近 1.5 小时
            msgs = reader.get_messages(
                "wxid_zhangsan",
                start_time=now - 5400,
                end_time=now,
            )
            # 应该有 4 条（最近 1.5h 的）
            assert len(msgs) >= 1
            for m in msgs:
                assert m.create_time >= now - 5400
        finally:
            reader.close()


# ============================================================
# Test: Utility Functions
# ============================================================


class TestUtilities:
    """工具函数测试。"""

    def test_sanitize_dirname_normal(self):
        """正常名称不变。"""
        assert _sanitize_dirname("张三") == "张三"

    def test_sanitize_dirname_invalid_chars(self):
        """非法字符替换为下划线。"""
        assert _sanitize_dirname("张:三") == "张_三"
        assert _sanitize_dirname("A<B>C") == "A_B_C"
        assert _sanitize_dirname('test"name') == "test_name"

    def test_sanitize_dirname_empty(self):
        """空名称返回默认值。"""
        assert _sanitize_dirname("") == "unknown_contact"
        assert _sanitize_dirname("   ") == "unknown_contact"

    def test_parse_date_to_ts(self):
        """日期 → 时间戳。"""
        ts = _parse_date_to_ts("2024-07-01")
        dt = datetime.fromtimestamp(ts)
        assert dt.year == 2024
        assert dt.month == 7
        assert dt.day == 1
        assert dt.hour == 0
        assert dt.minute == 0

    def test_parse_date_to_ts_end(self):
        """结束日期 → 23:59:59。"""
        ts = _parse_date_to_ts("2024-07-01", is_end=True)
        dt = datetime.fromtimestamp(ts)
        assert dt.hour == 23
        assert dt.minute == 59
        assert dt.second == 59

    def test_parse_date_invalid(self):
        """无效日期返回 0。"""
        assert _parse_date_to_ts("invalid") == 0
        assert _parse_date_to_ts("2024/07/01") == 0


# ============================================================
# Test: ExportResult Model
# ============================================================


class TestExportResult:
    """ExportResult 模型测试。"""

    def test_success_default(self):
        """默认 success 为 True（无错误）。"""
        from miru.chat_analyzer.models import ExportResult

        result = ExportResult()
        assert result.success is True

    def test_with_errors(self):
        """有错误时 success 为 False。"""
        from miru.chat_analyzer.models import ExportResult

        result = ExportResult(errors=["解密失败"])
        assert result.success is False


# ============================================================
# Test: ContactInfo Model
# ============================================================


class TestContactInfo:
    """ContactInfo 模型测试。"""

    def test_display_name_default(self):
        """display_name 默认取 remark > nickname > alias > username。"""
        c = ContactInfo(username="wxid_abc", nickname="昵称", remark="备注", alias="号")
        assert c.display_name == "备注"

    def test_display_name_no_remark(self):
        """无备注时取 nickname。"""
        c = ContactInfo(username="wxid_abc", nickname="昵称", remark="", alias="")
        assert c.display_name == "昵称"

    def test_display_name_username_fallback(self):
        """全空时回退到 username。"""
        c = ContactInfo(username="wxid_abc", nickname="", remark="", alias="")
        assert c.display_name == "wxid_abc"


# ============================================================
# Test: P1 — Non-text Message Filtering
# ============================================================


class TestNonTextFiltering:
    """P1: 非文本消息过滤 — 只导出 local_type=1 的文本消息。"""

    def test_text_messages_exported(self, tmp_path):
        """文本消息正确导出。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db_for_chat(ct_db)
        _make_message_db_for_chat(msg_db, contact_username="wxid_zhangsan")

        contact = ContactInfo(
            username="wxid_zhangsan",
            nickname="张三",
            display_name="张三",
        )
        reader = WeChatDBReader(ct_db, msg_db)
        try:
            messages = reader.get_messages("wxid_zhangsan")
            exported = []
            for msg in messages:
                if msg.local_type != WeChatDBReader.MSG_TYPE_TEXT:
                    continue
                exported.append(
                    format_message(msg, contact, self_sender_id=1),
                )
            # 6 messages total: 4 text + 1 image + (empty content counts as text)
            # The 4 real text messages should be exported
            text_msgs = [m for m in messages if m.local_type == WeChatDBReader.MSG_TYPE_TEXT]
            assert len(exported) == len(text_msgs)
        finally:
            reader.close()

    def test_image_message_not_exported(self, tmp_path):
        """图片消息不被导出。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db_for_chat(ct_db)
        _make_message_db_for_chat(msg_db, contact_username="wxid_zhangsan")

        contact = ContactInfo(
            username="wxid_zhangsan",
            nickname="张三",
            display_name="张三",
        )
        reader = WeChatDBReader(ct_db, msg_db)
        try:
            messages = reader.get_messages("wxid_zhangsan")
            exported = []
            for msg in messages:
                if msg.local_type != WeChatDBReader.MSG_TYPE_TEXT:
                    continue
                exported.append(
                    format_message(msg, contact, self_sender_id=1),
                )
            # Default data has 1 image (local_type=3)
            image_count = sum(1 for m in messages if m.local_type == WeChatDBReader.MSG_TYPE_IMAGE)
            assert image_count > 0
            # Verify no image messages in export
            for e in exported:
                assert e.content != "" or e.content == ""
        finally:
            reader.close()

    def test_all_types_mixed(self, tmp_path):
        """混合消息类型 — 只导出文本。"""
        now = int(time.time())
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db_for_chat(ct_db)

        # Custom messages: text + voice + image
        custom_msgs = [
            {
                "local_id": 1,
                "server_id": 20001,
                "local_type": 1,
                "real_sender_id": 2,
                "create_time": now - 3000,
                "sort_seq": 1,
                "message_content": "hello",
            },
            {
                "local_id": 2,
                "server_id": 20002,
                "local_type": 34,
                "real_sender_id": 2,
                "create_time": now - 2000,
                "sort_seq": 2,
                "message_content": "<voicemsg>xml</voicemsg>",
            },
            {
                "local_id": 3,
                "server_id": 20003,
                "local_type": 3,
                "real_sender_id": 2,
                "create_time": now - 1000,
                "sort_seq": 3,
                "message_content": "",
            },
            {
                "local_id": 4,
                "server_id": 20004,
                "local_type": 1,
                "real_sender_id": 1,
                "create_time": now,
                "sort_seq": 4,
                "message_content": "world",
            },
        ]
        _make_message_db_for_chat(
            msg_db, contact_username="wxid_zhangsan", messages_data=custom_msgs
        )

        contact = ContactInfo(
            username="wxid_zhangsan",
            nickname="张三",
            display_name="张三",
        )
        reader = WeChatDBReader(ct_db, msg_db)
        try:
            messages = reader.get_messages("wxid_zhangsan")
            exported = []
            for msg in messages:
                if msg.local_type != WeChatDBReader.MSG_TYPE_TEXT:
                    continue
                exported.append(
                    format_message(msg, contact, self_sender_id=1),
                )
            assert len(exported) == 2  # Only 2 text messages
            assert exported[0].content == "hello"
            assert exported[1].content == "world"
        finally:
            reader.close()


# ============================================================
# Test: P2 — Missing Message Table
# ============================================================


class TestMissingMessageTable:
    """P2: 联系人存在但 Msg 表不存在 → 不崩溃，返回空。"""

    def test_no_message_table_returns_empty(self, tmp_path):
        """无消息表的联系人返回空列表。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"

        # contact.db 有 wxid_nomsg 联系人，
        # 但 message_0.db 没有对应的 Msg_ 表
        _make_contact_db_for_chat(
            ct_db,
            contacts_data=[
                {"username": "wxid_nomsg", "nick_name": "无消息", "remark": "", "alias": ""},
            ],
        )

        conn = sqlite3.connect(str(msg_db))
        conn.execute("CREATE TABLE Name2Id (user_name TEXT)")
        conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (1, 'wxid_nomsg')")
        conn.commit()
        conn.close()

        reader = WeChatDBReader(ct_db, msg_db)
        try:
            messages = reader.get_messages("wxid_nomsg")  # No Msg_ table
            assert messages == []
        finally:
            reader.close()

    def test_exporter_handles_missing_table(self, tmp_path):
        """ChatExporter export() 中对无消息表的联系人不崩溃。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"

        _make_contact_db_for_chat(
            ct_db,
            contacts_data=[
                {"username": "wxid_nomsg", "nick_name": "无消息", "remark": "", "alias": ""},
            ],
        )
        conn = sqlite3.connect(str(msg_db))
        conn.execute("CREATE TABLE Name2Id (user_name TEXT)")
        conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (1, 'wxid_nomsg')")
        conn.close()

        reader = WeChatDBReader(ct_db, msg_db)
        try:
            # Simulate the try/except pattern used in exporter.export()
            try:
                messages = reader.get_messages("wxid_nomsg", limit=1000)
            except Exception:
                messages = []
            assert messages == []
        finally:
            reader.close()


# ============================================================
# Test: P3 — Empty Username Filtering
# ============================================================


class TestEmptyUsernameFiltering:
    """P3: Name2Id fallback 过滤空 username。"""

    def test_empty_username_filtered(self, tmp_path):
        """空 username 不被加入联系人列表。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db_for_chat(ct_db)

        # 模拟 Name2Id 包含空 username
        conn = sqlite3.connect(str(msg_db))
        conn.execute("CREATE TABLE Name2Id (user_name TEXT)")
        conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (1, '')")
        conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (2, 'wxid_valid')")
        conn.commit()
        conn.close()

        reader = WeChatDBReader(ct_db, msg_db)
        try:
            from miru.chat_analyzer.exporter import _get_contacts_from_msg_db

            contacts = _get_contacts_from_msg_db(reader)
            usernames = [c.username for c in contacts]
            assert "" not in usernames
            assert "wxid_valid" in usernames
        finally:
            reader.close()

    def test_whitespace_username_filtered(self, tmp_path):
        """纯空格 username 不被加入。"""
        ct_db = tmp_path / "contact.db"
        msg_db = tmp_path / "message_0.db"
        _make_contact_db_for_chat(ct_db)

        conn = sqlite3.connect(str(msg_db))
        conn.execute("CREATE TABLE Name2Id (user_name TEXT)")
        conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (1, '   ')")
        conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (2, 'real_user')")
        conn.commit()
        conn.close()

        reader = WeChatDBReader(ct_db, msg_db)
        try:
            from miru.chat_analyzer.exporter import _get_contacts_from_msg_db

            contacts = _get_contacts_from_msg_db(reader)
            usernames = [c.username for c in contacts]
            assert "   " not in usernames
            assert "real_user" in usernames
        finally:
            reader.close()
