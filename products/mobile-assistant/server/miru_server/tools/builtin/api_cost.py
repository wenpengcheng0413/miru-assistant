"""API 成本工具：Miru 自己会算账（Q14）。"""
from __future__ import annotations

import asyncio

from ..base import Tool, ToolContext, ToolResult


class ApiCostReportTool(Tool):
    name = "api_cost_report"
    description = (
        "查询 AI API 花费：总额、按服务商/按模型分桶、按天趋势。"
        "用户问'这个月花了多少钱/最近七天消耗/哪个模型最贵'时使用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "统计最近 N 天（1-31）；0 表示本月至今",
                "default": 7,
            },
        },
    }

    async def run(self, ctx: ToolContext, days: int = 7) -> ToolResult:
        report = await asyncio.to_thread(ctx.services.cost.daily_report, days)
        return ToolResult.success(report, summary=f"近 {days} 天 API 花费 {report['total_rmb']} 元")


class ApiBudgetSetTool(Tool):
    name = "api_budget_set"
    description = (
        "设置月度 API 预算（元）。用户说'这个月预算控制在 XX 元以内'时使用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "limit_rmb": {"type": "number", "description": "预算上限（元）"},
            "provider": {
                "type": "string",
                "enum": ["total", "deepseek", "minimax"],
                "description": "total=总预算，deepseek=DeepSeek，minimax=TTS",
                "default": "total",
            },
        },
        "required": ["limit_rmb"],
    }

    async def run(self, ctx: ToolContext, limit_rmb: float, provider: str = "total") -> ToolResult:
        await asyncio.to_thread(ctx.services.cost.set_budget, provider, None, limit_rmb)
        return ToolResult.success(
            {"provider": provider, "limit_rmb": limit_rmb},
            summary=f"已设置 {provider} 月度预算 {limit_rmb:.0f} 元",
        )
