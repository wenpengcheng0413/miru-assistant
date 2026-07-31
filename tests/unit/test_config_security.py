"""
Miru Assistant — 配置安全性测试 (V1.1 Phase 2)。

测试覆盖:
    - SecretStr 不泄露明文
    - get_api_key / get_token
    - 环境变量优先
    - print/str 不暴露密钥
"""

import os

import pytest
import yaml
from pydantic import SecretStr

from miru.utils.config import (
    LLMConfig,
    MiruConfig,
    NotifierConfig,
    _resolve_env_vars,
    load_config,
)


class TestSecretStr:
    """SecretStr 安全性测试。"""

    def test_llm_api_key_is_secret(self):
        cfg = LLMConfig(api_key=SecretStr("sk-secret-123"))
        # str() 不应暴露明文
        assert "sk-secret-123" not in str(cfg)
        # repr() 不应暴露
        assert "sk-secret-123" not in repr(cfg)
        # 通过 getter 获取
        assert cfg.get_api_key() == "sk-secret-123"

    def test_notifier_token_is_secret(self):
        cfg = NotifierConfig(type="pushplus", token=SecretStr("tok-abc"))
        assert "tok-abc" not in str(cfg)
        assert cfg.get_token() == "tok-abc"

    def test_empty_defaults(self):
        cfg = LLMConfig()
        assert cfg.get_api_key() == ""
        nc = NotifierConfig(type="console")
        assert nc.get_token() == ""


class TestEnvVarResolution:
    """环境变量替换测试。"""

    def test_env_var_substitution(self):
        os.environ["MIRU_TEST_KEY"] = "test-value-123"
        raw = {"key": "${MIRU_TEST_KEY}"}
        resolved = _resolve_env_vars(raw)
        assert resolved["key"] == "test-value-123"
        del os.environ["MIRU_TEST_KEY"]

    def test_env_var_with_default(self):
        if "NONEXISTENT_VAR" in os.environ:
            del os.environ["NONEXISTENT_VAR"]
        raw = {"key": "${NONEXISTENT_VAR:fallback}"}
        resolved = _resolve_env_vars(raw)
        assert resolved["key"] == "fallback"

    def test_nested_dict_resolution(self):
        os.environ["MIRU_NESTED"] = "nested-val"
        raw = {"outer": {"inner": "${MIRU_NESTED}"}}
        resolved = _resolve_env_vars(raw)
        assert resolved["outer"]["inner"] == "nested-val"
        del os.environ["MIRU_NESTED"]


class TestConfigLoadWithSecrets:
    """完整配置加载 + SecretStr。"""

    def test_load_config_with_env_key(self, tmp_path):
        """通过环境变量注入 API key。"""
        config_data = {
            "miru": {
                "groups": ["test"],
                "scheduler": {
                    "daily_report_time": "21:00",
                    "timezone": "Asia/Shanghai",
                    "misfire_grace_time": 1800,
                },
                "llm": {
                    "provider": "deepseek",
                    "api_key": "${MIRU_TEST_API_KEY}",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-v4-flash",
                    "temperature": 0.3,
                    "max_tokens": 2048,
                    "timeout": 60,
                    "max_retries": 2,
                    "retry_delay": [5, 30],
                },
                "notifiers": [
                    {"type": "pushplus", "enabled": True, "token": "${MIRU_TEST_TOKEN}"},
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

        config_path = tmp_path / "settings.yaml"
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        os.environ["MIRU_TEST_API_KEY"] = "sk-my-key-123"
        os.environ["MIRU_TEST_TOKEN"] = "my-pushplus-token"

        cfg = load_config(str(config_path))

        assert cfg.miru.llm.get_api_key() == "sk-my-key-123"
        assert cfg.miru.notifiers[0].get_token() == "my-pushplus-token"
        # 验证不泄露
        cfg_str = str(cfg)
        assert "sk-my-key-123" not in cfg_str

        del os.environ["MIRU_TEST_API_KEY"]
        del os.environ["MIRU_TEST_TOKEN"]
