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
    cors_origins: list[str] = Field(default_factory=list)


class LLMConfig(BaseModel):
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-v4-flash"
    vision_model: str = "deepseek-v4-flash-vision-exp"
    thinking: bool = False
    temperature: float = 0.7
    # DeepSeek V4 Flash supports up to 384K output; 32K is a practical default
    # for attachment reports without making ordinary requests unnecessarily slow.
    max_tokens: int = 32768
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
    snapshot_dir: str = "./data/wechat_snapshot"
    snapshot_max_age_hours: float = 168.0
    sync_copy_media: bool = True


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


class HomeNodeConfig(BaseModel):
    """Cloud-side identity and liveness policy for the outbound Home Node."""

    enabled: bool = False
    node_id: str = "node-home"
    token: str = ""
    allowed_capabilities: list[str] = Field(default_factory=list)
    heartbeat_interval_s: int = Field(default=20, ge=5, le=60)
    stale_after_s: int = Field(default=30, ge=10, le=180)
    offline_after_s: int = Field(default=60, ge=20, le=300)

    def model_post_init(self, __context: object) -> None:
        if self.offline_after_s <= self.stale_after_s:
            raise ValueError("home_node.offline_after_s must exceed stale_after_s")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", self.node_id):
            raise ValueError("home_node.node_id is invalid")
        clean: list[str] = []
        for item in self.allowed_capabilities:
            value = item.strip()
            if value and len(value) <= 64 and re.fullmatch(r"[a-z0-9_.-]+", value):
                clean.append(value)
        self.allowed_capabilities = sorted(set(clean))


class AppConfig(BaseModel):
    # development keeps the current Windows behavior; cloud is deliberately
    # dependency-light and never initializes Home Node/WeChat/local STT.
    profile: str = "development"
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
    home_node: HomeNodeConfig = Field(default_factory=HomeNodeConfig)

    # 配置文件目录用于加载 pricing.yaml；运行路径统一按项目目录解析。
    config_dir: Path = Path("config")
    project_dir: Path = Path(".")

    def model_post_init(self, __context: object) -> None:
        profile = (self.profile or "development").strip().lower()
        if profile not in {"development", "cloud", "node"}:
            raise ValueError("profile must be development, cloud, or node")
        self.profile = profile
        if profile == "cloud":
            # Cloud must not probe LAN/Bonjour, import WeChat, or load a local
            # SenseVoice/Whisper model. Voice is reported unavailable until a
            # later external-provider phase supplies it explicitly.
            self.server.advertise_lan = False
            # Fail closed if an old local config carried the development
            # wildcard; browser origins must be explicitly enumerated later.
            self.server.cors_origins = [
                origin.strip()
                for origin in self.server.cors_origins
                if origin.strip() and origin.strip() != "*"
            ]
            self.stt.engine = "none"
            # Cloud never imports the local WeChat implementation. Only when
            # Home Node is explicitly enabled may the fixed Phase 8 proxy stay
            # configured; its schema remains hidden until the node is online.
            remote_node_tools = {
                "wechat_search_messages",
                "wechat_conversation_messages",
                "wechat_transcribe_voice",
            } if self.home_node.enabled else set()
            self.tools.enabled = [
                name for name in self.tools.enabled
                if not name.startswith("wechat_") or name in remote_node_tools
            ]
            if self.home_node.enabled and len(self.home_node.token) < 32:
                raise ValueError(
                    "MIRU_HOME_NODE_TOKEN (at least 32 characters) is required when Home Node is enabled"
                )

    @property
    def is_cloud(self) -> bool:
        return self.profile == "cloud"

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
        profile_override = os.environ.get("MIRU_PROFILE", "").strip()
        if profile_override:
            raw["profile"] = profile_override
        raw = _resolve_env(raw)
        cfg = cls.model_validate(raw)
        cfg.config_dir = path.parent
        cfg.project_dir = path.parent.parent if path.parent.name == "config" else path.parent
        cfg.stt.model_dir = str(cfg.resolve(cfg.stt.model_dir))
        cfg.stt.whisper_model_dir = str(cfg.resolve(cfg.stt.whisper_model_dir))
        return cfg
