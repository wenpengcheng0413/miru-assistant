"""REST API 冒烟测试（TestClient + lifespan）。"""
from fastapi.testclient import TestClient

from miru_server.main import create_app


def test_health_requires_token(app_config):
    app = create_app(app_config)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 401
        resp = client.get("/api/health", headers={"Authorization": "Bearer test-token"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["stt_engine"] == "none"
        assert data["tts_provider"] == "none"
        assert data["build_id"]
        assert "error_code" in data["wechat"]


def test_memory_endpoints(app_config):
    app = create_app(app_config)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        r = client.put("/api/memory/profile/称呼", json={"value": "老板"}, headers=headers)
        assert r.status_code == 200
        r = client.get("/api/memory?scope=profile", headers=headers)
        entries = r.json()["entries"]
        assert any(e["key"] == "称呼" and e["value"] == "老板" for e in entries)
        r = client.get("/api/memory?q=老板", headers=headers)
        assert r.json()["entries"]
        r = client.delete("/api/memory/profile/称呼", headers=headers)
        assert r.json()["removed"] is True
        client.put(
            "/api/memory/knowledge/new",
            json={"value": "旧知识"},
            headers=headers,
        )
        knowledge = client.get("/api/memory?scope=knowledge", headers=headers).json()["entries"]
        knowledge_id = knowledge[0]["id"]
        r = client.put(
            f"/api/memory/knowledge/{knowledge_id}",
            json={"value": "修改后的知识"},
            headers=headers,
        )
        assert r.status_code == 200
        knowledge = client.get("/api/memory?scope=knowledge", headers=headers).json()["entries"]
        assert knowledge[0]["content"] == "修改后的知识"
        r = client.delete(f"/api/memory/knowledge/{knowledge_id}", headers=headers)
        assert r.json()["removed"] is True


def test_persona_and_budget_endpoints(app_config):
    app = create_app(app_config)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        r = client.get("/api/persona", headers=headers)
        assert r.json()["name"] == "Miru"
        r = client.put("/api/cost/budget", json={"provider": "total", "limit_rmb": 150}, headers=headers)
        assert r.status_code == 200
        r = client.get("/api/cost/budget", headers=headers)
        assert r.json()["limit_rmb"] == 150
        r = client.get("/api/cost/report?days=7", headers=headers)
        assert "total_rmb" in r.json()
        r = client.get("/api/tools", headers=headers)
        assert any(t["name"] == "get_current_time" for t in r.json()["tools"])
        assert any(t["name"] == "wechat_transcribe_voice" for t in r.json()["tools"])


def test_conversation_sidebar_endpoints(app_config):
    app = create_app(app_config)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        created = client.post("/api/conversations", json={"persona": "miru"}, headers=headers)
        assert created.status_code == 201
        conv_id = created.json()["id"]
        renamed = client.patch(
            f"/api/conversations/{conv_id}", json={"title": "旅行计划"}, headers=headers
        )
        assert renamed.json()["title"] == "旅行计划"
        rows = client.get("/api/conversations?q=旅行", headers=headers).json()
        assert rows[0]["id"] == conv_id
        assert rows[0]["message_count"] == 0


def test_image_attachment_upload(app_config):
    app = create_app(app_config)
    headers = {"Authorization": "Bearer test-token"}
    png = b"\x89PNG\r\n\x1a\n" + b"fake-image"
    with TestClient(app) as client:
        conv = client.post("/api/conversations", json={}, headers=headers).json()["id"]
        response = client.post(
            f"/api/conversations/{conv}/attachments",
            headers=headers,
            files={"file": ("photo.png", png, "image/png")},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["kind"] == "image"
        assert data["filename"] == "photo.png"
        files = client.get(f"/api/conversations/{conv}/attachments", headers=headers).json()
        assert files[0]["id"] == data["id"]


def test_csv_attachment_is_extracted_locally(app_config):
    app = create_app(app_config)
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        conv = client.post("/api/conversations", json={}, headers=headers).json()["id"]
        response = client.post(
            f"/api/conversations/{conv}/attachments",
            headers=headers,
            files={"file": ("sales.csv", b"month,revenue\nJuly,120\n", "text/csv")},
        )
        assert response.status_code == 201
        assert response.json()["kind"] == "spreadsheet"
        assert response.json()["status"] == "ready"
        assert response.json()["error"] == ""
