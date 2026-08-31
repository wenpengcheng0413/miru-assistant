from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from miru_node.client import HomeNodeClient
from miru_node.config import NodeClientConfig
from miru_node.journal import JobJournal
from miru_server.config import HomeNodeConfig
from miru_server.node_registry import HomeNodeRegistry
from miru_server.node_rpc import HomeNodeRpc, NodeRpcError
from miru_server.tools.base import ToolContext
from miru_server.tools.builtin.home_node import HomeNodePingTool
from miru_server.tools.registry import ToolRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]


def _online_registry() -> tuple[HomeNodeRegistry, str]:
    registry = HomeNodeRegistry(HomeNodeConfig(
        enabled=True,
        token="x" * 32,
        allowed_capabilities=["home_node_ping"],
    ))
    connection_id = registry.register(
        protocol_version=1,
        capabilities=["home_node_ping"],
    )
    return registry, connection_id


@pytest.mark.asyncio
async def test_rpc_success_and_late_result_is_discarded():
    registry, connection_id = _online_registry()
    rpc = HomeNodeRpc(registry)
    sent: list[dict] = []

    async def send(payload: dict) -> None:
        sent.append(payload)

    await rpc.attach(connection_id, send)
    pending = asyncio.create_task(rpc.execute(
        "home_node_ping", {}, timeout_s=1, job_id="job-success",
    ))
    await asyncio.sleep(0)
    assert sent[0]["type"] == "job.request"
    assert sent[0]["job_id"] == "job-success"
    assert rpc.accept_result(connection_id, {
        "type": "job.result",
        "job_id": "job-success",
        "result": {"ok": True, "data": {"state": "ok"}},
    }) is True
    assert (await pending)["data"]["state"] == "ok"
    assert rpc.accept_result(connection_id, {
        "type": "job.result",
        "job_id": "job-success",
        "result": {"ok": True},
    }) is False


@pytest.mark.asyncio
async def test_rpc_timeout_sends_cancel_and_disconnect_fails_pending():
    registry, connection_id = _online_registry()
    rpc = HomeNodeRpc(registry)
    sent: list[dict] = []

    async def send(payload: dict) -> None:
        sent.append(payload)

    await rpc.attach(connection_id, send)
    with pytest.raises(NodeRpcError) as timeout:
        await rpc.execute("home_node_ping", {}, timeout_s=0.01, job_id="job-timeout")
    assert timeout.value.error_code == "node_timeout"
    assert [item["type"] for item in sent] == ["job.request", "job.cancel"]

    pending = asyncio.create_task(rpc.execute(
        "home_node_ping", {}, timeout_s=1, job_id="job-disconnect",
    ))
    await asyncio.sleep(0)
    await rpc.detach(connection_id)
    with pytest.raises(NodeRpcError) as disconnected:
        await pending
    assert disconnected.value.error_code == "node_disconnected"


@pytest.mark.asyncio
async def test_ping_tool_and_dynamic_schema_follow_node_state():
    registry, connection_id = _online_registry()
    rpc = HomeNodeRpc(registry)
    tool_registry = ToolRegistry(
        [HomeNodePingTool],
        enabled=["home_node_ping"],
        profile="cloud",
    )
    tool_registry.bind_home_node(registry)
    assert tool_registry.enabled_names == ["home_node_ping"]

    async def send(payload: dict) -> None:
        rpc.accept_result(connection_id, {
            "type": "job.result",
            "job_id": payload["job_id"],
            "result": {"ok": True, "data": {"state": "ok", "protocol_version": 1}},
        })

    await rpc.attach(connection_id, send)
    services = SimpleNamespace(node_rpc=rpc)
    result = await tool_registry.execute(
        ToolContext(services=services, conversation_id="c", turn_id="turn-1"),
        "home_node_ping",
        {},
    )
    assert result.ok is True
    assert result.data["state"] == "ok"

    await rpc.detach(connection_id)
    registry.disconnect(connection_id)
    assert tool_registry.enabled_names == []


@pytest.mark.asyncio
async def test_node_ping_executor_is_fixed_and_value_free(tmp_path):
    config = NodeClientConfig(
        cloud_url="wss://example.test/ws/node",
        token_path=str(tmp_path / "token"),
        journal_path=str(tmp_path / "journal.json"),
        capabilities=["home_node_ping"],
    )
    client = HomeNodeClient(config)
    result = await client._run_job({"tool": "home_node_ping", "args": {}})
    assert result["ok"] is True
    assert result["data"]["node_id"] == "node-home"
    assert result["data"]["protocol_version"] == 1
    denied = await client._run_job({"tool": "shell", "args": {"command": "whoami"}})
    assert denied["ok"] is False
    assert denied["error_code"] == "node_capability_unavailable"


def test_journal_persists_bounded_results_and_replays_duplicates(tmp_path):
    journal = JobJournal(tmp_path / "journal.json", limit=2)
    journal.record_result("one", {"ok": True, "data": {"value": 1}})
    journal.record_result("two", {"ok": True, "data": {"value": 2}})
    journal.record_result("three", {"ok": True, "data": {"value": 3}})
    assert journal.completed_ids() == ["two", "three"]
    assert journal.get_result("one") is None
    assert journal.get_result("three")["data"]["value"] == 3


def test_phase7_production_capability_is_explicitly_allowlisted():
    settings = (REPO_ROOT / "deploy/production/settings.production.yaml").read_text(
        encoding="utf-8"
    )
    installer = (
        REPO_ROOT / "products/mobile-assistant/server/scripts/install_home_node_task.ps1"
    ).read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / "deploy/Dockerfile.phase7-overlay").read_text(encoding="utf-8")
    assert settings.count("- home_node_ping") == 2
    assert "capabilities:\n  - home_node_ping" in installer
    assert "  - shell\n" not in installer.lower()
    for path in [
        "miru_server/node_rpc.py",
        "miru_server/api/node_ws.py",
        "miru_server/tools/registry.py",
        "miru_server/tools/builtin/home_node.py",
    ]:
        assert path in dockerfile
