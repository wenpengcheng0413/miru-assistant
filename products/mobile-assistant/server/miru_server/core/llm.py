"""DeepSeek 流式客户端（OpenAI 兼容协议）——含流式 tool_calls 分片拼接。

要点（2026-08 调研确认）：
- model=deepseek-v4-flash（自动指向 0731）；1M 上下文
- 语音场景必须关闭思考模式（thinking 默认开启，推理 token 按输出计费）
- 流式工具调用：delta.tool_calls 按 index 归并，function.arguments 逐片拼接
- stream_options.include_usage → 末帧带真实 token 用量（成本入账用）
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

from ..config import LLMConfig

logger = logging.getLogger(__name__)

RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)
RETRY_DELAYS = (2.0, 8.0)


@dataclass
class Usage:
    prompt_tokens: int
    completion_tokens: int
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    estimated: bool = False

    def to_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cache_hit_tokens": self.cache_hit_tokens,
            "cache_miss_tokens": self.cache_miss_tokens,
            "estimated": self.estimated,
        }


@dataclass
class ToolCallSpec:
    id: str
    name: str
    arguments: dict


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCallsDone:
    calls: list[ToolCallSpec]


@dataclass
class Done:
    usage: Usage
    finish_reason: str | None = None


@dataclass
class StreamError:
    message: str


LLMEvent = TextDelta | ToolCallsDone | Done | StreamError


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._client = AsyncOpenAI(
            api_key=cfg.api_key or "missing-key",  # 占位，空 key 时首次调用报错并提示
            base_url=cfg.base_url,
            timeout=cfg.timeout_s,
            max_retries=0,  # 重试策略自己控制（流式中途重试 SDK 行为不可控）
        )

    @property
    def model(self) -> str:
        return self.cfg.model

    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        tool_choice: str | dict | None = None,
    ) -> AsyncIterator[LLMEvent]:
        """流式对话。可能的事件：TextDelta* → (ToolCallsDone) → Done；失败时 StreamError。"""
        kwargs = {
            "model": model or self.cfg.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": self.cfg.temperature,
            "max_tokens": max_tokens or self.cfg.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        # DeepSeek V4 uses type=enabled/disabled. The older enabled=false
        # form triggers a 400 and deleting it re-enables hidden reasoning.
        thinking_override = True
        kwargs["extra_body"] = {
            "thinking": {"type": "enabled" if self.cfg.thinking else "disabled"}
        }

        last_error = "未知错误"
        for attempt in range(3):
            try:
                visible = False
                tool_calls = False
                usage: Usage | None = None
                finish_reason: str | None = None
                async for ev in self._stream_once(kwargs):
                    if isinstance(ev, TextDelta):
                        visible = visible or bool(ev.text.strip())
                        yield ev
                    elif isinstance(ev, ToolCallsDone):
                        tool_calls = True
                        yield ev
                    elif isinstance(ev, Done):
                        usage = ev.usage
                        finish_reason = ev.finish_reason
                # 某些网关在 thinking 参数被拒后仍只返回推理 token，
                # 消耗满 max_tokens 却不给 content。扩大上限再试一次，
                # 不能让客户端静默收到空回复。
                if visible or tool_calls:
                    if usage is not None:
                        yield Done(usage, finish_reason)
                    return
                if attempt < 2:
                    kwargs["max_tokens"] = min(max(int(kwargs["max_tokens"]) * 2, 4096), self.cfg.max_tokens)
                    kwargs.pop("extra_body", None)
                    logger.warning("LLM 返回空可见内容，扩大输出上限后重试（max_tokens=%s）", kwargs["max_tokens"])
                    continue
                yield StreamError("模型返回了空内容，请稍后重试（可能被思考 token 占满输出上限）")
                return
            except BadRequestError as e:
                # 老网关不认 thinking 参数 → 去掉重试一次
                if thinking_override and "thinking" in str(e).lower():
                    logger.warning("API 不接受 thinking 参数，去掉后重试")
                    kwargs.pop("extra_body", None)
                    thinking_override = False
                    continue
                last_error = f"请求被拒: {e}"
                break  # 400 不重试
            except AuthenticationError as e:
                last_error = f"API key 无效: {e}"
                break
            except RETRYABLE as e:
                last_error = f"{type(e).__name__}: {e}"
                if attempt < 2:
                    await asyncio.sleep(RETRY_DELAYS[attempt])
                    continue
            except Exception as e:  # 网络/解析等杂项
                last_error = f"{type(e).__name__}: {e}"
                if attempt < 2:
                    await asyncio.sleep(RETRY_DELAYS[attempt])
                    continue
        yield StreamError(f"LLM 不可用（{last_error}）")

    async def _stream_once(self, kwargs: dict) -> AsyncIterator[LLMEvent]:
        stream = await self._client.chat.completions.create(**kwargs)

        # 流式工具调用：按 index 归并分片
        acc: dict[int, dict] = {}
        usage: Usage | None = None
        finish_reason: str | None = None

        async for chunk in stream:
            if chunk.usage is not None:
                u = chunk.usage
                usage = Usage(
                    prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(u, "completion_tokens", 0) or 0,
                    cache_hit_tokens=getattr(u, "prompt_cache_hit_tokens", 0) or 0,
                    cache_miss_tokens=getattr(u, "prompt_cache_miss_tokens", 0) or 0,
                )
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                finish_reason = choice.finish_reason
            delta = choice.delta
            if delta.content:
                yield TextDelta(delta.content)
            for tc in delta.tool_calls or []:
                slot = acc.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function.arguments:
                        slot["arguments"] += tc.function.arguments
            if choice.finish_reason == "tool_calls":
                yield ToolCallsDone(calls=[_parse_call(s) for s in acc.values()])
                acc = {}

        # 用量兜底：估算（约 1 token ≈ 3.5 中文汉字 → 用 /3 保守）
        if usage is None:
            prompt_chars = sum(len(str(m.get("content", ""))) for m in kwargs["messages"])
            usage = Usage(
                prompt_tokens=prompt_chars // 3,
                completion_tokens=0,
                estimated=True,
            )
        yield Done(usage, finish_reason)


    async def chat_json(self, system: str, user: str, temperature: float = 0.1) -> dict:
        """一次性 JSON 模式调用（记忆提取等结构化任务用）。"""
        kwargs = {
            "model": self.cfg.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": temperature,
            "max_tokens": min(self.cfg.max_tokens, 1000),
        }
        kwargs["extra_body"] = {
            "thinking": {"type": "enabled" if self.cfg.thinking else "disabled"}
        }
        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except BadRequestError as e:
            if "thinking" in str(e).lower() and kwargs.get("extra_body"):
                kwargs.pop("extra_body")
                resp = await self._client.chat.completions.create(**kwargs)
            else:
                raise
        text = resp.choices[0].message.content or "{}"
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("chat_json 解析失败: %s", text[:200])
            return {}

    async def vision_chat(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """对包含 image_url 内容块的消息做一次视觉问答。

        复用流式客户端的重试、thinking 兼容和错误处理逻辑；该方法只返回
        可见文本，适合由本地工具在用户明确要求时调用视觉模型。
        """
        parts: list[str] = []
        async for event in self.stream_chat(
            messages,
            tools=None,
            model=model or self.cfg.vision_model,
            max_tokens=max_tokens or min(self.cfg.max_tokens, 1200),
        ):
            if isinstance(event, TextDelta):
                parts.append(event.text)
            elif isinstance(event, StreamError):
                raise RuntimeError(event.message)
        return "".join(parts).strip()


def _parse_call(slot: dict) -> ToolCallSpec:
    try:
        args = json.loads(slot["arguments"] or "{}")
    except json.JSONDecodeError:
        args = {"_raw": slot["arguments"]}
    return ToolCallSpec(id=slot["id"] or "", name=slot["name"] or "", arguments=args)


def tool_result_message(call: ToolCallSpec, result_json: str) -> dict:
    """OpenAI 协议：工具执行结果回填消息。"""
    return {"role": "tool", "tool_call_id": call.id, "content": result_json}


def assistant_toolcall_message(calls: list[ToolCallSpec]) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)},
            }
            for c in calls
        ],
    }
