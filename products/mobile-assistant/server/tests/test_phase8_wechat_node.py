from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from miru_node.client import HomeNodeClient
from miru_node.config import NodeClientConfig
from miru_node.wechat_adapter import WeChatAdapterError, WeChatNodeAdapter
from miru_server.config import HomeNodeConfig
from miru_server.node_registry import HomeNodeRegistry
from miru_server.node_rpc import HomeNodeRpc
from miru_server.main import create_app
from miru_server.tools.base import ToolContext
from miru_server.tools.builtin.wechat_node import WechatSearchMessagesNodeTool
from miru_server.tools.registry import ToolRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]


class _FakeReader:
    def __init__(self, _root: str):
        self.closed = False

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
        assert username == "wxid_private_value"
        return [("Msg_private_hash", "message/message_0.db", 3)]

    def read_messages_since(self, table: str, shard: str, since: int):
        assert table == "Msg_private_hash"
        assert shard == "message/message_0.db"
        assert since > 0
        return [
            SimpleNamespace(
                timestamp=1_800_000_001,
                sender_username="wxid_private_value",
                content="project keyword alpha",
            ),
            SimpleNamespace(
                timestamp=1_800_000_002,
                sender_username="self-secret-wxid",
                content="<?xml version='1.0'?><msg><img aeskey='must-not-leak'/></msg>",
            ),
            SimpleNamespace(
                timestamp=1_800_000_003,
                sender_username="self-secret-wxid",
                content="keyword " + "x" * 600,
            ),
        ]

    def close(self):
        self.closed = True


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


@pytest.mark.parametrize(
    ("contact", "error_code"),
    [("missing", "contact_not_found"), ("Test Group", "contact_scope_denied")],
)
def test_wechat_adapter_rejects_unknown_and_group_scope(contact, error_code):
    adapter = WeChatNodeAdapter(reader_factory=_FakeReader)
    with pytest.raises(WeChatAdapterError) as exc:
        adapter.search_messages(contact=contact, keyword="keyword")
    assert exc.value.error_code == error_code
    assert "wxid" not in exc.value.message


@pytest.mark.asyncio
async def test_node_client_executes_only_allowlisted_wechat_search(tmp_path, monkeypatch):
    config = NodeClientConfig(
        cloud_url="wss://example.test/ws/node",
        token_path=str(tmp_path / "token"),
        journal_path=str(tmp_path / "journal.json"),
        capabilities=["home_node_ping", "wechat_search_messages"],
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


def test_phase8_production_allowlist_contains_only_read_capability():
    settings = (REPO_ROOT / "deploy/production/settings.production.yaml").read_text(
        encoding="utf-8"
    )
    installer = (
        REPO_ROOT / "products/mobile-assistant/server/scripts/install_home_node_task.ps1"
    ).read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / "deploy/Dockerfile.phase8-overlay").read_text(encoding="utf-8")
    assert settings.count("- wechat_search_messages") == 2
    assert "  - wechat_search_messages" in installer
    assert "wechat_max_days: 90" in installer
    assert "wechat_max_results: 20" in installer
    for forbidden in ["wechat_recent_messages", "wechat_transcribe_voice", "wechat_image_analysis"]:
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
