from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from miru_node.client import HomeNodeClient
from miru_node.config import NodeClientConfig
from miru_node.wechat_adapter import WeChatAdapterError, WeChatNodeAdapter
from miru_server.config import HomeNodeConfig
from miru_server.node_registry import HomeNodeRegistry
from miru_server.node_rpc import HomeNodeRpc
from miru_server.main import create_app
from miru_server.tools.base import ToolContext
from miru_server.tools.builtin.wechat_node import (
    WechatConversationMessagesNodeTool,
    WechatOriginalImagesNodeTool,
    WechatSearchMessagesNodeTool,
    WechatTranscribeVoiceNodeTool,
)
from miru_server.tools.registry import ToolRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]


class _FakeReader:
    def __init__(self, _root: str):
        self.closed = False
        self.account_dir = "fake-account"

    def get_contacts(self):
        return [
            {
                "username": "wxid_private_value",
                "alias": "alice-id",
                "remark": "Alice",
                "nickname": "Alice Nick",
                "display_name": "Alice",
            },
            {
                "username": "group@chatroom",
                "alias": "",
                "remark": "Test Group",
                "nickname": "",
                "display_name": "Test Group",
            },
        ]

    def find_direct_session_tables(self, username: str):
        if username == "wxid_private_value":
            return [("Msg_private_hash", "message/message_0.db", 3)]
        assert username == "group@chatroom"
        return [("Msg_group_hash", "message/message_1.db", 3)]

    def read_messages_since(self, table: str, shard: str, since: int):
        assert since > 0
        if table == "Msg_group_hash":
            assert shard == "message/message_1.db"
            return [
                SimpleNamespace(
                    timestamp=1_800_000_004,
                    server_id=4,
                    sender_username="member-private-wxid",
                    sender="Group Member",
                    msg_type=1,
                    content="group alpha",
                ),
                SimpleNamespace(
                    timestamp=1_800_000_005,
                    server_id=5,
                    sender_username="unresolved-private-wxid",
                    sender="wxid_must_not_leak",
                    msg_type=3,
                    content="[图片]",
                    raw_content="<img md5='0123456789abcdef0123456789abcdef'/>",
                ),
                SimpleNamespace(
                    timestamp=1_800_000_006,
                    server_id=6,
                    sender_username="self-secret-wxid",
                    sender="我",
                    msg_type=34,
                    content="[语音] (时长 3s)",
                ),
            ]
        assert table == "Msg_private_hash"
        assert shard == "message/message_0.db"
        return [
            SimpleNamespace(
                timestamp=1_800_000_001,
                server_id=1,
                msg_type=1,
                sender="Alice",
                sender_username="wxid_private_value",
                content="project keyword alpha",
            ),
            SimpleNamespace(
                timestamp=1_800_000_002,
                server_id=2,
                msg_type=3,
                sender="wxid_self_must_not_leak",
                sender_username="self-secret-wxid",
                content="<?xml version='1.0'?><msg><img aeskey='must-not-leak'/></msg>",
            ),
            SimpleNamespace(
                timestamp=1_800_000_003,
                server_id=3,
                msg_type=1,
                sender="wxid_self_must_not_leak",
                sender_username="self-secret-wxid",
                content="keyword " + "x" * 600,
            ),
        ]

    def close(self):
        self.closed = True


class _FakeVoiceExtractor:
    def __init__(self, _db):
        pass

    def iter_voice_ids(self, server_ids):
        return {server_id: b"fake-silk" for server_id in server_ids}

    def decode_to_pcm_cached(self, _server_id, _silk):
        return b"\x00\x00" * 1600


class _FakeStt:
    def transcribe(self, pcm, sample_rate):
        assert pcm
        assert sample_rate == 16000
        return "本机转写结果"


class _FakeImageExtractor:
    def __init__(self, _account_dir):
        pass

    def locate_files(self, _username, _timestamp, md5):
        return [Path(f"{md5}_h.dat")]

    def decrypt(self, _path):
        return b"\xff\xd8\xff" + b"image-bytes"

    def sniff_format(self, _data):
        return "jpg"


