from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from miru_node.client import reconnect_delay
from miru_node.config import NodeClientConfig
from miru_node.credentials import load_token, protect_token
from miru_node.journal import JobJournal
from miru_server.config import HomeNodeConfig
from miru_server.main import create_app
from miru_server.node_registry import HomeNodeRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]


def _cloud_config(app_config):
    values = app_config.model_dump()
    values["profile"] = "cloud"
    values["server"]["token"] = "test-token"
    values["llm"]["api_key"] = "test-key"
    values["stt"]["engine"] = "none"
    values["home_node"] = {
        "enabled": True,
        "node_id": "node-home",
        "token": "node-test-token-with-at-least-32-characters",
        "allowed_capabilities": ["test.echo"],
        "heartbeat_interval_s": 20,
        "stale_after_s": 30,
        "offline_after_s": 60,
    }
    return type(app_config).model_validate(values)


def _hello(**overrides):
    value = {
        "type": "node.hello",
        "protocol_version": 1,
        "node_id": "node-home",
        "device_token": "node-test-token-with-at-least-32-characters",
        "client_instance_id": "instance-12345678",
        "capabilities": ["test.echo", "unknown.capability"],
        "last_completed_job_ids": [],
    }
    value.update(overrides)
    return value


def test_registry_online_stale_offline_transitions():
    clock = [100.0]
    cfg = HomeNodeConfig(
        enabled=True,
        token="x" * 32,
        stale_after_s=30,
        offline_after_s=60,
        allowed_capabilities=["test.echo"],
    )
    registry = HomeNodeRegistry(
        cfg,
        monotonic=lambda: clock[0],
        utcnow=lambda: datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    assert registry.snapshot().state == "offline"
    connection = registry.register(protocol_version=1, capabilities=["test.echo", "denied"])
    assert registry.snapshot().state == "online"
    assert registry.snapshot().capabilities == ("test.echo",)
    clock[0] += 31
    assert registry.snapshot().state == "stale"
    clock[0] += 30
    assert registry.snapshot().state == "offline"
    assert registry.heartbeat(connection) is True
    assert registry.snapshot().state == "online"
    registry.disconnect(connection)
    assert registry.snapshot().state == "stale"


def test_node_ws_auth_capability_filter_and_status(app_config):
    cfg = _cloud_config(app_config)
    with TestClient(create_app(cfg)) as client:
        before = client.get("/api/status", headers={"Authorization": "Bearer test-token"}).json()
        assert before["cloud"]["state"] == "ready"
        assert before["home_node"]["state"] == "offline"
        with client.websocket_connect("/ws/node") as websocket:
            websocket.send_text(json.dumps(_hello()))
            welcome = websocket.receive_json()
            assert welcome["type"] == "node.welcome"
            assert welcome["allowed_capabilities"] == ["test.echo"]
            online = client.get(
                "/api/status", headers={"Authorization": "Bearer test-token"}
            ).json()
            assert online["home_node"]["state"] == "online"
            assert online["home_node"]["capabilities"] == ["test.echo"]
            websocket.send_text(json.dumps({
                "type": "node.heartbeat",
                "protocol_version": 1,
                "node_id": "node-home",
            }))
            assert websocket.receive_json()["type"] == "node.heartbeat_ack"
        after = client.get("/api/status", headers={"Authorization": "Bearer test-token"}).json()
        assert after["home_node"]["state"] == "stale"
        assert after["cloud"]["state"] == "ready"


@pytest.mark.parametrize(
    ("override", "close_code"),
    [
        ({"device_token": "wrong-token"}, 4401),
        ({"node_id": "unknown-node"}, 4403),
        ({"protocol_version": 99}, 4400),
    ],
)
def test_node_ws_rejects_invalid_identity(app_config, override, close_code):
    cfg = _cloud_config(app_config)
    with TestClient(create_app(cfg)) as client:
        with client.websocket_connect("/ws/node") as websocket:
            websocket.send_text(json.dumps(_hello(**override)))
            with pytest.raises(WebSocketDisconnect) as exc:
                websocket.receive_json()
            assert exc.value.code == close_code


def test_node_client_config_is_wss_only_and_journal_is_bounded(tmp_path):
    with pytest.raises(ValueError):
        NodeClientConfig(
            cloud_url="ws://example.test/ws/node",
            token_path=str(tmp_path / "token"),
            journal_path=str(tmp_path / "journal.json"),
        )
    cfg = NodeClientConfig(
        cloud_url="wss://example.test",
        token_path=str(tmp_path / "token"),
        journal_path=str(tmp_path / "journal.json"),
    )
    assert cfg.cloud_url == "wss://example.test/ws/node"
    journal = JobJournal(cfg.journal_path, limit=3)
    for item in ["a", "b", "c", "d"]:
        journal.record_completed(item)
    assert journal.completed_ids() == ["b", "c", "d"]
    assert reconnect_delay(0, maximum=60) == 1
    assert reconnect_delay(20, maximum=60) == 60


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")
def test_node_token_dpapi_roundtrip_is_not_plaintext(tmp_path):
    token = "phase6-node-token-which-is-longer-than-32-characters"
    path = tmp_path / "home-node-token.dat"
    try:
        protect_token(token, path)
    except FileNotFoundError as exc:
        # Sandboxed CI accounts may not have a loaded CurrentUser DPAPI master
        # key. Production acceptance runs this same test in the real user
        # session, where failure is not skipped.
        if exc.winerror == 2:
            pytest.skip("CurrentUser DPAPI profile is unavailable in this sandbox")
        raise
    assert token.encode("utf-8") not in path.read_bytes()
    assert load_token(path) == token


def test_phase6_production_boundary_is_value_free_and_private():
    compose = (REPO_ROOT / "deploy/production/compose.production.yaml").read_text(encoding="utf-8")
    settings = (REPO_ROOT / "deploy/production/settings.production.yaml").read_text(encoding="utf-8")
    caddy = (REPO_ROOT / "deploy/production/Caddyfile.production").read_text(encoding="utf-8")
    assert "/run/secrets/home_node_token" in compose
    assert "MIRU_HOME_NODE_TOKEN=\"$$(cat /run/secrets/home_node_token)\"" in compose
    assert 'token: "${MIRU_HOME_NODE_TOKEN}"' in settings
    assert "/ws/node*" not in caddy
    assert "0.0.0.0:8765" not in compose
    assert '"127.0.0.1:18080:8080"' in compose
