"""价格计算测试：缓存命中、高峰 ×2、周末不乘。"""
from datetime import datetime
from pathlib import Path

from miru_server.cost.pricing import Pricing, TZ_SH

PRICING_PATH = Path(__file__).parent.parent / "config" / "pricing.yaml"


def _pricing() -> Pricing:
    return Pricing(PRICING_PATH)


def test_basic_cost_non_peak():
    p = _pricing()
    ts = datetime(2026, 8, 13, 20, 0, tzinfo=TZ_SH)   # 周四 20:00 非高峰
    cost, peak = p.llm_cost("deepseek", "deepseek-v4-flash", 1_000_000, 1_000_000, 0, ts)
    assert not peak
    assert abs(cost - 3.0) < 1e-9                   # 1 + 2


def test_peak_multiplier_weekday():
    p = _pricing()
    ts = datetime(2026, 8, 13, 10, 0, tzinfo=TZ_SH)  # 周四 10:00 高峰
    cost, peak = p.llm_cost("deepseek", "deepseek-v4-flash", 1_000_000, 1_000_000, 0, ts)
    assert peak
    assert abs(cost - 6.0) < 1e-9                   # (1+2) × 2


def test_weekend_no_peak():
    p = _pricing()
    ts = datetime(2026, 8, 15, 10, 0, tzinfo=TZ_SH)  # 周六
    _, peak = p.llm_cost("deepseek", "deepseek-v4-flash", 0, 0, 0, ts)
    assert not peak


def test_cache_hit_is_cheap():
    p = _pricing()
    ts = datetime(2026, 8, 13, 20, 0, tzinfo=TZ_SH)
    cost, _ = p.llm_cost("deepseek", "deepseek-v4-flash", 1_000_000, 100_000, 900_000, ts)
    # 100k miss ×1 + 900k hit ×0.02 + 100k out ×2 = 0.1 + 0.018 + 0.2 = 0.318
    assert abs(cost - 0.318) < 1e-9


def test_tts_char_cost():
    p = _pricing()
    assert abs(p.char_cost("minimax", "speech-02-turbo", 10_000) - 2.0) < 1e-9
    assert p.char_cost("edge", "zh-CN-XiaoxiaoNeural", 10_000) == 0.0


def test_missing_model_zero_cost():
    p = _pricing()
    cost, peak = p.llm_cost("deepseek", "no-such-model", 1000, 1000, 0, None)
    assert cost == 0.0 and not peak
