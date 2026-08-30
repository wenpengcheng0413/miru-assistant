"""Phase 2 deployment-definition checks that do not require Docker Desktop."""
from __future__ import annotations

from pathlib import Path
import re

import yaml


REPO_ROOT = Path(__file__).resolve().parents[4]
DEPLOY = REPO_ROOT / "deploy"


def test_phase2_deploy_files_exist():
    for name in (
        "Dockerfile",
        "compose.yaml",
        "Caddyfile",
        "requirements-cloud.txt",
        "settings.cloud.example.yaml",
        "mock_llm.py",
        "benchmark.py",
    ):
        assert (DEPLOY / name).is_file()
    assert (REPO_ROOT / ".dockerignore").is_file()


def test_dockerfile_is_cloud_only_and_non_root():
    text = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in text
    assert "USER miru" in text
    assert "COPY products/mobile-assistant/server/miru_server" in text
    copy_lines = "\n".join(line for line in text.splitlines() if line.strip().startswith("COPY"))
    assert not re.search(r"settings\.yaml|\.env|data/models", copy_lines)


def test_cloud_requirements_exclude_windows_and_local_stt():
    text = "\n".join(
        line.split("#", 1)[0].strip().lower()
        for line in (DEPLOY / "requirements-cloud.txt").read_text(encoding="utf-8").splitlines()
    )
    for forbidden in ("pymem", "pysilk", "sherpa-onnx", "faster-whisper", "zeroconf", "cuda"):
        assert forbidden not in text


def test_compose_is_isolated_and_has_initial_limits():
    compose = yaml.safe_load((DEPLOY / "compose.yaml").read_text(encoding="utf-8"))
    assert compose["name"] == "miru-phase2"
    assert set(("miru-api", "caddy", "mock-llm")) <= set(compose["services"])
    api = compose["services"]["miru-api"]
    caddy = compose["services"]["caddy"]
    assert api["container_name"] == "miru-phase2-api"
    assert api["mem_limit"] == "640m"
    assert api["memswap_limit"] == "768m"
    assert api["cpus"] == 1.0
    assert api["pids_limit"] == 128
    assert api["read_only"] is True
    assert caddy["mem_limit"] == "96m"
    assert caddy["memswap_limit"] == "128m"
    assert caddy["cpus"] == 0.2
    assert caddy["pids_limit"] == 64
    assert "miru-phase2-data" in compose["volumes"]
    assert "miru-phase2-network" in compose["networks"]
    assert not any("miru_server.db" in str(v) for v in api.get("volumes", []))


def test_caddy_is_local_proxy_and_clears_identity_headers():
    text = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")
    assert ":8080" in text
    assert "reverse_proxy miru-api:8765" in text
    assert "header -Tailscale-User-Login" in text
    assert "header -Tailscale-App-Capabilities" in text
    assert "https://" not in text


def test_dockerignore_excludes_private_runtime_trees():
    text = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
    for forbidden in ("**/settings.yaml", "**/.env", "**/data", "**/wechat_snapshot", "**/models", "*.db"):
        assert forbidden in text
