"""Cloud proxy tools for privacy-scoped Home Node WeChat reads."""
from __future__ import annotations

from ..base import Tool, ToolContext, ToolResult
from ...node_rpc import NodeRpcError


class WechatSearchMessagesNodeTool(Tool):
    name = "wechat_search_messages"
    description = (
        "在 Windows Home Node 上按精确联系人或群聊和关键词搜索最近微信消息。"
        "必须提供联系人/群聊、关键词和有限时间范围。"
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


class WechatConversationMessagesNodeTool(Tool):
    name = "wechat_conversation_messages"
    description = (
        "读取 Windows Home Node 上某个精确联系人或群聊最近一段时间的消息。"
        "每次返回一页；如果 has_more 为 true，可把 next_cursor 原样传回继续读取更早消息。"
        "适合用户要求查看、回顾或总结某个联系人/群聊，而不是关键词检索。"
        "如果消息页含 voice 类型且用户要求完整信息，还应调用 wechat_transcribe_voice。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "contact": {"type": "string", "description": "精确联系人备注、昵称或群名"},
            "days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 30},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 20},
            "cursor": {
                "type": "string",
                "description": "可选；上一页返回的 next_cursor。首次读取不要填写",
                "default": "",
            },
        },
        "required": ["contact"],
        "additionalProperties": False,
    }
    execution_location = "node-home"
    required_node = "node-home"
    permissions = ("wechat.read.messages",)
    timeout_s = 30.0
    max_result_chars = 12_000

    async def run(
        self,
        ctx: ToolContext,
        contact: str,
        days: int = 30,
        limit: int = 20,
        cursor: str = "",
    ) -> ToolResult:
        args = {"contact": contact, "days": days, "limit": limit, "cursor": cursor}
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
                str(result.get("error") or "微信会话读取失败"),
                error_code=str(result.get("error_code") or "wechat_read_failed"),
                retryable=bool(result.get("retryable", False)),
            )
        data = result.get("data")
        if not isinstance(data, dict):
            return ToolResult.failure(
                "Home Node 返回无效微信结果",
                error_code="invalid_node_result",
                retryable=False,
            )
        return ToolResult.success(
            data,
            summary=f"已读取微信会话消息 {len(data.get('messages', []))} 条",
        )


class WechatTranscribeVoiceNodeTool(Tool):
    name = "wechat_transcribe_voice"
    description = (
        "在 Windows Home Node 本机解码并识别指定联系人或群聊的微信语音消息。"
        "原始语音和 PCM 不离开本机，只返回转写文字。用户要求完整聊天信息、"
        "语音内容或会话页出现 voice 类型时使用；has_more 为 true 时可用 next_cursor 继续。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "contact": {"type": "string", "description": "精确联系人备注、昵称或群名"},
            "days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 30},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 10},
            "cursor": {"type": "string", "default": "", "description": "上一页 next_cursor"},
        },
        "required": ["contact"],
        "additionalProperties": False,
    }
    execution_location = "node-home"
    required_node = "node-home"
    permissions = ("wechat.read.voice",)
    timeout_s = 300.0
    max_result_chars = 12_000

    async def run(
        self,
        ctx: ToolContext,
        contact: str,
        days: int = 30,
        limit: int = 10,
        cursor: str = "",
    ) -> ToolResult:
        args = {"contact": contact, "days": days, "limit": limit, "cursor": cursor}
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
                str(result.get("error") or "微信语音转写失败"),
                error_code=str(result.get("error_code") or "wechat_voice_failed"),
                retryable=bool(result.get("retryable", False)),
            )
        data = result.get("data")
        if not isinstance(data, dict):
            return ToolResult.failure(
                "Home Node 返回无效语音结果",
                error_code="invalid_node_result",
                retryable=False,
            )
        return ToolResult.success(
            data,
            summary=(
                f"已在本机转写微信语音 "
                f"{data.get('transcribed', 0)}/{len(data.get('voice_messages', []))} 条"
            ),
        )
