"""
Miru Assistant — Chat Analyzer 联系人白名单单元测试。

测试覆盖:
    - load_contact_aliases: 文件存在/不存在/空/损坏
    - resolve_via_aliases: name/username/remark 匹配、大小写、无匹配
    - export() 白名单模式: username 直接指定跳过模糊匹配

不依赖真实微信环境 — 全部 mock。
"""

from unittest.mock import MagicMock, patch

from miru.chat_analyzer.contacts import (
    ContactAlias,
    load_contact_aliases,
    resolve_via_aliases,
)

# ============================================================
# Test Data
# ============================================================

_SAMPLE_YAML = """\
contacts:
  - name: "Krista"
    username: "do4urself"
    remark: "🐱👀"
  - name: "张三"
    username: "zhangsan_wxid"
  - name: "李四"
    remark: "小李"
"""


# ============================================================
# Test: load_contact_aliases
# ============================================================


class TestLoadContactAliases:
    """白名单加载。"""

    def test_load_valid(self, tmp_path):
        """正常加载。"""
        path = tmp_path / "contacts.yaml"
        path.write_text(_SAMPLE_YAML, encoding="utf-8")

        aliases = load_contact_aliases(path)
        assert len(aliases) == 3
        assert aliases[0].name == "Krista"
        assert aliases[0].username == "do4urself"
        assert aliases[0].remark == "🐱👀"
        assert aliases[1].username == "zhangsan_wxid"
        assert aliases[2].remark == "小李"

    def test_missing_file(self, tmp_path):
        """文件不存在 → 空列表。"""
        assert load_contact_aliases(tmp_path / "nonexistent.yaml") == []

    def test_empty_file(self, tmp_path):
        """空文件 → 空列表。"""
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        assert load_contact_aliases(path) == []

    def test_no_contacts_key(self, tmp_path):
        """无 contacts 键 → 空列表。"""
        path = tmp_path / "no_contacts.yaml"
        path.write_text("other: 1", encoding="utf-8")
        assert load_contact_aliases(path) == []

    def test_corrupt_yaml(self, tmp_path):
        """损坏 YAML → 空列表（不抛异常）。"""
        path = tmp_path / "corrupt.yaml"
        path.write_text("contacts: [unclosed", encoding="utf-8")
        assert load_contact_aliases(path) == []

    def test_entry_without_name_skipped(self, tmp_path):
        """无 name 的条目被跳过。"""
        path = tmp_path / "no_name.yaml"
        path.write_text(
            "contacts:\n  - username: 'only_username'\n  - name: '有效'\n",
            encoding="utf-8",
        )
        aliases = load_contact_aliases(path)
        assert len(aliases) == 1
        assert aliases[0].name == "有效"


# ============================================================
# Test: resolve_via_aliases
# ============================================================


class TestResolveViaAliases:
    """白名单匹配。"""

    def _make_aliases(self) -> list[ContactAlias]:
        return [
            ContactAlias(name="Krista", username="do4urself", remark="🐱👀"),
            ContactAlias(name="张三", username="zhangsan_wxid", remark=""),
        ]

    def test_match_by_username(self):
        """按微信号匹配。"""
        alias = resolve_via_aliases(self._make_aliases(), "do4urself")
        assert alias is not None
        assert alias.name == "Krista"

    def test_match_by_name(self):
        """按显示名匹配。"""
        alias = resolve_via_aliases(self._make_aliases(), "Krista")
        assert alias is not None
        assert alias.username == "do4urself"

    def test_match_by_remark(self):
        """按备注名（emoji）匹配。"""
        alias = resolve_via_aliases(self._make_aliases(), "🐱👀")
        assert alias is not None
        assert alias.name == "Krista"

    def test_case_insensitive(self):
        """大小写不敏感。"""
        alias = resolve_via_aliases(self._make_aliases(), "DO4URSELF")
        assert alias is not None
        assert alias.name == "Krista"

    def test_no_match(self):
        """无匹配 → None。"""
        assert resolve_via_aliases(self._make_aliases(), "不存在") is None

    def test_empty_aliases(self):
        """空白名单 → None。"""
        assert resolve_via_aliases([], "Krista") is None

    def test_empty_query(self):
        """空查询 → None。"""
        assert resolve_via_aliases(self._make_aliases(), "") is None


# ============================================================
# Test: export() 白名单模式
# ============================================================


class TestExportWithUsername:
    """export(username=...) 直接指定微信 ID。"""

    def test_export_with_username_skips_resolve(self, tmp_path):
        """提供 username 时跳过模糊匹配，直接使用。"""
        from miru.chat_analyzer.exporter import ChatExporter
        from miru.chat_analyzer.models import ExportResult
        from miru.collector.wechat_reader import WeChatDBReader

        # 构造 fake reader（get_messages 返回空）
        fake_reader = MagicMock(spec=WeChatDBReader)
        fake_reader.get_messages.return_value = []
        fake_reader.close.return_value = None

        exporter = ChatExporter(config_path="config/settings.yaml")
        with patch.object(exporter, "_open_readers", return_value=([fake_reader], True)):
            result = exporter.export(
                contact_name="Krista",
                output_dir=str(tmp_path),
                username="do4urself",
            )

        assert isinstance(result, ExportResult)
        assert result.contact_username == "do4urself"
        assert result.total_messages == 0
        # 验证 get_messages 使用白名单 username（而非模糊匹配结果）
        call_args = fake_reader.get_messages.call_args
        assert call_args.args[0] == "do4urself"
        # 验证没有调用 get_contacts（跳过模糊匹配）
        fake_reader.get_contacts.assert_not_called()

    def test_export_without_username_uses_resolve(self, tmp_path):
        """不提供 username 时走模糊匹配。"""
        from miru.chat_analyzer.exporter import ChatExporter
        from miru.collector.wechat_reader import WeChatContact, WeChatDBReader

        fake_reader = MagicMock(spec=WeChatDBReader)
        fake_reader.get_messages.return_value = []
        fake_reader.get_contacts.return_value = [
            WeChatContact(username="wxid_a", nickname="张三", remark="", alias=""),
        ]
        fake_reader.close.return_value = None

        exporter = ChatExporter(config_path="config/settings.yaml")
        with patch.object(exporter, "_open_readers", return_value=([fake_reader], True)):
            result = exporter.export(
                contact_name="张三",
                output_dir=str(tmp_path),
            )

        assert result.contact_username == "wxid_a"
        fake_reader.get_contacts.assert_called_once()


# ============================================================
# Test: ContactAlias model
# ============================================================


class TestContactAliasModel:
    """ContactAlias dataclass。"""

    def test_defaults(self):
        """默认值。"""
        alias = ContactAlias(name="测试")
        assert alias.username == ""
        assert alias.remark == ""
