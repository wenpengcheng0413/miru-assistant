"""Cloud proxy tools for privacy-scoped Home Node WeChat reads."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ...attachments import image_metadata, vision_image_blocks
from ...node_rpc import NodeRpcError
from ..base import Tool, ToolContext, ToolResult


_MEDIA_ID = re.compile(r"^[a-f0-9]{32}$")


def _node_media_path(ctx: ToolContext, item: dict) -> Path | None:
    media_id = str(item.get("id") or "")
    if not _MEDIA_ID.fullmatch(media_id):
        return None
    root = (
        ctx.services.config.resolve(ctx.services.config.attachments.dir)
        / "node-media"
    ).resolve()
    meta_path = root / f"{media_id}.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        expires = datetime.fromisoformat(str(meta.get("expires_at") or ""))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            return None
        if str(meta.get("conversation_id") or "") != ctx.conversation_id:
            return None
        path = (root / str(meta.get("file_name") or "")).resolve()
    except Exception:
        return None
    return path if path.is_file() and path.parent == root else None


async def _analyze_node_image(ctx: ToolContext, item: dict) -> None:
    path = _node_media_path(ctx, item)
    if path is None:
        item["analyzed"] = False
        item["analysis_error"] = "原图不可用于视觉分析"
        return
    try:
        metadata = image_metadata(path)
        prompt = (
            "请用中文客观分析这张微信原图的具体含义。先看全图，再结合高清局部，"
            "逐项识别人、物体、场景、界面状态和文字；文字请尽量准确转写。"
            f"图片像素为 {metadata.get('width') or '未知'}×{metadata.get('height') or '未知'}。"
            "区分可确认事实与推测；像素不足时明确说看不清，禁止猜测。控制在 400 字以内。"
        )
        description = await ctx.services.llm.vision_chat(
            [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    *vision_image_blocks(path),
                ],
            }],
            model=ctx.services.config.llm.vision_model,
            max_tokens=700,
        )
        item["description"] = description
        item["analyzed"] = bool(description)
        if not description:
            item["analysis_error"] = "视觉模型返回空内容"
    except Exception as exc:
        item["analyzed"] = False
        item["analysis_error"] = f"视觉模型分析失败：{str(exc)[:120]}"


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


class WechatOriginalImagesNodeTool(Tool):
    name = "wechat_original_images"
    description = (
        "按需从 Windows Home Node 提取指定联系人或群聊的微信原图。"
        "原图通过加密连接传到 Cloud 的短期媒体区，24 小时后自动过期；"
        "Cloud 会使用视觉模型逐张分析具体内容，并返回可由 Miru App 鉴权显示、点击放大的图片。"
        "用户要求照片、图片、截图、图中文字/含义或完整聊天媒体时必须使用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "contact": {"type": "string", "description": "精确联系人备注、昵称或群名"},
            "days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 7},
            "limit": {"type": "integer", "minimum": 1, "maximum": 3, "default": 3},
            "cursor": {"type": "string", "default": "", "description": "上一页 next_cursor"},
        },
        "required": ["contact"],
        "additionalProperties": False,
    }
    execution_location = "node-home"
    required_node = "node-home"
    permissions = ("wechat.read.images",)
    timeout_s = 120.0
    max_result_chars = 10_000

    async def run(
        self,
        ctx: ToolContext,
        contact: str,
        days: int = 7,
        limit: int = 3,
        cursor: str = "",
    ) -> ToolResult:
        args = {
            "contact": contact,
            "days": days,
            "limit": limit,
            "cursor": cursor,
            "conversation_id": ctx.conversation_id,
        }
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
                str(result.get("error") or "微信原图读取失败"),
                error_code=str(result.get("error_code") or "wechat_image_failed"),
                retryable=bool(result.get("retryable", False)),
            )
        data = result.get("data")
        if not isinstance(data, dict):
            return ToolResult.failure(
                "Home Node 返回无效图片结果",
                error_code="invalid_node_result",
                retryable=False,
            )
        visible = [item for item in data.get("images", []) if item.get("download_path")]
        for item in visible:
            await _analyze_node_image(ctx, item)
        data["analyzed"] = sum(bool(item.get("analyzed")) for item in visible)
        return ToolResult.success(
            data,
            summary=(
                f"已提取微信原图 {len(visible)} 张并分析 {data['analyzed']} 张"
                "（原图链接 24 小时有效）"
            ),
        )