def test_wechat_adapter_is_exact_bounded_and_value_scoped():
    adapter = WeChatNodeAdapter(
        reader_factory=_FakeReader,
        max_days=90,
        max_results=2,
    )
    result = adapter.search_messages(
        contact="Alice",
        keyword="keyword",
        days=365,
        limit=99,
    )
    assert result["contact"] == "Alice"
    assert result["days"] == 90
    assert result["total_hits"] == 2
    assert len(result["samples"]) == 2
    assert result["samples"][0]["sender"] == "contact"
    assert result["samples"][1]["sender"] == "self"
    assert len(result["samples"][1]["content"]) <= 301
    encoded = str(result)
    assert "wxid_private_value" not in encoded
    assert "self-secret-wxid" not in encoded
    assert "message_0.db" not in encoded
    assert "aeskey" not in encoded


@pytest.mark.parametrize(("contact", "error_code"), [("missing", "contact_not_found")])
def test_wechat_adapter_rejects_unknown_and_group_scope(contact, error_code):
    adapter = WeChatNodeAdapter(reader_factory=_FakeReader)
    with pytest.raises(WeChatAdapterError) as exc:
        adapter.search_messages(contact=contact, keyword="keyword")
    assert exc.value.error_code == error_code
    assert "wxid" not in exc.value.message


def test_wechat_conversation_pages_group_without_identifiers_or_paths():
    adapter = WeChatNodeAdapter(reader_factory=_FakeReader, max_results=2)
    first = adapter.conversation_messages(contact="Test Group", days=30, limit=99)
    assert first["conversation_type"] == "group"
    assert len(first["messages"]) == 2
    assert first["messages"][0]["sender"] == "group_member"
    assert first["messages"][0]["message_type"] == "image"
    assert first["messages"][1]["sender"] == "self"
    assert first["messages"][1]["message_type"] == "voice"
    assert first["has_more"] is True
    assert first["next_cursor"]

    second = adapter.conversation_messages(
        contact="Test Group",
        days=30,
        limit=2,
        cursor=first["next_cursor"],
    )
    assert [m["sender"] for m in second["messages"]] == ["Group Member"]
    assert second["has_more"] is False
    assert second["next_cursor"] == ""
    encoded = str(first) + str(second)
    assert "wxid_" not in encoded
    assert "message_1.db" not in encoded


def test_wechat_conversation_rejects_cursor_from_another_scope():
    adapter = WeChatNodeAdapter(reader_factory=_FakeReader, max_results=2)
    first = adapter.conversation_messages(contact="Test Group", days=30, limit=1)
    with pytest.raises(WeChatAdapterError) as exc:
        adapter.conversation_messages(
            contact="Alice",
            days=30,
            cursor=first["next_cursor"],
        )
    assert exc.value.error_code == "invalid_cursor"


def test_wechat_voice_is_transcribed_locally_without_raw_media_or_ids():
    adapter = WeChatNodeAdapter(
        reader_factory=_FakeReader,
        voice_extractor_factory=_FakeVoiceExtractor,
        stt_factory=lambda _model_dir: _FakeStt(),
    )
    result = adapter.transcribe_voice(contact="Test Group", days=30, limit=10)
    assert result["conversation_type"] == "group"
    assert result["transcribed"] == 1
    assert result["voice_messages"][0]["sender"] == "self"
    assert result["voice_messages"][0]["transcript"] == "本机转写结果"
    assert result["voice_messages"][0]["error"] == ""
    encoded = str(result)
    assert "fake-silk" not in encoded
    assert "server_id" not in encoded
    assert "wxid" not in encoded


def test_wechat_original_image_extracts_only_exact_reference():
    adapter = WeChatNodeAdapter(
        reader_factory=_FakeReader,
        image_extractor_factory=_FakeImageExtractor,
    )
    result = adapter.extract_original_images(contact="Test Group", days=30, limit=3)
    assert len(result["images"]) == 1
    image = result["images"][0]
    assert image["media_type"] == "image/jpeg"
    assert image["_bytes"].startswith(b"\xff\xd8\xff")
    assert image["_extension"] == ".jpg"


