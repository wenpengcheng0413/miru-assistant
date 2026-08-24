"""Pytest fixtures — 测试公共配置。"""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """创建临时目录，测试结束后自动清理。"""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def sample_config_data():
    """提供测试用的最小配置。"""
    return {
        "miru": {
            "groups": ["测试群"],
            "scheduler": {
                "daily_report_time": "21:00",
                "timezone": "Asia/Shanghai",
                "misfire_grace_time": 1800,
            },
            "llm": {
                "provider": "deepseek",
                "api_key": "test-key",
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-v4-flash",
                "temperature": 0.3,
                "max_tokens": 2048,
                "timeout": 60,
                "max_retries": 2,
                "retry_delay": [5, 30],
            },
            "notifiers": [
                {"type": "console", "enabled": True, "token": ""},
            ],
            "storage": {
                "db_path": "./data/miru.db",
                "log_path": "./data/logs",
                "log_level": "INFO",
                "log_retention": "30 days",
                "log_rotation": "10 MB",
            },
            "wechat": {
                "data_dir": "",
                "tested_version": "4.0.x",
                "on_version_mismatch": "warn",
            },
        }
    }
