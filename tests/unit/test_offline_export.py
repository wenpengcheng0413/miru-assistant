"""
Miru Assistant — 离线全量导出器单元测试。

测试覆盖:
    - session_table_md5 计算（MD5(wxid) → 表名）
    - 模拟数据库定位会话表（跨分片，不误伤其他会话）
    - sender 身份判定与统计（我 vs Krista）
    - 文本消息导出格式
    - 非文本摘要（图片/语音/链接 XML）
    - 联系人不存在 / 无消息表 → 不崩溃
    - summarize_content 纯函数

使用 sqlite3 明文模拟微信 4.x 数据库结构
（OfflineWeChatDB 无密钥时自动回退标准 sqlite3）。
"""

import hashlib
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

from miru.chat_analyzer.offline_exporter import ContactFullExporter
from miru.chat_analyzer.offline_reader import (
    MSG_TYPE_IMAGE,
    MSG_TYPE_TEXT,
    OfflineWeChatDB,
    decompress_zstd,
    session_table_md5,
    summarize_content,
)

# ============================================================
# Helpers — 模拟微信 4.x 账号目录
# ============================================================

SELF_WXID = "wxid_self"
CONTACT_WXID = "wxid_krista_test"  # 虚构测试 wxid（勿用真实账号）
CONTACT_NAME = "Krista"