def test_wechat_original_image_prefers_high_definition_and_falls_back_without_md5(tmp_path):
    regular = tmp_path / "candidate.dat"
    high = tmp_path / "candidate_h.dat"
    thumb = tmp_path / "candidate_t.dat"
    for path in (regular, high, thumb):
        path.write_bytes(b"dat")

    class Reader(_FakeReader):
        def read_messages_since(self, table: str, shard: str, since: int):
            return [SimpleNamespace(
                timestamp=int(high.stat().st_mtime),
                server_id=9,
                sender_username="self-secret-wxid",
                sender="我",
                msg_type=3,
                content="[图片]",
                raw_content="",
            )]

    class Extractor:
        def __init__(self, _account_dir):
            pass

        def locate_files(self, *_args):
            return [regular, high]

        def locate_thumb(self, *_args):
            return [thumb]

        def decrypt(self, path):
            return b"\xff\xd8\xff" + path.stem.encode()

        def sniff_format(self, _data):
            return "jpg"

    result = WeChatNodeAdapter(
        reader_factory=Reader,
        image_extractor_factory=Extractor,
    ).extract_original_images(contact="Test Group", days=30, limit=1)
    image = result["images"][0]
    assert image["_bytes"] == b"\xff\xd8\xffcandidate_h"
    assert image["match"].endswith("high_definition")


@pytest.mark.asyncio
async def test_cloud_analyzes_relayed_original_image(app_config, tmp_path):
    media_id = "a" * 32
    root = app_config.resolve(app_config.attachments.dir) / "node-media"
    root.mkdir(parents=True)
    image_path = root / f"{media_id}.png"
    Image.new("RGB", (32, 24), "white").save(image_path)
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    (root / f"{media_id}.json").write_text(json.dumps({
        "conversation_id": "conversation-1",
        "file_name": image_path.name,
        "expires_at": expires.isoformat(),
    }), encoding="utf-8")

    class Rpc:
        async def execute(self, *_args, **_kwargs):
            return {"ok": True, "data": {"images": [{
                "id": media_id,
                "download_path": f"/api/node-media/{media_id}",
            }]}}

    class Llm:
        async def vision_chat(self, messages, **_kwargs):
            assert any(
                block.get("type") == "image_url"
                for block in messages[0]["content"]
            )
            return "图片里是一段可确认的测试内容"

    services = SimpleNamespace(config=app_config, node_rpc=Rpc(), llm=Llm())
    result = await WechatOriginalImagesNodeTool().run(
        ToolContext(services=services, conversation_id="conversation-1"),
        contact="Test Group",
    )
    assert result.ok is True
    assert result.data["analyzed"] == 1
    assert result.data["images"][0]["description"] == "图片里是一段可确认的测试内容"


@pytest.mark.asyncio
async def test_node_client_executes_only_allowlisted_wechat_search(tmp_path, monkeypatch):
    config = NodeClientConfig(
        cloud_url="wss://example.test/ws/node",
        token_path=str(tmp_path / "token"),
        journal_path=str(tmp_path / "journal.json"),
        capabilities=[
            "home_node_ping",
            "wechat_conversation_messages",
            "wechat_search_messages",
            "wechat_transcribe_voice",
            "wechat_original_images",
        ],
    )
    client = HomeNodeClient(config)
    monkeypatch.setattr(
        WeChatNodeAdapter,
        "search_messages",
        lambda self, **kwargs: {"total_hits": 1, "samples": [], **kwargs},
    )
    result = await client._run_job({
        "tool": "wechat_search_messages",
        "args": {"contact": "Alice", "keyword": "keyword", "days": 7, "limit": 3},
    })
    assert result["ok"] is True
    assert result["data"]["total_hits"] == 1
    monkeypatch.setattr(
        WeChatNodeAdapter,
        "conversation_messages",
        lambda self, **kwargs: {"messages": [], "has_more": False, **kwargs},
    )
    page = await client._run_job({
        "tool": "wechat_conversation_messages",
        "args": {"contact": "Test Group", "days": 7, "limit": 3, "cursor": ""},
    })
    assert page["ok"] is True
    assert page["data"]["contact"] == "Test Group"
    monkeypatch.setattr(
        WeChatNodeAdapter,
        "transcribe_voice",
        lambda self, **kwargs: {"voice_messages": [], "transcribed": 0, **kwargs},
    )
    voice = await client._run_job({
        "tool": "wechat_transcribe_voice",
        "args": {"contact": "Test Group", "days": 7, "limit": 1, "cursor": ""},
    })
    assert voice["ok"] is True
    monkeypatch.setattr(
        WeChatNodeAdapter,
        "extract_original_images",
        lambda self, **kwargs: {
            "images": [{
                "time": "2026-08-31T00:00:00+00:00",
                "sender": "self",
                "media_type": "image/jpeg",
                "size_bytes": 10,
                "error": "",
                "_bytes": b"private-image",
                "_extension": ".jpg",
            }],
            **kwargs,
        },
    )
    monkeypatch.setattr(
        client,
        "_upload_node_media",
        lambda *args, **kwargs: {
            "id": "a" * 32,
            "download_path": "/api/node-media/" + "a" * 32,
            "expires_at": "2026-09-01T00:00:00+00:00",
        },
    )
    media = await client._run_job({
        "tool": "wechat_original_images",
        "args": {
            "contact": "Test Group",
            "days": 7,
            "limit": 1,
            "cursor": "",
            "conversation_id": "conversation-1",
        },
    })
    assert media["ok"] is True
    assert media["data"]["images"][0]["download_path"].startswith("/api/node-media/")
    assert all("_bytes" not in item for item in media["data"]["images"])
    assert "private-image" not in str(media)
    denied = await client._run_job({"tool": "wechat_recent_messages", "args": {}})
    assert denied["error_code"] == "node_capability_unavailable"


