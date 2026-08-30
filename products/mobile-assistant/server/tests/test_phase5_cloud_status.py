import json
from pathlib import Path

from fastapi.testclient import TestClient

from miru_server.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[4]


def _cloud_config(app_config):
    values = app_config.model_dump()
    values["profile"] = "cloud"
    values["server"]["token"] = "test-token"
    values["server"]["advertise_lan"] = False
    values["server"]["cors_origins"] = []
    values["llm"]["api_key"] = "test-key"
    values["stt"]["engine"] = "none"
    return type(app_config).model_validate(values)


def test_status_has_version_and_timestamp(app_config):
    cfg = _cloud_config(app_config)
    with TestClient(create_app(cfg)) as client:
        response = client.get(
            "/api/status",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["schema_version"] == 1
        assert payload["generated_at"].endswith("+00:00")
        assert payload["cloud"]["state"] == "ready"


def test_websocket_sends_bounded_system_status_after_hello(app_config):
    cfg = _cloud_config(app_config)
    with TestClient(create_app(cfg)) as client:
        with client.websocket_connect("/ws/session") as websocket:
            websocket.send_text(json.dumps({
                "type": "hello",
                "token": "test-token",
                "device": "iphone",
                "device_id": "ios-test-device",
                "mode": "text",
            }))
            assert websocket.receive_json()["type"] == "hello_ok"
            event = websocket.receive_json()
            assert event["type"] == "system_status"
            status = event["status"]
            assert status["cloud"]["state"] == "ready"
            assert status["home_node"]["state"] == "not_configured"
            serialized = json.dumps(status).lower()
            assert "test-token" not in serialized
            assert "test-key" not in serialized


def test_flutter_production_profile_is_fail_closed_and_value_free():
    config = (REPO_ROOT / "products/mobile-assistant/app/lib/core/config.dart").read_text(
        encoding="utf-8"
    )
    controller = (
        REPO_ROOT / "products/mobile-assistant/app/lib/features/chat/chat_controller.dart"
    ).read_text(encoding="utf-8")
    pipeline = (REPO_ROOT / "codemagic.yaml").read_text(encoding="utf-8")

    assert "String token = '';" in config
    assert "dev-smoke-test-token" not in config
    assert "profile.allowsBonjour" in config
    assert "config.bonjourEnabled" in controller
    assert "MIRU_DEPLOYMENT_PROFILE=tailnet" in pipeline
    assert "MIRU_BASE_URL must use HTTPS" in pipeline
    assert "NSAllowsArbitraryLoads" not in pipeline
    assert "NSBonjourServices" not in pipeline
