"""配置加载：yaml + ${ENV_VAR} 环境变量解析（与 V2 utils/config 风格一致）。"""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_ENV_RE = re.compile(r"\$\{(\w+)\}")


def _resolve_env(value: object) -> object:
    """递归解析字符串中的 ${VAR}；缺失的环境变量替换为空串。"""
    if isinstance(value, str):
        def _sub(m: re.Match) -> str:
            return os.environ.get(m.group(1), "")
        return _ENV_RE.sub(_sub, value)
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    return value


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765
    token: str = ""
    advertise_lan: bool = True
    service_name: str = "Miru"


class LLMConfig(BaseModel):
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-v4-flash"
    vision_model: str = "deepseek-v4-flash-vision-exp"
    thinking: bool = False
    temperature: float = 0.7
    max_tokens: int = 8192
    short_max_tokens: int = 2048
    timeout_s: float = 90.0
    max_tool_rounds: int = 6


class VADConfig(BaseModel):
    engine: str = "energy"
    threshold_db: float = 6.0
    min_speech_ms: int = 300
    min_silence_ms: int = 500
    max_utterance_ms: int = 15000


class STTConfig(BaseModel):
    engine: str = "sensevoice"          # sensevoice | whisper | none
    model_dir: str = "./data/models/sensevoice"
    language: str = "auto"
    num_threads: int = 4
    partial_interval_ms: int = 800
    # 懒加载：连续 N 秒没用语音识别就卸载模型（释放 ~0.9GB 内存）；0 = 常驻不卸载
    idle_unload_seconds: float = 300.0
    vad: VADConfig = Field(default_factory=VADConfig)
    whisper_model: str = "small"
    whisper_model_dir: str = "./data/models"


class MiniMaxConfig(BaseModel):
    base_url: str = "https://api.minimaxi.com"
    api_key: str = ""
    group_id: str = ""
    model: str = "speech-02-turbo"


class EdgeTTSConfig(BaseModel):
    voice: str = "zh-CN-XiaoxiaoNeural"


class TTSConfig(BaseModel):
    provider: str = "minimax"           # minimax | edge | none
    format: str = "mp3"                 # mp3 | pcm
    sample_rate: int = 32000
    fallback_to_edge: bool = True
    minimax: MiniMaxConfig = Field(default_factory=MiniMaxConfig)
    edge: EdgeTTSConfig = Field(default_factory=EdgeTTSConfig)


class MemoryConfig(BaseModel):
    auto_extract: bool = True
    history_max_chars: int = 16000
    episodes_max_in_prompt: int = 5
    summarize_at_rounds: int = 20


class PersonaConfig(BaseModel):
    default: str = "miru"
    dir: str = "./config/persona"


class WeChatToolConfig(BaseModel):
    llm_visibility: str = "aggregates"  # aggregates | samples | raw
    data_root: str = ""


class ToolsConfig(BaseModel):
    enabled: list[str] = Field(default_factory=list)
    wechat: WeChatToolConfig = Field(default_factory=WeChatToolConfig)


class BudgetConfig(BaseModel):
    hard_block: bool = False


class DBConfig(BaseModel):
    path: str = "./data/miru_server.db"


class BackupConfig(BaseModel):
    """本机数据保护：备份文件必须位于数据库目录之外。"""

    enabled: bool = True
    dir: str = "./data/backups"
    retention_days: int = 30


class AttachmentConfig(BaseModel):
    """手机上传文件的本机落盘位置和安全上限。"""

    dir: str = "./data/attachments"
    max_file_mb: int = 50
    max_images_per_turn: int = 10
    max_preview_pages: int = 10
    max_extracted_chars_per_turn: int = Field(default=80_000, ge=10_000, le=200_000)


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    persona: PersonaConfig = Field(default_factory=PersonaConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    db: DBConfig = Field(default_factory=DBConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    attachments: AttachmentConfig = Field(default_factory=AttachmentConfig)

    # 配置文件目录用于加载 pricing.yaml；运行路径统一按项目目录解析。
    config_dir: Path = Path("config")
    project_dir: Path = Path(".")

    def resolve(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (self.project_dir / p)

    @classmethod
    def load(cls, path: str | Path | None = None) -> AppConfig:
        """加载 yaml 配置；文件不存在时用默认值（settings.example.yaml 有完整模板）。"""
        path = Path(path) if path else Path(
            os.environ.get("MIRU_SERVER_CONFIG", "config/settings.yaml")
        )
        path = path.resolve()
        raw: dict = {}
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw = _resolve_env(raw)
        cfg = cls.model_validate(raw)
        cfg.config_dir = path.parent
        cfg.project_dir = path.parent.parent if path.parent.name == "config" else path.parent
        cfg.stt.model_dir = str(cfg.resolve(cfg.stt.model_dir))
        cfg.stt.whisper_model_dir = str(cfg.resolve(cfg.stt.whisper_model_dir))
        return cfg