def _make_contact_db(db_path: Path) -> None:
    """创建模拟 contact.db（含 Krista 与另一联系人）。"""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE contact (
            username TEXT,
            alias TEXT,
            remark TEXT,
            nick_name TEXT
        )
    """)
    conn.execute(
        "INSERT INTO contact VALUES (?, ?, ?, ?)",
        (CONTACT_WXID, "do4urself", "🐱👀", "Krista"),
    )
    conn.execute(
        "INSERT INTO contact VALUES (?, ?, ?, ?)",
        ("wxid_other", "", "", "路人甲"),
    )
    conn.commit()
    conn.close()


def _msg_row(
    local_id: int,
    local_type: int,
    sender_id: int,
    create_time: int,
    content: str,
) -> tuple:
    """构造 Msg 表一行 (local_id, server_id, local_type, real_sender_id, create_time, sort_seq, message_content)。"""
    return (local_id, 10000 + local_id, local_type, sender_id, create_time, local_id, content)


def _make_msg_db(
    db_path: Path,
    wxid: str = CONTACT_WXID,
    rows: list[tuple] | None = None,
) -> str:
    """创建模拟 message_N.db（Name2Id + Msg_<md5> 表），返回表名。"""
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE Name2Id (user_name TEXT)")
    # rowid=1 → 自己, rowid=2 → Krista, rowid=3 → 路人
    conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (1, ?)", (SELF_WXID,))
    conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (2, ?)", (CONTACT_WXID,))
    conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (3, 'wxid_other')")

    if rows is None:
        base = 1_700_000_000
        rows = [
            _msg_row(1, MSG_TYPE_TEXT, 1, base, "哈喽"),
            _msg_row(2, MSG_TYPE_TEXT, 2, base + 60, "睡了吗"),
            _msg_row(3, MSG_TYPE_TEXT, 1, base + 120, "今天有空吗"),
            _msg_row(4, MSG_TYPE_TEXT, 2, base + 180, "有的"),
        ]

    table = f"Msg_{session_table_md5(wxid)}"
    conn.execute(f"""
        CREATE TABLE [{table}] (
            local_id INTEGER,
            server_id INTEGER,
            local_type INTEGER DEFAULT 1,
            real_sender_id INTEGER DEFAULT 0,
            create_time INTEGER,
            sort_seq INTEGER,
            message_content BLOB
        )
    """)
    for r in rows:
        conn.execute(f"INSERT INTO [{table}] VALUES (?, ?, ?, ?, ?, ?, ?)", r)

    conn.commit()
    conn.close()
    return table


def _make_other_table(db_path: Path, wxid: str = "wxid_other") -> str:
    """创建另一联系人的会话表（应不被命中）。"""
    conn = sqlite3.connect(str(db_path))
    table = f"Msg_{session_table_md5(wxid)}"
    conn.execute(f"""
        CREATE TABLE [{table}] (
            local_id INTEGER,
            server_id INTEGER,
            local_type INTEGER DEFAULT 1,
            real_sender_id INTEGER DEFAULT 0,
            create_time INTEGER,
            sort_seq INTEGER,
            message_content BLOB
        )
    """)
    conn.execute(
        f"INSERT INTO [{table}] VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, 90001, MSG_TYPE_TEXT, 3, 1_700_000_000, 1, "别人的消息"),
    )
    conn.commit()
    conn.close()
    return table


@pytest.fixture
def wx_account(tmp_path: Path) -> Path:
    """创建模拟微信账号目录（明文库，无密钥文件）。"""
    acct = tmp_path / f"{SELF_WXID}_a01"
    storage = acct / "db_storage"
    (storage / "contact").mkdir(parents=True)
    (storage / "message").mkdir(parents=True)
    _make_contact_db(storage / "contact" / "contact.db")
    _make_msg_db(storage / "message" / "message_0.db")
    return acct


def _export_dir_texts(result) -> tuple[str, str]:
    """读取导出结果的 chat.txt / chat_raw.txt 内容。"""
    chat = Path(result.output_file).read_text(encoding="utf-8")
    raw = Path(result.raw_output_file).read_text(encoding="utf-8")
    return chat, raw


def _sender_counts(chat_text: str) -> Counter:
    """解析 chat.txt 的 sender 分布。"""
    senders = re.findall(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] (.+?)：$", chat_text, re.M)
    return Counter(senders)


# ============================================================
# Test: session_table_md5
# ============================================================


class TestSessionTableMd5:
    """MD5(wxid) → 表名。"""

    def test_md5_correct(self):
        """MD5 计算正确（与已知值比对）。"""
        assert session_table_md5(CONTACT_WXID) == hashlib.md5(CONTACT_WXID.encode()).hexdigest()

    def test_table_name_format(self):
        """表名格式为 Msg_<md5>。"""
        assert session_table_md5(CONTACT_WXID).startswith("Msg_") is False  # 返回裸 md5
        assert len(session_table_md5(CONTACT_WXID)) == 32

    def test_deterministic(self):
        """同一 wxid 结果一致。"""
        assert session_table_md5(CONTACT_WXID) == session_table_md5(CONTACT_WXID)


# ============================================================
# Test: OfflineWeChatDB — 表定位
# ============================================================


class TestFindSessionTables:
    """模拟数据库 → 找到对应 Msg_ 表。"""

    def test_finds_contact_table(self, wx_account: Path):
        """命中 Krista 的会话表。"""
        db = OfflineWeChatDB(wx_account)
        try:
            tables = db.find_session_tables(CONTACT_WXID)
            assert len(tables) == 1
            table, shard, count = tables[0]
            assert table == f"Msg_{session_table_md5(CONTACT_WXID)}"
            assert shard == "message/message_0.db"
            assert count == 2  # Krista 作为发送者的消息数
        finally:
            db.close()

    def test_does_not_hit_other_tables(self, wx_account: Path):
        """不误伤其他联系人的会话表。"""
        _make_other_table(wx_account / "db_storage" / "message" / "message_0.db")
        db = OfflineWeChatDB(wx_account)
        try:
            tables = db.find_session_tables(CONTACT_WXID)
            # 只有 Krista 的表
            assert len(tables) == 1
            assert all(t != f"Msg_{session_table_md5('wxid_other')}" for t, _, _ in tables)
        finally:
            db.close()

    def test_cross_shard(self, wx_account: Path):
        """同一会话跨分片 → 全部命中。"""
        _make_msg_db(wx_account / "db_storage" / "message" / "message_1.db")
        db = OfflineWeChatDB(wx_account)
        try:
            tables = db.find_session_tables(CONTACT_WXID)
            assert len(tables) == 2
            shards = {s for _, s, _ in tables}
            assert shards == {"message/message_0.db", "message/message_1.db"}
        finally:
            db.close()

    def test_no_table_returns_empty(self, wx_account: Path):
        """无消息表的联系人 → 空列表（不崩溃）。"""
        db = OfflineWeChatDB(wx_account)
        try:
            assert db.find_session_tables("wxid_nonexistent") == []
        finally:
            db.close()

    def test_resolve_contact(self, wx_account: Path):
        """按名称解析联系人 wxid。"""
        db = OfflineWeChatDB(wx_account)
        try:
            c = db.resolve_contact("Krista")
            assert c["username"] == CONTACT_WXID
            assert c["display_name"] == "🐱👀"  # remark > nickname
            # 模糊匹配
            assert db.resolve_contact("rista")["username"] == CONTACT_WXID
            # 微信号匹配
            assert db.resolve_contact("do4urself")["username"] == CONTACT_WXID
        finally:
            db.close()

    def test_resolve_contact_not_found(self, wx_account: Path):
        """联系人不存在 → LookupError。"""
        db = OfflineWeChatDB(wx_account)
        try:
            with pytest.raises(LookupError):
                db.resolve_contact("不存在的人")
        finally:
            db.close()


# ============================================================
# Test: 消息读取与 sender 判定
# ============================================================


class TestReadMessages:
    """消息读取与身份判定。"""

    def test_messages_sorted_by_time(self, wx_account: Path):
        """消息按时间升序。"""
        db = OfflineWeChatDB(wx_account)
        try:
            tables = db.find_session_tables(CONTACT_WXID)
            msgs = db.read_all_messages(tables[0][0], tables[0][1])
            assert len(msgs) == 4
            for i in range(1, len(msgs)):
                assert msgs[i].timestamp >= msgs[i - 1].timestamp
            assert msgs[0].content == "哈喽"
        finally:
            db.close()

    def test_sender_username_mapped(self, wx_account: Path):
        """sender_username 正确映射（wxid）。"""
        db = OfflineWeChatDB(wx_account)
        try:
            tables = db.find_session_tables(CONTACT_WXID)
            msgs = db.read_all_messages(tables[0][0], tables[0][1])
            by_content = {m.content: m for m in msgs}
            assert by_content["哈喽"].sender_username == SELF_WXID
            assert by_content["睡了吗"].sender_username == CONTACT_WXID
            # 显示名: contact.db 有 Krista 的 remark 🐱👀
            assert by_content["睡了吗"].sender == "🐱👀"
        finally:
            db.close()


# ============================================================
# Test: ContactFullExporter 集成
# ============================================================


class TestFullExporter:
    """导出 chat.txt + chat_raw.txt。"""

    def test_export_basic(self, wx_account: Path, tmp_path: Path):
        """基本导出 — 文件生成与内容。"""
        exporter = ContactFullExporter(wx_account)
        result = exporter.export(CONTACT_NAME, output_dir=tmp_path / "output")

        assert result.success, result.errors
        assert result.total_messages == 4
        assert result.text_messages == 4
        assert result.output_file.endswith("chat.txt")
        assert result.raw_output_file.endswith("chat_raw.txt")

        chat, raw = _export_dir_texts(result)
        assert "联系人：Krista" in chat
        assert "消息数量：4" in chat
        assert "[哈喽" not in chat  # 时间戳格式 [2026-...] 我：
        assert "[202" in chat
        assert "哈喽" in chat
        assert "睡了吗" in chat

    def test_header_not_duplicated(self, wx_account: Path, tmp_path: Path):
        """文件头只出现一次（防止隐式字符串拼接导致头部重复 60 次）。"""
        exporter = ContactFullExporter(wx_account)
        result = exporter.export(CONTACT_NAME, output_dir=tmp_path / "output")
        chat, raw = _export_dir_texts(result)
        # 头部块整体只出现 1 次: "="*60 首尾各一次，共 2 处
        assert chat.count("联系人：") == 1
        assert chat.count("=" * 60) == 2
        assert raw.count("联系人：") == 1
        assert raw.count("=" * 60) == 2

    def test_sender_counts(self, wx_account: Path, tmp_path: Path):
        """sender 统计: 我 vs Krista。"""
        exporter = ContactFullExporter(wx_account)
        result = exporter.export(CONTACT_NAME, output_dir=tmp_path / "output")
        chat, _ = _export_dir_texts(result)
        counts = _sender_counts(chat)
        assert counts["我"] == 2
        assert counts[CONTACT_NAME] == 2

    def test_raw_file_contains_original(self, wx_account: Path, tmp_path: Path):
        """chat_raw.txt 含原始内容。"""
        exporter = ContactFullExporter(wx_account)
        result = exporter.export(CONTACT_NAME, output_dir=tmp_path / "output")
        _, raw = _export_dir_texts(result)
        assert "哈喽" in raw

    def test_export_by_wxid(self, wx_account: Path, tmp_path: Path):
        """直接指定 wxid（跳过名称解析）。"""
        exporter = ContactFullExporter(wx_account)
        result = exporter.export("自定义显示名", wxid=CONTACT_WXID, output_dir=tmp_path / "o")
        assert result.success
        assert result.total_messages == 4

    def test_export_unknown_contact(self, wx_account: Path, tmp_path: Path):
        """联系人不存在 → 不崩溃，返回错误。"""
        exporter = ContactFullExporter(wx_account)
        result = exporter.export("不存在的人", output_dir=tmp_path / "output")
        assert not result.success
        assert result.errors

    def test_export_no_messages(self, wx_account: Path, tmp_path: Path):
        """有联系人但无消息 → 空 chat.txt（不崩溃）。"""
        # 在 contact.db 加入无消息联系人
        conn = sqlite3.connect(str(wx_account / "db_storage" / "contact" / "contact.db"))
        conn.execute("INSERT INTO contact VALUES (?, ?, ?, ?)", ("wxid_nomsg", "", "", "无消息"))
        conn.commit()
        conn.close()

        exporter = ContactFullExporter(wx_account)
        result = exporter.export("无消息", output_dir=tmp_path / "output")
        assert result.success, result.errors  # 空导出不算失败
        assert result.total_messages == 0
        assert Path(result.output_file).exists()

    def test_image_message_summarized(self, wx_account: Path, tmp_path: Path):
        """图片消息 → [图片] 摘要。"""
        img_xml = '<msg><img length="100" md5="aabbccddeeff00112233445566778899"/></msg>'
        conn = sqlite3.connect(str(wx_account / "db_storage" / "message" / "message_0.db"))
        table = f"Msg_{session_table_md5(CONTACT_WXID)}"
        conn.execute(
            f"INSERT INTO [{table}] VALUES (?, ?, ?, ?, ?, ?, ?)",
            _msg_row(9, MSG_TYPE_IMAGE, 2, 1_700_000_100, img_xml),
        )
        conn.commit()
        conn.close()

        exporter = ContactFullExporter(wx_account)
        result = exporter.export(CONTACT_NAME, output_dir=tmp_path / "output")
        chat, raw = _export_dir_texts(result)
        assert "[图片] (md5=aabbccdd)" in chat
        assert img_xml in raw  # 原始版保留 XML

    def test_voice_message_summarized(self, wx_account: Path, tmp_path: Path):
        """语音消息 → [语音] 摘要。"""
        conn = sqlite3.connect(str(wx_account / "db_storage" / "message" / "message_0.db"))
        table = f"Msg_{session_table_md5(CONTACT_WXID)}"
        conn.execute(
            f"INSERT INTO [{table}] VALUES (?, ?, ?, ?, ?, ?, ?)",
            _msg_row(10, 34, 2, 1_700_000_200, '<msg><voicemsg voicelength = "4200"/></msg>'),
        )
        conn.commit()
        conn.close()

        exporter = ContactFullExporter(wx_account)
        result = exporter.export(CONTACT_NAME, output_dir=tmp_path / "output")
        chat, _ = _export_dir_texts(result)
        assert "[语音] (时长 4s)" in chat


# ============================================================
# Test: summarize_content 纯函数
# ============================================================


class TestSummarizeContent:
    """非文本摘要函数。"""

    def test_text_unchanged(self):
        """文本原样返回。"""
        assert summarize_content("你好呀", MSG_TYPE_TEXT) == "你好呀"

    def test_empty(self):
        """空内容 → 空串（调用方填充占位）。"""
        assert summarize_content("", MSG_TYPE_TEXT) == ""
        assert summarize_content("   ", 3) == ""

    def test_image(self):
        """图片 XML → [图片]。"""
        xml = '<msg><img md5="0123456789abcdef0123456789abcdef"/></msg>'
        result = summarize_content(xml, MSG_TYPE_IMAGE)
        assert result == "[图片] (md5=01234567)"

    def test_image_no_md5(self):
        """无 md5 的图片 → 简版 [图片]。"""
        assert summarize_content("<msg><img/></msg>", MSG_TYPE_IMAGE) == "[图片]"

    def test_voice(self):
        """语音 XML → [语音] (时长 Xs)。"""
        xml = '<msg><voicemsg endflag = "1" voicelength = "2780"/></msg>'
        assert summarize_content(xml, 34) == "[语音] (时长 2s)"

    def test_appmsg_title(self):
        """链接/文件 XML → 提取标题。"""
        xml = '<msg><appmsg><title>今天天气真好</title><type>57</type></appmsg></msg>'
        result = summarize_content(xml, 49)
        assert "标题: 今天天气真好" in result
        assert "[链接]" in result

    def test_appmsg_refermsg(self):
        """引用消息 → 提取 displayname + content。"""
        xml = (
            '<msg><appmsg><refermsg>'
            "<displayname>Krista</displayname><content>不是吧老铁。。</content>"
            "</refermsg></appmsg></msg>"
        )
        result = summarize_content(xml, 49)
        assert "引用 Krista: 不是吧老铁。。" in result

    def test_plain_xml_fallback(self):
        """其他 XML → 去标签提取文本。"""
        assert summarize_content("<msg><title>简单文本</title></msg>", 49) == "简单文本"


# ============================================================
# Test: decompress_zstd
# ============================================================


class TestDecompressZstd:
    """ZSTD 解压。"""

    def test_non_zstd_passthrough(self):
        """非 ZSTD 数据原样返回。"""
        data = b"plain text"
        assert decompress_zstd(data) == data

    def test_zstd_roundtrip(self):
        """ZSTD 压缩数据正确解压。"""
        import zstandard as zstd

        payload = "微信消息内容".encode("utf-8")
        compressed = zstd.ZstdCompressor().compress(payload)
        assert decompress_zstd(compressed) == payload


# ============================================================
# Test: 时间格式
# ============================================================


class TestTimestampFormat:
    """导出时间戳格式。"""

    def test_minute_precision(self):
        """chat.txt 使用分钟级时间戳（与在线 ChatExporter 兼容）。"""
        ts = datetime(2026, 7, 1, 10, 32, 5).timestamp()
        formatted = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        assert formatted == "2026-07-01 10:32"

    def test_stats_compatibility(self):
        """时间戳能被 statistics._parse_header 解析。"""
        from miru.chat_analyzer.statistics import _parse_header

        parsed = _parse_header("[2026-07-01 10:32] 我：")
        assert parsed is not None
        assert parsed[1] == "我"
        assert parsed[2] is True
