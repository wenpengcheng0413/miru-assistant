"""测试夹具：临时配置/数据库/服务，全部离线（不联网、不需要 API key）。"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from miru_server.config import AppConfig
from miru_server.services import create_services

PERSONA_YAML = """
name: Miru
role: 个人 AI 助理
personality: 聪明、直接、略带幽默感
speaking_style: 中文为主，像朋友聊天
response_style:
  simple: 一句话答完
  complex: 先给结论
address_user: 老板
prohibitions:
  - 不编造数据
voice:
  voice_id: Calm_Woman
  speed: 1.0
  emotion: neutral
"""


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    shutil.copy(BACKEND_DIR / "config" / "pricing.yaml", config_dir / "pricing.yaml")
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir()
    (persona_dir / "miru.yaml").write_text(PERSONA_YAML, encoding="utf-8")

    cfg = AppConfig.model_validate({
        "server": {"token": "test-token"},
        "db": {"path": str(tmp_path / "test.db")},
        "stt": {"engine": "none"},
        "tts": {"provider": "none"},
        "memory": {"auto_extract": False},
        "persona": {"dir": str(persona_dir)},
        "llm": {"api_key": "test-key"},
        "tools": {
            "enabled": [
                "get_current_time", "memory_set", "memory_get", "memory_list",
                "memory_delete", "memory_search", "api_cost_report", "api_budget_set",
            ],
        },
    })
    cfg.config_dir = config_dir
    cfg.project_dir = tmp_path
    return cfg


@pytest.fixture
def services(app_config: AppConfig):
    return create_services(app_config)
