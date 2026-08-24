"""服务装配：启动时创建一次，全部组件通过 Services 引用（避免循环导入）。"""
from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig, STTConfig
from .core.llm import LLMClient
from .cost.pricing import Pricing
from .cost.tracker import CostTracker
from .db.database import init_db
from .memory.store import MemoryStore
from .persona.builder import PersonaManager
from .stt.base import NoneSTT, STTEngine, STTUnavailable, create_stt
from .tools.registry import ToolRegistry, build_registry
from .tts.base import TTSProvider, create_fallback_provider, create_provider

logger = logging.getLogger(__name__)


def _stt_config_ok(cfg: STTConfig) -> bool:
    """廉价可用性检查：只验依赖与模型文件，不加载模型本体（省 ~0.9GB 常驻）。"""
    if cfg.engine == "sensevoice":
        try:
            if importlib.util.find_spec("sherpa_onnx") is None:
                return False
        except Exception:
            return False
        model_dir = Path(cfg.model_dir)
        return (model_dir / "model.onnx").exists() and (model_dir / "tokens.txt").exists()
    if cfg.engine == "whisper":
        try:
            return importlib.util.find_spec("faster_whisper") is not None
        except Exception:
            return False
    return True


@dataclass
class Services:
    config: AppConfig
    db: object                       # sessionmaker[Session]
    llm: LLMClient
    tools: ToolRegistry
    persona: PersonaManager
    memory: MemoryStore
    cost: CostTracker
    pricing: Pricing
    stt: STTEngine
    tts_provider: TTSProvider | None
    tts_fallback: TTSProvider | None


def create_services(config: AppConfig) -> Services:
    db = init_db(config.resolve(config.db.path))
    pricing = Pricing(config.config_dir / "pricing.yaml")

    stt: STTEngine
    # 懒加载 + 闲置卸载：SenseVoice 常驻约 0.9GB，空闲时不扛（首次识别慢 1~3 秒）
    if config.stt.engine == "none":
        stt = NoneSTT()
    elif not _stt_config_ok(config.stt):
        logger.warning(
            "STT 依赖/模型缺失（engine=%s），进入文本模式", config.stt.engine
        )
        stt = NoneSTT()
    else:
        from .stt.lazy import LazySTT

        stt = LazySTT(
            factory=lambda: create_stt(config.stt),
            idle_unload_seconds=config.stt.idle_unload_seconds,
        )

    tts_provider, tts_fallback = None, None
    try:
        tts_provider = create_provider(config.tts)
        tts_fallback = create_fallback_provider(config.tts)
    except Exception as e:
        logger.warning("TTS provider 初始化失败: %s", e)

    return Services(
        config=config,
        db=db,
        llm=LLMClient(config.llm),
        tools=build_registry(config),
        persona=PersonaManager(config.resolve(config.persona.dir)),
        memory=MemoryStore(db),
        cost=CostTracker(db, pricing),
        pricing=pricing,
        stt=stt,
        tts_provider=tts_provider,
        tts_fallback=tts_fallback,
    )
