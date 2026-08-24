"""Tool 基类与结果模型（设计见 docs/04-Tool与Skill系统.md §2）。"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, ClassVar

# 防止循环导入：ToolContext 用 Any 引用 Services
@dataclass
class ToolContext:
    services: Any                       # miru_server.services.Services
    conversation_id: str
    emit: Callable[[dict], Awaitable[None]] = field(default=lambda _: _noop())


async def _noop(_: dict) -> None:
    return None


@dataclass
class ToolResult:
    ok: bool
    data: Any = None                    # 序列化为 JSON 回填给 LLM
    summary: str = ""                   # 给人看的一句话状态（tool_end 事件）
    error: str = ""                     # ok=False 时的错误说明（同样会给 LLM）

    def to_llm(self, max_chars: int = 8000) -> str:
        """裁剪后的 JSON 字符串（回填 LLM 的 tool 消息内容）。"""
        payload = {"ok": self.ok, "data": self.data}
        if not self.ok and self.error:
            payload["error"] = self.error
        text = json.dumps(payload, ensure_ascii=False, default=str)
        if len(text) > max_chars:
            text = text[:max_chars] + f"…(已截断，原长度 {len(text)})"
        return text

    @classmethod
    def success(cls, data: Any, summary: str = "完成") -> "ToolResult":
        return cls(ok=True, data=data, summary=summary)

    @classmethod
    def failure(cls, error: str) -> "ToolResult":
        return cls(ok=False, data=None, summary="失败", error=error)


class Tool(ABC):
    """一个工具 = 一个类。注册即对 LLM 可见（受 settings.tools.enabled 白名单约束）。"""

    name: ClassVar[str]                      # 函数名（LLM 调用用）
    description: ClassVar[str]               # 中文描述：干什么、何时用
    parameters: ClassVar[dict] = {           # JSON Schema
        "type": "object",
        "properties": {},
    }
    require_confirm: ClassVar[bool] = False  # 高危工具需用户确认（MVP2+）
    max_result_chars: ClassVar[int] = 8000

    @abstractmethod
    async def run(self, ctx: ToolContext, **kwargs) -> ToolResult: ...

    @classmethod
    def schema(cls) -> dict:
        """OpenAI function calling 格式。"""
        return {
            "type": "function",
            "function": {
                "name": cls.name,
                "description": cls.description,
                "parameters": cls.parameters,
            },
        }
