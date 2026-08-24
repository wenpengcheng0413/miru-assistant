"""记忆工具：Miru 通过它们读写长期记忆（用户也可在设置页直接管理）。"""
from __future__ import annotations

import asyncio

from ..base import Tool, ToolContext, ToolResult

SCOPES = ("profile", "preferences", "projects", "knowledge")


class MemorySetTool(Tool):
    name = "memory_set"
    description = (
        "写入长期记忆。scope 取值：profile=用户画像(职业/称呼/常联系人等稳定事实)、"
        "preferences=用户偏好(回答详略/语气/提醒方式)、projects=进行中的项目(名称/状态)、"
        "knowledge=用户主动要求记住的知识。value 用一句话写清。"
        "当用户说'记住…'或对话中出现值得长期记住的稳定信息时使用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "scope": {"type": "string", "enum": list(SCOPES)},
            "key": {"type": "string", "description": "条目名，如 '称呼' / '回答详细程度'"},
            "value": {"type": "string", "description": "条目内容"},
        },
        "required": ["scope", "key", "value"],
    }

    async def run(self, ctx: ToolContext, scope: str, key: str, value: str) -> ToolResult:
        store = ctx.services.memory
        await asyncio.to_thread(store.set, scope, key, value, source="llm")
        return ToolResult.success({"scope": scope, "key": key}, summary=f"已记住：{key}")


class MemoryGetTool(Tool):
    name = "memory_get"
    description = "读取一条长期记忆（scope 同 memory_set）。不确定有哪些内容时先 memory_list。"
    parameters = {
        "type": "object",
        "properties": {
            "scope": {"type": "string", "enum": list(SCOPES)},
            "key": {"type": "string"},
        },
        "required": ["scope", "key"],
    }

    async def run(self, ctx: ToolContext, scope: str, key: str) -> ToolResult:
        entry = await asyncio.to_thread(ctx.services.memory.get, scope, key)
        if entry is None:
            return ToolResult.success(None, summary=f"没有 {scope}/{key} 这条记忆")
        return ToolResult.success(entry, summary=f"已读取记忆：{key}")


class MemoryListTool(Tool):
    name = "memory_list"
    description = "列出某个 scope 下的全部记忆（回答'你记得我什么'之类问题时使用）。"
    parameters = {
        "type": "object",
        "properties": {"scope": {"type": "string", "enum": list(SCOPES)}},
        "required": ["scope"],
    }

    async def run(self, ctx: ToolContext, scope: str) -> ToolResult:
        entries = await asyncio.to_thread(ctx.services.memory.list, scope)
        return ToolResult.success(entries, summary=f"{scope} 共 {len(entries)} 条记忆")


class MemoryDeleteTool(Tool):
    name = "memory_delete"
    description = "删除一条长期记忆。用户明确说'忘掉/删掉记忆'时使用。"
    parameters = {
        "type": "object",
        "properties": {
            "scope": {"type": "string", "enum": list(SCOPES)},
            "key": {"type": "string"},
        },
        "required": ["scope", "key"],
    }

    async def run(self, ctx: ToolContext, scope: str, key: str) -> ToolResult:
        removed = await asyncio.to_thread(ctx.services.memory.delete, scope, key)
        if removed:
            return ToolResult.success(True, summary=f"已删除记忆：{key}")
        return ToolResult.success(False, summary=f"没有 {scope}/{key} 这条记忆")


class MemorySearchTool(Tool):
    name = "memory_search"
    description = "在全部记忆中按关键词搜索（用户问'我是不是说过…'时使用）。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "limit": {"type": "integer", "description": "最多返回条数", "default": 10},
        },
        "required": ["query"],
    }

    async def run(self, ctx: ToolContext, query: str, limit: int = 10) -> ToolResult:
        hits = await asyncio.to_thread(ctx.services.memory.search, query, limit)
        return ToolResult.success(hits, summary=f"搜到 {len(hits)} 条相关记忆")
