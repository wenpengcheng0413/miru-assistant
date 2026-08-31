"""工具注册表：自动发现内置工具 + 白名单过滤 + 带超时执行。"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from typing import Any

from ..core.events import tool_end as tool_end_event
from ..core.events import tool_start as tool_start_event
from .base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_TOOL_TIMEOUT_S = 30.0


class ToolRegistry:
    def __init__(
        self,
        tools: list[type[Tool]] | None = None,
        enabled: list[str] | None = None,
        *,
        profile: str = "development",
    ):
        self._all: dict[str, type[Tool]] = {t.name: t for t in (tools or [])}
        self._enabled: set[str] = set(enabled) if enabled is not None else set(self._all)
        self.profile = profile
        self._home_node = None
        # 白名单里提到但不存在的名字 → 告警
        for name in self._enabled - set(self._all):
            logger.warning("tools.enabled 里没有实现 %s，已忽略", name)

    @property
    def enabled_names(self) -> list[str]:
        names = sorted(n for n in self._enabled if n in self._all)
        if self.profile == "cloud":
            snapshot = self._home_node.snapshot() if self._home_node is not None else None
            names = [n for n in names if (
                self._all[n].metadata().get("execution_location") != "node-home"
                or (
                    snapshot is not None
                    and snapshot.state == "online"
                    and n in snapshot.capabilities
                )
            )]
        return names

    def bind_home_node(self, home_node: Any) -> None:
        self._home_node = home_node

    def get(self, name: str) -> type[Tool] | None:
        if name in self._enabled:
            return self._all.get(name)
        return None

    def schemas(self) -> list[dict]:
        """发给 LLM 的工具 schema（只含启用的）。"""
        return [self._all[n].schema() for n in self.enabled_names]

    def list_all(self) -> list[dict]:
        available = set(self.enabled_names)
        return [
            {
                "name": n,
                "enabled": n in available,
                "description": t.description,
                **t.metadata(),
            }
            for n, t in sorted(self._all.items())
        ]

    async def execute(self, ctx: ToolContext, name: str, args: dict) -> ToolResult:
        declared_cls = self._all.get(name)
        metadata = declared_cls.metadata() if declared_cls else None
        if (
            self.profile == "cloud"
            and metadata is not None
            and metadata.get("execution_location") == "node-home"
            and self._home_node is None
        ):
            return ToolResult.failure(
                "Home Node 未配置",
                error_code="node_not_configured",
                retryable=False,
            )
        tool_cls = self.get(name)
        call_id = args.pop("_call_id", "") or name
        if tool_cls is None:
            return ToolResult.failure(
                f"工具 {name} 未启用或不存在",
                error_code="tool_not_available",
                retryable=False,
            )

        await ctx.emit(tool_start_event(call_id, name, args))
        started = time.monotonic()
        try:
            call_ctx = replace(ctx, rpc_job_id=call_id)
            result = await asyncio.wait_for(
                tool_cls().run(call_ctx, **args), timeout=float(getattr(tool_cls, "timeout_s", DEFAULT_TOOL_TIMEOUT_S))
            )
        except asyncio.TimeoutError:
            timeout_s = float(getattr(tool_cls, "timeout_s", DEFAULT_TOOL_TIMEOUT_S))
            result = ToolResult.failure(
                f"工具 {name} 执行超时（>{timeout_s:.0f}s），可缩小时间范围或分批查询",
                error_code="tool_timeout",
                retryable=True,
            )
        except Exception as exc:
            # Exception messages can contain provider responses or user data;
            # keep production logs structured and value-free.
            logger.error(
                "工具执行异常: tool=%s exception_type=%s error_code=tool_failed",
                name,
                type(exc).__name__,
            )
            result = ToolResult.failure(
                f"工具 {name} 执行异常",
                error_code="tool_failed",
                retryable=False,
            )
        duration_ms = int((time.monotonic() - started) * 1000)
        await ctx.emit(
            tool_end_event(
                call_id,
                name,
                result.ok,
                result.summary,
                duration_ms,
                result.error,
            )
        )
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
    from .builtin.home_node import HomeNodePingTool
    enabled = list(config.tools.enabled)
    tools: list[type[Tool]] = [
        GetCurrentTimeTool,
        MemorySetTool,
        MemoryGetTool,
        MemoryListTool,
        MemoryDeleteTool,
        MemorySearchTool,
        ApiCostReportTool,
        ApiBudgetSetTool,
        HomeNodePingTool,
    ]
    profile = getattr(config, "profile", "development")
    if profile == "cloud":
        from .builtin.wechat_node import (
            WechatConversationMessagesNodeTool,
            WechatOriginalImagesNodeTool,
            WechatSearchMessagesNodeTool,
            WechatTranscribeVoiceNodeTool,
        )

        tools.extend([
            WechatSearchMessagesNodeTool,
            WechatConversationMessagesNodeTool,
            WechatTranscribeVoiceNodeTool,
            WechatOriginalImagesNodeTool,
        ])
    else:
        from .builtin.wechat import (
            WechatChatStatsTool,
            WechatContactListTool,
            WechatGroupDigestTool,
            WechatGroupListTool,
            WechatRecentActivityTool,
            WechatRecentMessagesTool,
            WechatRecentContactsTool,
            WechatConversationDigestTool,
            WechatDatasetPageTool,
            WechatSearchMessagesTool,
            WechatTranscribeVoiceTool,
            WechatImageAnalysisTool,
        )

        # 旧 settings.yaml 只列出旧微信工具时，自动启用新的固定工作流，
        # 这样升级服务端无需手工编辑被忽略的本机配置文件。
        if any(name.startswith("wechat_") for name in enabled):
            enabled.extend([
                "wechat_recent_contacts", "wechat_conversation_digest", "wechat_dataset_page",
                "wechat_recent_activity", "wechat_image_analysis",
            ])
        tools.extend([
            WechatContactListTool,
            WechatRecentActivityTool,
            WechatChatStatsTool,
            WechatSearchMessagesTool,
            WechatRecentMessagesTool,
            WechatRecentContactsTool,
            WechatConversationDigestTool,
            WechatDatasetPageTool,
            WechatTranscribeVoiceTool,
            WechatImageAnalysisTool,
            WechatGroupListTool,
            WechatGroupDigestTool,
        ])
    return ToolRegistry(tools=tools, enabled=enabled, profile=profile)
