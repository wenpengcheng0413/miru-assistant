"""价格表加载与费用计算（价格在 config/pricing.yaml，改价不改代码）。"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

logger = logging.getLogger(__name__)

TZ_SH = ZoneInfo("Asia/Shanghai")


class Pricing:
    def __init__(self, yaml_path: str | Path):
        path = Path(yaml_path)
        if not path.exists():
            logger.warning("pricing.yaml 不存在（%s），费用按 0 计", path)
            self.raw: dict = {}
            return
        self.raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    # ---- LLM ----

    def llm_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_hit_tokens: int = 0,
        ts: datetime | None = None,
    ) -> tuple[float, bool]:
        """返回 (费用, 是否高峰)。"""
        table = self.raw.get(provider, {}).get(model)
        if not table:
            return 0.0, False
        miss = max(input_tokens - cache_hit_tokens, 0)
        cost = (
            miss * table.get("input_per_m", 0)
            + cache_hit_tokens * table.get("input_cache_hit_per_m", 0)
            + output_tokens * table.get("output_per_m", 0)
        ) / 1_000_000
        peak = self._is_peak(ts)
        if peak:
            cost *= self.raw.get(provider, {}).get("peak_multiplier", 1.0)
        return cost, peak

    def _is_peak(self, ts: datetime | None) -> bool:
        if ts is None:
            ts = datetime.now(TZ_SH)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=TZ_SH)
        local = ts.astimezone(TZ_SH)
        if local.weekday() >= 5:   # 周末不算高峰
            return False
        for start, end in self.raw.get("deepseek", {}).get("peak_hours", []):
            if start <= local.hour < end:
                return True
        return False

    # ---- 按字符计费（TTS）----

    def char_cost(self, provider: str, model: str, chars: int) -> float:
        per_10k = self.raw.get(provider, {}).get(model, {}).get("per_10k_chars", 0)
        return chars / 10_000 * per_10k
