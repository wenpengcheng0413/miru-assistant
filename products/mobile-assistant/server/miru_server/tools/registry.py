"""工具注册表：自动发现内置工具 + 白名单过滤 + 带超时执行。"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ..core.events import tool_end as tool_end_event
from ..core.events import tool_start as tool_start_event
from .base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_TOOL_TIMEOUT_S = 30.0


class ToolRegistry:
    def __init__(self, tools: list[type[Tool]] | None = None, enabled: list[str] | None = None):
        self._all: dict[str, type[Tool]] = {t.name: t for t in (tools or [])}
        self._enabled: set[str] = set(enabled) if enabled is not None else set(self._all)
        # 白名单里提到但不存在的名字 → 告警
        for name in self._enabled - set(self._all):
            logger.warning("tools.enabled 里没有实现 %s，已忽略", name)

    @property
    def enabled_names(self) -> list[str]:
        return sorted(n for n in self._enabled if n in self._all)

    def get(self, name: str) -> type[Tool] | None:
        if name in self._enabled:
            return self._all.get(name)
        return None

    def schemas(self) -> list[dict]:
        """发给 LLM 的工具 schema（只含启用的）。"""
        return [self._all[n].schema() for n in self.enabled_names]

    def list_all(self) -> list[dict]:
        return [
            {"name": n, "enabled": n in self._enabled, "description": t.description}
            for n, t in sorted(self._all.items())
        ]

    async def execute(self, ctx: ToolContext, name: str, args: dict) -> ToolResult:
        tool_cls = self.get(name)
        call_id = args.pop("_call_id", "") or name
        if tool_cls is None:
            return ToolResult.failure(f"工具 {name} 未启用或不存在")

        await ctx.emit(tool_start_event(call_id, name, args))
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                tool_cls().run(ctx, **args), timeout=DEFAULT_TOOL_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            result = ToolResult.failure(f"工具 {name} 执行超时（>{DEFAULT_TOOL_TIMEOUT_S:.0f}s）")
        except Exception as e:
            logger.exception("工具 %s 执行异常", name)
            result = ToolResult.failure(f"工具 {name} 执行异常: {e}")
        duration_ms = int((time.monotonic() - started) * 1000)
        await ctx.emit(tool_end_event(call_id, name, result.ok, result.summary, duration_ms))
        return result


def build_registry(config: Any) -> ToolRegistry:
    """扫描内置工具并应用白名单。新增工具：在 builtin/ 里加一个 Tool 子类即可。"""
    from .builtin.api_cost import ApiBudgetSetTool, ApiCostReportTool
    from .builtin.memory import (
        MemoryDeleteTool,
        MemoryGetTool,
        MemoryListTool,
        MemorySearchTool,
        MemorySetTool,
    )
    from .builtin.system import GetCurrentTimeTool
    from .builtin.wechat import (
        WechatChatStatsTool,
        WechatContactListTool,
        WechatGroupDigestTool,
        WechatGroupListTool,
        WechatRecentMessagesTool,
        WechatSearchMessagesTool,
        WechatTranscribeVoiceTool,
    )

    return ToolRegistry(
        tools=[
            GetCurrentTimeTool,
            MemorySetTool,
            MemoryGetTool,
            MemoryListTool,
            MemoryDeleteTool,
            MemorySearchTool,
            ApiCostReportTool,
            ApiBudgetSetTool,
            WechatContactListTool,
            WechatChatStatsTool,
            WechatSearchMessagesTool,
            WechatRecentMessagesTool,
            WechatTranscribeVoiceTool,
            WechatGroupListTool,
            WechatGroupDigestTool,
        ],
        enabled=config.tools.enabled,
    )
