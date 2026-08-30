"""Phase 1 cloud-profile acceptance tests; all provider calls are mocked/offline."""
from __future__ import annotations

import json
import logging
import builtins
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from miru_server.attachments import AttachmentStorage
from miru_server.config import AppConfig
from miru_server.core.llm import LLMClient
from miru_server.db.database import init_db
from miru_server.db.migrations import LATEST_SCHEMA_VERSION, apply_migrations, schema_version
from miru_server.main import create_app
from miru_server.services import create_services
from miru_server.tools.base import Tool, ToolContext, ToolResult
from miru_server.tools.registry import ToolRegistry, build_registry


def _cloud_config(app_config: AppConfig, **overrides) -> AppConfig:
    values = app_config.model_dump(exclude={"config_dir", "project_dir"})
    values["profile"] = "cloud"
    values["server"]["advertise_lan"] = True
    values["stt"] = {"engine": "sensevoice"}
    values["tts"] = {"provider": "minimax", "minimax": {"api_key": ""}}
    values["tools"]["enabled"] = ["get_current_time", "wechat_chat_stats"]
    values.update(overrides)
    cfg = AppConfig.model_validate(values)
    cfg.config_dir = app_config.config_dir
    cfg.project_dir = app_config.project_dir
    return cfg


def test_cloud_profile_is_dependency_light_and_minimax_optional(app_config):
    cfg = _cloud_config(app_config)
    assert cfg.profile == "cloud"
    assert cfg.server.advertise_lan is False
    assert cfg.stt.engine == "none"
    assert not any(name.startswith("wechat_") for name in cfg.tools.enabled)

    services = create_services(cfg)
    assert services.stt.name == "none"
    assert services.tts_provider is None
    assert not any(name.startswith("wechat_") for name in services.tools.enabled_names)


