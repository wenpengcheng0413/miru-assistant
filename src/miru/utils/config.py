"""
Miru Assistant — 配置加载器。

从 YAML 配置文件加载配置，支持环境变量替换。
使用 Pydantic 进行配置校验。
敏感字段使用 SecretStr 防止日志/序列化泄露。
"""

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, SecretStr, ValidationError

from miru.utils.errors import ConfigNotFoundError, ConfigValidationError

# 匹配 ${ENV_VAR} 或 ${ENV_VAR:default}
_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")


def _resolve_env_vars(value: Any) -> Any:
    """递归替换值中的 ${ENV_VAR} 模式。"""
    if isinstance(value, str):
        def _replace(m: re.Match[str]) -> str:
            var_name = m.group(1)
            default = m.group(2)
            return os.environ.get(var_name, default if default is not None else "")

        return _ENV_VAR_PATTERN.sub(_replace, value)
    elif isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


class SchedulerConfig(BaseModel):
    """调度器配置。"""
    daily_report_time: str = "21:00"
    timezone: str = "Asia/Shanghai"
    misfire_grace_time: int = 1800


class LLMConfig(BaseModel):
    """LLM API 配置。"""
    provider: str = "deepseek"
    api_key: SecretStr = Field(default=SecretStr(""))
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    temperature: float = 0.3
    max_tokens: int = 2048
    timeout: int = 60
    max_retries: int = 2
    retry_delay: list[int] = [5, 30]

    def get_api_key(self) -> str:
        """安全获取 API key 明文。"""
        return self.api_key.get_secret_value()


class NotifierConfig(BaseModel):
    """推送渠道配置。"""
    type: str
    enabled: bool = True
    token: SecretStr = Field(default=SecretStr(""))

    def get_token(self) -> str:
        """安全获取 token 明文。"""
        return self.token.get_secret_value()


class StorageConfig(BaseModel):
    """存储配置。"""
    db_path: str = "./data/miru.db"
    log_path: str = "./data/logs"
    log_level: str = "INFO"
    log_retention: str = "30 days"
    log_rotation: str = "10 MB"


class WeChatConfig(BaseModel):
    """微信客户端配置。"""
    data_dir: str = ""
    database_key: str = ""  # 手动提供 64 hex 数据库密钥 (跳过自动提取)
    tested_version: str = "4.0.x"
    on_version_mismatch: str = "warn"


class MiruConfig(BaseModel):
    """Miru Assistant 主配置。"""
    groups: list[str] = Field(default_factory=list)
    scheduler: SchedulerConfig = SchedulerConfig()
    llm: LLMConfig = LLMConfig()
    notifiers: list[NotifierConfig] = Field(default_factory=list)
    storage: StorageConfig = StorageConfig()
    wechat: WeChatConfig = WeChatConfig()


class AppConfig(BaseModel):
    """应用根配置。"""
    miru: MiruConfig = MiruConfig()


def load_config(config_path: str | Path = "config/settings.yaml") -> AppConfig:
    """
    加载并校验配置文件。

    Args:
        config_path: YAML 配置文件路径。

    Returns:
        校验后的 AppConfig 对象。

    Raises:
        ConfigNotFoundError: 配置文件不存在。
        ConfigValidationError: 配置校验失败。
    """
    path = Path(config_path)

    if not path.exists():
        raise ConfigNotFoundError(
            f"配置文件不存在: {path}\n"
            f"请从模板复制: cp config/settings.example.yaml config/settings.yaml"
        )

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raise ConfigValidationError(f"配置文件为空: {path}")

    # 环境变量替换
    resolved = _resolve_env_vars(raw)

    try:
        return AppConfig(**resolved)
    except ValidationError as e:
        raise ConfigValidationError(f"配置校验失败:\n{e}") from e
