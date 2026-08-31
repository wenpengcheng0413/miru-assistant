"""Low-risk Phase 7 Home Node transport probe."""
from __future__ import annotations

from ..base import Tool, ToolContext, ToolResult
from ...node_rpc import NodeRpcError


class HomeNodePingTool(Tool):
    name = "home_node_ping"
    description = "检查 Windows Home Node 是否在线，并返回协议版本、运行状态和节点时间。"
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    execution_location = "node-home"
    required_node = "node-home"
    timeout_s = 10.0
    max_result_chars = 2_000

    async def run(self, ctx: ToolContext) -> ToolResult:
        try:
            result = await ctx.services.node_rpc.execute(
                self.name,
                {},
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
                str(result.get("error") or "Home Node 工具执行失败"),
                error_code=str(result.get("error_code") or "node_job_failed"),
                retryable=bool(result.get("retryable", False)),
            )
        data = result.get("data")
        if not isinstance(data, dict):
            return ToolResult.failure(
                "Home Node 返回无效结果",
                error_code="invalid_node_result",
                retryable=False,
            )
        return ToolResult.success(data, summary="Home Node 响应正常")
