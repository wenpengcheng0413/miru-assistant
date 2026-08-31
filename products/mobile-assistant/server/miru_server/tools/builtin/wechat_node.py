"""Cloud proxy tools for privacy-scoped Home Node WeChat reads."""
from __future__ import annotations

from ..base import Tool, ToolContext, ToolResult
from ...node_rpc import NodeRpcError


class WechatSearchMessagesNodeTool(Tool):
    name = "wechat_search_messages"
    description = (
        "在 Windows Home Node 上按精确联系人和关键词搜索最近微信消息。"
        "当前仅支持一对一联系人；必须提供联系人、关键词和有限时间范围。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "contact": {"type": "string", "description": "精确联系人备注、昵称或微信号"},
            "keyword": {"type": "string", "description": "必须出现的搜索关键词"},
            "days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 30},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
        },
        "required": ["contact", "keyword"],
        "additionalProperties": False,
    }
    execution_location = "node-home"
    required_node = "node-home"
    permissions = ("wechat.read.messages",)
    timeout_s = 30.0
    max_result_chars = 10_000

    async def run(
        self,
        ctx: ToolContext,
        contact: str,
        keyword: str,
        days: int = 30,
        limit: int = 10,
    ) -> ToolResult:
        args = {"contact": contact, "keyword": keyword, "days": days, "limit": limit}
        try:
            result = await ctx.services.node_rpc.execute(
                self.name,
                args,
                timeout_s=self.timeout_s,
                job_id=ctx.rpc_job_id or ctx.turn_id,
            )
        except NodeRpcError as exc:
            return ToolResult.failure(
                exc.message,
                error_code=exc.error_code,
                retryable=exc.retryable,
            )
        if result.get("ok") is not True:
            return ToolResult.failure(
                str(result.get("error") or "微信消息搜索失败"),
                error_code=str(result.get("error_code") or "wechat_search_failed"),
                retryable=bool(result.get("retryable", False)),
            )
        data = result.get("data")
        if not isinstance(data, dict):
            return ToolResult.failure(
                "Home Node 返回无效微信结果",
                error_code="invalid_node_result",
                retryable=False,
            )
        return ToolResult.success(data, summary=f"微信关键词搜索命中 {data.get('total_hits', 0)} 条")