@pytest.mark.asyncio
async def test_cloud_proxy_routes_bounded_wechat_job():
    registry = HomeNodeRegistry(HomeNodeConfig(
        enabled=True,
        token="x" * 32,
        allowed_capabilities=["wechat_search_messages"],
    ))
    connection_id = registry.register(
        protocol_version=1,
        capabilities=["wechat_search_messages"],
    )
    rpc = HomeNodeRpc(registry)
    tool_registry = ToolRegistry(
        [WechatSearchMessagesNodeTool],
        enabled=["wechat_search_messages"],
        profile="cloud",
    )
    tool_registry.bind_home_node(registry)

    async def send(payload: dict) -> None:
        assert payload["tool"] == "wechat_search_messages"
        assert payload["args"] == {
            "contact": "Alice", "keyword": "keyword", "days": 7, "limit": 2,
        }
        rpc.accept_result(connection_id, {
            "job_id": payload["job_id"],
            "result": {"ok": True, "data": {"total_hits": 1, "samples": []}},
        })

    await rpc.attach(connection_id, send)
    services = SimpleNamespace(node_rpc=rpc)
    result = await tool_registry.execute(
        ToolContext(services=services, conversation_id="c", turn_id="turn"),
        "wechat_search_messages",
        {"contact": "Alice", "keyword": "keyword", "days": 7, "limit": 2},
    )
    assert result.ok is True
    assert result.data["total_hits"] == 1


@pytest.mark.asyncio
async def test_cloud_proxy_routes_conversation_page():
    registry = HomeNodeRegistry(HomeNodeConfig(
        enabled=True,
        token="x" * 32,
        allowed_capabilities=["wechat_conversation_messages"],
    ))
    connection_id = registry.register(
        protocol_version=1,
        capabilities=["wechat_conversation_messages"],
    )
    rpc = HomeNodeRpc(registry)
    tool_registry = ToolRegistry(
        [WechatConversationMessagesNodeTool],
        enabled=["wechat_conversation_messages"],
        profile="cloud",
    )
    tool_registry.bind_home_node(registry)

    async def send(payload: dict) -> None:
        assert payload["tool"] == "wechat_conversation_messages"
        rpc.accept_result(connection_id, {
            "job_id": payload["job_id"],
            "result": {"ok": True, "data": {"messages": [], "has_more": False}},
        })

    await rpc.attach(connection_id, send)
    services = SimpleNamespace(node_rpc=rpc)
    result = await tool_registry.execute(
        ToolContext(services=services, conversation_id="c", turn_id="page-turn"),
        "wechat_conversation_messages",
        {"contact": "Test Group", "days": 7, "limit": 2, "cursor": ""},
    )
    assert result.ok is True


