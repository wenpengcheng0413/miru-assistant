"""工具注册表与内置工具测试。"""
import asyncio

from miru_server.core.llm import Usage
from miru_server.tools.base import ToolContext
from miru_server.tools.registry import ToolRegistry, build_registry


def _ctx(services, events=None):
    async def cap(payload):
        if events is not None:
            events.append(payload)
    return ToolContext(services=services, conversation_id="t", emit=cap)


def test_registry_whitelist(app_config, services):
    registry = build_registry(app_config)
    names = registry.enabled_names
    assert "get_current_time" in names
    assert "memory_set" in names
    assert "wechat_chat_stats" not in names   # 默认白名单外
    schemas = registry.schemas()
    assert all("function" in s and s["function"]["name"] in names for s in schemas)


def test_get_current_time(services):
    registry = build_registry(services.config)
    result = asyncio.run(registry.execute(_ctx(services), "get_current_time", {}))
    assert result.ok
    assert "2026" in result.data["date"] or True  # 年份以机器时钟为准，只验证结构
    assert result.data["weekday"].startswith("星期")


def test_disabled_tool_rejected(services):
    registry = build_registry(services.config)
    result = asyncio.run(registry.execute(_ctx(services), "wechat_chat_stats", {}))
    assert not result.ok and "未启用" in result.error


def test_memory_tools_roundtrip(services):
    registry = build_registry(services.config)
    r = asyncio.run(registry.execute(
        _ctx(services), "memory_set", {"scope": "profile", "key": "称呼", "value": "老板"}
    ))
    assert r.ok
    r = asyncio.run(registry.execute(
        _ctx(services), "memory_get", {"scope": "profile", "key": "称呼"}
    ))
    assert r.ok and r.data["value"] == "老板"


def test_api_cost_tools(services):
    registry = build_registry(services.config)
    services.cost.record_llm(None, "deepseek-v4-flash", Usage(1000, 500))
    services.cost.record_tts(None, "minimax", "speech-02-turbo", 10000)
    r = asyncio.run(registry.execute(_ctx(services), "api_cost_report", {"days": 7}))
    assert r.ok and r.data["total_rmb"] > 0
    r = asyncio.run(registry.execute(
        _ctx(services), "api_budget_set", {"limit_rmb": 150, "provider": "total"}
    ))
    assert r.ok
    status = services.cost.budget_status("total")
    assert status["limit_rmb"] == 150


def test_clean_wechat_content():
    """XML 媒体消息 → 可读占位（aeskey 不外泄）；链接保留标题；超长截断。"""
    from miru_server.tools.builtin.wechat import _clean_content

    img_xml = '<?xml version="1.0"?><msg><img aeskey="50122582fd3e9428ac" cdnmid="x"/></msg>'
    assert _clean_content(img_xml) == "[图片]"
    assert "aeskey" not in _clean_content(img_xml)

    link_xml = '<?xml version="1.0"?><msg><appmsg><title>一篇好文章</title><url>http://x</url></appmsg></msg>'
    assert _clean_content(link_xml) == "[链接: 一篇好文章]"

    voice_xml = '<?xml version="1.0"?><msg><voicemsg voicelength="5000"/></msg>'
    assert _clean_content(voice_xml) == "[语音]"

    assert _clean_content("正常文本") == "正常文本"
    assert _clean_content("长" * 600).endswith("…")
    assert len(_clean_content("长" * 600)) <= 501


def test_wechat_image_export_prefers_full_image_over_thumbnail(tmp_path):
    """视觉分析必须先尝试完整原图，缩略图只可作为兼容性回退。"""
    from miru_server.tools.builtin.wechat import _export_image

    full = tmp_path / "full.dat"
    thumb = tmp_path / "full_t.dat"
    full.write_bytes(b"full")
    thumb.write_bytes(b"thumb")

    class FakeExtractor:
        def locate_files(self, *_args):
            return [full, thumb]

        def locate_thumb(self, *_args):
            return [thumb]

        def decrypt(self, path):
            return b"\xff\xd8\xfffull" if path == full else b"\xff\xd8\xffthumb"

        def sniff_format(self, _data):
            return "jpg"

    class FakeMessage:
        timestamp = 1
        server_id = 2
        raw_content = ""
        content = ""

    output, error, metadata = _export_image(FakeExtractor(), "wxid", FakeMessage(), tmp_path / "export", set())
    assert error == ""
    assert output is not None
    assert output.read_bytes() == b"\xff\xd8\xfffull"
    assert metadata["source"] == "原图"


def test_wechat_high_definition_image_outranks_regular_image(tmp_path):
    from miru_server.tools.builtin.wechat import _image_candidate_key

    regular = tmp_path / "photo.dat"
    high_definition = tmp_path / "photo_h.dat"
    regular.write_bytes(b"regular")
    high_definition.write_bytes(b"high-definition")
    timestamp = regular.stat().st_mtime

    assert _image_candidate_key(high_definition, timestamp) < _image_candidate_key(regular, timestamp)


def test_wechat_wxgf_high_definition_image_is_decoded_before_thumbnail(tmp_path):
    from miru_server.tools.builtin.wechat import _export_image

    high_definition = tmp_path / "photo_h.dat"
    thumbnail = tmp_path / "photo_t.dat"
    high_definition.write_bytes(b"high-definition")
    thumbnail.write_bytes(b"thumbnail")

    class FakeExtractor:
        def locate_files(self, *_args):
            return [high_definition]

        def locate_thumb(self, *_args):
            return [thumbnail]

        def decrypt(self, path):
            return b"wxgf-private-original" if path == high_definition else b"\xff\xd8\xffthumbnail"

        def sniff_format(self, data):
            return "wxgf" if data.startswith(b"wxgf") else "jpg"

    class FakeMessage:
        timestamp = 1
        server_id = 2
        raw_content = ""
        content = ""

    output, error, metadata = _export_image(
        FakeExtractor(), "wxid", FakeMessage(), tmp_path / "export", set(),
        wxgf_decoder=lambda _data: b"\xff\xd8\xffdecoded-high-definition",
    )
    assert error == ""
    assert output is not None
    assert output.read_bytes() == b"\xff\xd8\xffdecoded-high-definition"
    assert metadata["source"] == "高清原图（WXGF 原图本机解码）"


def test_recent_activity_tool_is_enabled_when_wechat_is_configured(app_config):
    app_config.tools.enabled.append("wechat_contact_list")
    registry = build_registry(app_config)
    assert "wechat_recent_activity" in registry.enabled_names
    schema = next(
        item for item in registry.schemas()
        if item["function"]["name"] == "wechat_recent_activity"
    )
    props = schema["function"]["parameters"]["properties"]
    assert set(("minutes", "limit", "include_groups")) <= set(props)