def test_cloud_startup_does_not_import_windows_or_local_ai_dependencies(app_config, monkeypatch):
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        blocked = ("miru.chat_analyzer", "pymem", "pysilk", "sherpa_onnx", "faster_whisper", "zeroconf")
        if name == "miru" or name.startswith(blocked):
            raise ImportError(f"blocked dependency in cloud test: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    cfg = _cloud_config(app_config)
    with TestClient(create_app(cfg)) as client:
        assert client.get("/healthz").status_code == 200


def test_cloud_startup_without_token_fails_closed(app_config):
    cfg = _cloud_config(app_config)
    cfg.server.token = ""
    with pytest.raises(RuntimeError, match="MIRU_SERVER_TOKEN"):
        with TestClient(create_app(cfg)):
            pass


def test_profile_environment_override_is_explicit(tmp_path: Path, monkeypatch):
    config = tmp_path / "settings.yaml"
    config.write_text(
        "server:\n  token: token\nllm:\n  api_key: key\nstt:\n  engine: sensevoice\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MIRU_PROFILE", "cloud")
    loaded = AppConfig.load(config)
    assert loaded.profile == "cloud"
    assert loaded.stt.engine == "none"
    assert loaded.server.advertise_lan is False


def test_cloud_health_ready_status_and_auth(app_config):
    cfg = _cloud_config(app_config)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(create_app(cfg)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["checks"] == {"config": True, "sqlite": True, "services": True}

        assert client.get("/api/status").status_code == 401
        response = client.get("/api/status", headers=headers)
        assert response.status_code == 200
        status = response.json()
        assert status["cloud"]["profile"] == "cloud"
        assert status["home_node"]["state"] == "not_configured"
        assert status["capabilities"]["wechat"] == "unavailable"
        assert status["capabilities"]["gpu"] == "unavailable"
        assert status["capabilities"]["voice_reason"] == "provider_not_configured"
        serialized = json.dumps(status, ensure_ascii=False)
        assert "E:\\" not in serialized
        assert "api_key" not in serialized.lower()
        assert "token" not in serialized.lower()


def test_cloud_websocket_auth_fail_closed(app_config):
    cfg = _cloud_config(app_config)
    with TestClient(create_app(cfg)) as client:
        with client.websocket_connect("/ws/session") as websocket:
            websocket.send_text(json.dumps({"type": "hello", "token": "wrong"}))
            with pytest.raises(WebSocketDisconnect) as exc:
                websocket.receive_text()
            assert exc.value.code == 4401

        with client.websocket_connect("/ws/session") as websocket:
            websocket.send_text(json.dumps({"type": "hello", "token": "test-token"}))
            hello = json.loads(websocket.receive_text())
            assert hello["type"] == "hello_ok"


def test_cloud_cors_is_not_wildcard(app_config):
    cfg = _cloud_config(app_config)
    cfg.server.cors_origins = ["*"]
    cfg.model_post_init(None)
    app = create_app(cfg)
    middleware = next(item for item in app.user_middleware if item.cls is CORSMiddleware)
    assert middleware.kwargs["allow_origins"] == []
    assert "*" not in middleware.kwargs["allow_methods"]
    assert "*" not in middleware.kwargs["allow_headers"]


class _CloudTool(Tool):
    name = "cloud_probe"
    description = "test cloud tool"

    async def run(self, ctx: ToolContext, **kwargs) -> ToolResult:
        return ToolResult.success({"ok": True})


class _HomeTool(Tool):
    name = "wechat_probe"
    description = "test home tool"

    async def run(self, ctx: ToolContext, **kwargs) -> ToolResult:
        raise AssertionError("Home Node tool must not execute in cloud")


def test_tool_router_metadata_and_cloud_boundary():
    registry = ToolRegistry([_CloudTool, _HomeTool], ["cloud_probe", "wechat_probe"], profile="cloud")
    assert registry.schemas()[0]["function"]["name"] == "cloud_probe"
    home_listing = next(item for item in registry.list_all() if item["name"] == "wechat_probe")
    assert home_listing["enabled"] is False
    assert home_listing["execution_location"] == "node-home"
    result = asyncio_run(
        registry.execute(ToolContext(SimpleNamespace(), conversation_id="test"), "wechat_probe", {})
    )
    assert result.error_code == "node_not_configured"
    assert result.retryable is False
    assert "error_code" in result.to_llm()


def asyncio_run(awaitable):
    """Small local helper keeps this module independent of pytest-asyncio APIs."""
    import asyncio

    return asyncio.run(awaitable)


def test_cloud_registry_has_no_wechat_schema(app_config):
    registry = build_registry(_cloud_config(app_config))
    assert not any(name.startswith("wechat_") for name in registry.enabled_names)
    assert not any(item["function"]["name"].startswith("wechat_") for item in registry.schemas())


def test_attachment_storage_key_is_rooted_and_traversal_safe(tmp_path: Path):
    storage = AttachmentStorage(tmp_path / "attachments")
    storage.ensure()
    key, path = storage.path_for("a" * 32, "note.txt")
    assert key == ("a" * 32) + "/note.txt"
    assert path.parent == (tmp_path / "attachments" / ("a" * 32)).resolve()
    with pytest.raises(ValueError):
        storage.key_path("../outside.txt")
    with pytest.raises(ValueError):
        storage.key_path("C:/outside.txt")


def test_sqlite_wal_and_versioned_migration(tmp_path: Path):
    session_factory = init_db(tmp_path / "miru.db")
    assert session_factory is not None
    from miru_server.db.database import engine

    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar_one().lower() == "wal"
        assert schema_version(conn) == LATEST_SCHEMA_VERSION
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(attachments)"))}
        assert "storage_key" in columns


def test_migration_failure_rolls_back_version_and_ddl(tmp_path: Path):
    db_path = tmp_path / "migration.db"
    engine = create_engine(f"sqlite:///{db_path}")

    def migration_one(conn):
        conn.execute(text("CREATE TABLE partial_change (id INTEGER PRIMARY KEY)"))

    with pytest.raises(RuntimeError, match="missing migration"):
        with engine.begin() as conn:
            apply_migrations(conn, target=2, migrations={1: migration_one})
    with engine.connect() as conn:
        assert schema_version(conn) == 0
        assert conn.execute(text(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='partial_change'"
        )).scalar_one() == 0


@pytest.mark.asyncio
async def test_llm_json_failure_does_not_log_response_body(monkeypatch, caplog):
    client = LLMClient(type("Cfg", (), {
        "api_key": "test-key", "base_url": "https://example.invalid", "timeout_s": 1,
        "model": "test", "thinking": False, "max_tokens": 1000,
    })())
    marker = "RESPONSE_BODY_SHOULD_NOT_BE_LOGGED"

    async def fake_create(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=marker))])

    monkeypatch.setattr(client._client.chat.completions, "create", fake_create)
    with caplog.at_level(logging.WARNING):
        assert await client.chat_json("system", "user") == {}
    assert marker not in caplog.text