def test_phase8_production_allowlist_contains_only_read_capability():
    settings = (REPO_ROOT / "deploy/production/settings.production.yaml").read_text(
        encoding="utf-8"
    )
    installer = (
        REPO_ROOT / "products/mobile-assistant/server/scripts/install_home_node_task.ps1"
    ).read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / "deploy/Dockerfile.phase8-overlay").read_text(encoding="utf-8")
    assert settings.count("- wechat_search_messages") == 2
    assert settings.count("- wechat_conversation_messages") == 2
    assert "  - wechat_search_messages" in installer
    assert "  - wechat_conversation_messages" in installer
    assert "wechat_max_days: 90" in installer
    assert "wechat_max_results: 20" in installer
    assert settings.count("- wechat_transcribe_voice") == 2
    assert settings.count("- wechat_original_images") == 2
    assert "  - wechat_transcribe_voice" in installer
    assert "  - wechat_original_images" in installer
    assert "wechat_stt_model_dir: \"./data/models/sensevoice\"" in installer
    for forbidden in ["wechat_recent_messages", "wechat_image_analysis"]:
        assert f"  - {forbidden}" not in installer
    assert "miru_server/config.py" in dockerfile
    assert "miru_server/api/rest.py" in dockerfile
    assert "miru_server/tools/registry.py" in dockerfile
    assert "miru_server/tools/builtin/wechat_node.py" in dockerfile


def test_status_marks_underscore_wechat_capability_available(app_config):
    values = app_config.model_dump()
    values["profile"] = "cloud"
    values["server"]["token"] = "test-token"
    values["llm"]["api_key"] = "test-key"
    values["stt"]["engine"] = "none"
    values["tools"]["enabled"] = ["wechat_search_messages"]
    values["home_node"] = {
        "enabled": True,
        "node_id": "node-home",
        "token": "node-test-token-with-at-least-32-characters",
        "allowed_capabilities": ["wechat_search_messages"],
        "heartbeat_interval_s": 20,
        "stale_after_s": 30,
        "offline_after_s": 60,
    }
    cfg = type(app_config).model_validate(values)
    with TestClient(create_app(cfg)) as client:
        with client.websocket_connect("/ws/node") as websocket:
            websocket.send_json({
                "type": "node.hello",
                "protocol_version": 1,
                "node_id": "node-home",
                "device_token": "node-test-token-with-at-least-32-characters",
                "client_instance_id": "phase8-instance",
                "capabilities": ["wechat_search_messages"],
                "last_completed_job_ids": [],
            })
            assert websocket.receive_json()["type"] == "node.welcome"
            status = client.get(
                "/api/status", headers={"Authorization": "Bearer test-token"}
            ).json()
            assert status["capabilities"]["wechat"] == "available"


def test_node_media_relay_is_separately_authenticated_and_downloadable(app_config, tmp_path):
    values = app_config.model_dump()
    values["profile"] = "cloud"
    values["server"]["token"] = "app-test-token"
    values["llm"]["api_key"] = "test-key"
    values["stt"]["engine"] = "none"
    values["attachments"]["dir"] = str(tmp_path / "attachments")
    values["tools"]["enabled"] = ["wechat_original_images"]
    values["home_node"] = {
        "enabled": True,
        "node_id": "node-home",
        "token": "node-test-token-with-at-least-32-characters",
        "allowed_capabilities": ["wechat_original_images"],
        "heartbeat_interval_s": 20,
        "stale_after_s": 30,
        "offline_after_s": 60,
    }
    cfg = type(app_config).model_validate(values)
    app_headers = {"Authorization": "Bearer app-test-token"}
    node_headers = {"Authorization": "Bearer node-test-token-with-at-least-32-characters"}
    with TestClient(create_app(cfg)) as client:
        conversation_id = client.post(
            "/api/conversations", json={"persona": "miru"}, headers=app_headers
        ).json()["id"]
        denied = client.post(
            "/api/node/media",
            content=b"\xff\xd8\xffprivate",
            headers={
                "Authorization": "Bearer wrong",
                "X-Miru-Conversation-Id": conversation_id,
                "X-Miru-Image-Ext": ".jpg",
            },
        )
        assert denied.status_code == 401
        uploaded = client.post(
            "/api/node/media",
            content=b"\xff\xd8\xffprivate",
            headers={
                **node_headers,
                "X-Miru-Conversation-Id": conversation_id,
                "X-Miru-Image-Ext": ".jpg",
            },
        )
        assert uploaded.status_code == 200
        media = uploaded.json()
        assert media["download_path"].startswith("/api/node-media/")
        assert "sha256" not in media
        assert client.get(media["download_path"]).status_code == 401
        downloaded = client.get(media["download_path"], headers=app_headers)
        assert downloaded.status_code == 200
        assert downloaded.content == b"\xff\xd8\xffprivate"
        listed = client.get(
            f"/api/conversations/{conversation_id}/node-media", headers=app_headers
        ).json()["items"]
        assert len(listed) == 1
