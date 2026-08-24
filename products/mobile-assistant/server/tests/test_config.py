"""配置加载测试：yaml + ${ENV} 解析。"""
from pathlib import Path

from miru_server.config import AppConfig


def test_env_var_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("MIRU_TEST_TOKEN", "abc123")
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text(
        'server:\n  token: "${MIRU_TEST_TOKEN}"\n  port: 9999\n',
        encoding="utf-8",
    )
    cfg = AppConfig.load(yaml_path)
    assert cfg.server.token == "abc123"
    assert cfg.server.port == 9999
    assert cfg.config_dir == tmp_path
    assert cfg.project_dir == tmp_path
    assert Path(cfg.stt.model_dir) == tmp_path / "data" / "models" / "sensevoice"


def test_missing_env_becomes_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("MIRU_NOT_SET_VAR", raising=False)
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text('server:\n  token: "${MIRU_NOT_SET_VAR}"\n', encoding="utf-8")
    cfg = AppConfig.load(yaml_path)
    assert cfg.server.token == ""


def test_defaults_without_file(tmp_path):
    cfg = AppConfig.load(tmp_path / "not-exists.yaml")
    assert cfg.server.port == 8765
    assert cfg.server.advertise_lan is True
    assert cfg.llm.model == "deepseek-v4-flash"
    assert cfg.tts.provider == "minimax"
