"""成本账本：每次 LLM/TTS 调用的用量与费用入账 + 预算检查（docs/08 §1）。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..core.llm import Usage
from ..db.models import ApiUsage, Budget
from .pricing import Pricing

logger = logging.getLogger(__name__)


def _month(ts: datetime | None = None) -> str:
    ts = ts or datetime.now()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone().strftime("%Y-%m")


class CostTracker:
    def __init__(self, db: sessionmaker[Session], pricing: Pricing):
        self._db = db
        self._pricing = pricing

    # ---- 入账（同步，调用方用 to_thread）----

    def record_llm(
        self,
        conversation_id: str | None,
        model: str,
        usage: Usage,
        ts: datetime | None = None,
    ) -> float:
        cost, peak = self._pricing.llm_cost(
            "deepseek", model,
            usage.prompt_tokens, usage.completion_tokens,
            usage.cache_hit_tokens, ts,
        )
        with self._db() as s:
            s.add(ApiUsage(
                conversation_id=conversation_id,
                provider="deepseek",
                model=model,
                kind="llm",
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                cache_hit_tokens=usage.cache_hit_tokens,
                cost_rmb=cost,
                peak=int(peak),
                meta="estimated" if usage.estimated else None,
            ))
            s.commit()
        logger.debug("LLM 入账: model=%s cost=%.4f 元", model, cost)
        return cost

    def record_tts(self, conversation_id: str | None, provider: str, model: str, chars: int) -> float:
        cost = self._pricing.char_cost(provider, model, chars)
        with self._db() as s:
            s.add(ApiUsage(
                conversation_id=conversation_id,
                provider=provider, model=model, kind="tts",
                chars=chars, cost_rmb=cost,
            ))
            s.commit()
        return cost

    def record_local(self, kind: str, model: str, conversation_id: str | None = None) -> None:
        """本地计算（STT/嵌入）记 0 元，报表里可见'省了多少钱'。"""
        with self._db() as s:
            s.add(ApiUsage(
                conversation_id=conversation_id,
                provider="local", model=model, kind=kind, cost_rmb=0.0,
            ))
            s.commit()

    # ---- 报表 ----

    def daily_report(self, days: int = 7) -> dict:
        """近 N 天报表（days=0 → 本月至今）。"""
        with self._db() as s:
            if days > 0:
                start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                from datetime import timedelta
                start = start - timedelta(days=days - 1)
                rows = s.scalars(
                    select(ApiUsage).where(ApiUsage.created_at >= start)
                ).all()
            else:
                month = _month()
                rows = s.scalars(
                    select(ApiUsage).where(
                        func.strftime("%Y-%m", ApiUsage.created_at) == month
                    )
                ).all()

        by_provider: dict[str, float] = {}
        by_day: dict[str, float] = {}
        by_kind: dict[str, float] = {}
        tokens = 0
        for r in rows:
            by_provider[r.provider] = by_provider.get(r.provider, 0) + r.cost_rmb
            by_kind[r.kind] = by_kind.get(r.kind, 0) + r.cost_rmb
            day = r.created_at.strftime("%Y-%m-%d")
            by_day[day] = by_day.get(day, 0) + r.cost_rmb
            tokens += r.input_tokens + r.output_tokens
        total = round(sum(by_provider.values()), 4)
        return {
            "days": days,
            "total_rmb": total,
            "total_tokens": tokens,
            "by_provider": {k: round(v, 4) for k, v in sorted(by_provider.items())},
            "by_kind": {k: round(v, 4) for k, v in sorted(by_kind.items())},
            "by_day": [{"date": k, "rmb": round(v, 4)} for k, v in sorted(by_day.items())],
        }

    # ---- 预算 ----

    def set_budget(self, provider: str, month: str | None, limit_rmb: float) -> None:
        month = month or _month()
        with self._db() as s:
            row = s.get(Budget, (provider, month))
            if row:
                row.limit_rmb = limit_rmb
            else:
                s.add(Budget(provider=provider, month=month, limit_rmb=limit_rmb))
            s.commit()

    def budget_status(self, provider: str = "total", month: str | None = None) -> dict:
        month = month or _month()
        with self._db() as s:
            row = s.get(Budget, (provider, month))
            if row is None:
                return {"provider": provider, "month": month, "limit_rmb": None, "spent_rmb": 0.0, "pct": 0.0}
            # provider=total 时统计全部；否则按 provider 过滤
            q = select(func.coalesce(func.sum(ApiUsage.cost_rmb), 0.0)).where(
                func.strftime("%Y-%m", ApiUsage.created_at) == month
            )
            if provider != "total":
                q = q.where(ApiUsage.provider == provider)
            spent = s.scalar(q) or 0.0
        limit = row.limit_rmb
        return {
            "provider": provider,
            "month": month,
            "limit_rmb": limit,
            "spent_rmb": round(spent, 4),
            "pct": round(spent / limit * 100, 1) if limit else 0.0,
        }
