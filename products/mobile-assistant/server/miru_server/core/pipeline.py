"""会话管线：用户输入 → (预算检查) → DeepSeek 流式(工具循环) → 句级 TTS → 落库/成本/记忆。

每轮对话的完整主循环；每个 WS 连接持有一个 AgentPipeline 实例。
打断：WS 层 cancel 当前 run 任务即可（TTS 队列随 run 释放）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from sqlalchemy import select

from . import events
from .llm import (
    Done,
    StreamError,
    TextDelta,
    ToolCallsDone,
    assistant_toolcall_message,
    tool_result_message,
)
from .splitter import SentenceSplitter
from ..attachments import image_content_block
from ..db.models import Attachment, Conversation, Message, ToolCall, utcnow
from ..memory.extractor import MemoryExtractor
from ..persona.builder import Persona
from ..services import Services
from ..tools.base import ToolContext
from ..tts.queue import TTSQueue

logger = logging.getLogger(__name__)


@dataclass
class SessionContext:
    """一个 WS 连接的会话状态（同时充当 EventSink：send_json/send_audio 由 WS 层注入）。"""
    conversation_id: str
    persona_name: str
    persona: Persona
    mode: str = "text"                    # text | voice
    synth_tts: bool = True                # 文本模式默认不合成（省 TTS 费用）
    auto_run: bool = True                 # voice 模式：识别后自动进管线；false=等客户端确认/修改后 text_input
    tts_format: str = "mp3"
    tts_sample_rate: int = 32000
    send_json: Callable[[dict], Awaitable[None]] | None = None
    send_audio: Callable[[bytes], Awaitable[None]] | None = None
    stt_latency_ms: int = 0
    turn_running: bool = field(default=False, init=False)
    created_at: float = field(default_factory=time.time)


class AgentPipeline:
    def __init__(self, services: Services):
        self.services = services
        self.extractor = MemoryExtractor(services.llm, services.memory)

    # ------------------------------------------------------------------ 主流程

    async def run(self, ctx: SessionContext, user_text: str, attachment_ids: list[str] | None = None) -> None:
        cfg = self.services.config
        sink = ctx
        ctx.turn_running = True
        await self.ensure_conversation(ctx)

        # 预算检查（hard_block 时直接拒绝）
        note = await self._budget_note()
        if note:
            await self._send(ctx, "json", note)
            if note["type"] == "error":
                return

        # 组装上下文（先读历史，再存本条用户消息，避免重复）
        system_prompt = await asyncio.to_thread(self._build_system_prompt, ctx)
        history = await asyncio.to_thread(self._load_history, ctx.conversation_id)
        try:
            attachments = await asyncio.to_thread(
                self._load_attachments, ctx.conversation_id, attachment_ids or []
            )
            model_name, user_content, stored_text = await asyncio.to_thread(
                self._build_user_content, user_text, attachments
            )
        except (OSError, ValueError) as e:
            await self._send(ctx, "json", events.error("attachment_unavailable", str(e)))
            ctx.turn_running = False
            return
        await self._send(ctx, "json", events.user_text(user_text))
        await asyncio.to_thread(self._save_message, ctx.conversation_id, "user", stored_text)
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": user_content},
        ]
        schemas = self.services.tools.schemas() or None

        # TTS 队列（仅需要合成且 provider 可用时）
        tts: TTSQueue | None = None
        if ctx.synth_tts and self.services.tts_provider is not None:

            def _record_tts(provider: str, chars: int) -> None:
                # MiniMax 按配置的 model 计费；edge 兜底免费（记 0 元，报表可见）
                model = (
                    self.services.config.tts.minimax.model
                    if provider == "minimax"
                    else provider
                )
                self.services.cost.record_tts(ctx.conversation_id, provider, model, chars)

            tts = TTSQueue(
                sink=ctx,
                provider=self.services.tts_provider,
                fallback=self.services.tts_fallback,
                voice=ctx.persona.voice,
                audio_format=ctx.tts_format,
                sample_rate=ctx.tts_sample_rate,
                record_cost=_record_tts,
            )

        splitter = SentenceSplitter()
        last_feed = [time.monotonic()]   # 用列表共享引用给周期冲刷任务
        flusher = asyncio.create_task(self._periodic_flush(splitter, tts, last_feed))
        assistant_parts: list[str] = []
        usage = None

        try:
            for _round_no in range(cfg.llm.max_tool_rounds):
                calls = []
                async for ev in self.services.llm.stream_chat(messages, schemas, model=model_name):
                    if isinstance(ev, TextDelta):
                        assistant_parts.append(ev.text)
                        await self._send(ctx, "json", events.llm_delta(ev.text))
                        if tts:
                            for sentence in splitter.feed(ev.text):
                                tts.enqueue(sentence)
                        last_feed[0] = time.monotonic()
                    elif isinstance(ev, ToolCallsDone):
                        calls = ev.calls
                    elif isinstance(ev, Done):
                        usage = ev.usage
                    elif isinstance(ev, StreamError):
                        await self._send(ctx, "json", events.error("llm_unavailable", ev.message))
                        return
                if tts:
                    for sentence in splitter.flush(force=True):
                        tts.enqueue(sentence)

                if not calls:
                    break  # 正常结束

                # 执行工具并把结果回填
                tool_msgs = []
                for call in calls:
                    result = await self.services.tools.execute(
                        ToolContext(
                            services=self.services,
                            conversation_id=ctx.conversation_id,
                            emit=lambda p: self._send(ctx, "json", p),
                        ),
                        call.name,
                        dict(call.arguments, _call_id=call.id),
                    )
                    await asyncio.to_thread(
                        self._save_tool_call, ctx.conversation_id, call, result
                    )
                    tool_msgs.append(tool_result_message(call, result.to_llm()))
                messages.append(assistant_toolcall_message(calls))
                messages.extend(tool_msgs)
            else:
                # 工具循环耗尽（异常情况，模型一直在调工具）
                await self._send(ctx, "json", events.server_note("本轮工具调用次数过多，已停止继续查询。"))

            # 落库 + 成本入账 + 收尾
            assistant_text = "".join(assistant_parts).strip()
            await asyncio.to_thread(
                self._save_message, ctx.conversation_id, "assistant", assistant_text
            )
            cost_rmb = 0.0
            if usage is not None:
                cost_rmb = await asyncio.to_thread(
                    self.services.cost.record_llm,
                    ctx.conversation_id, model_name, usage,
                )
            if ctx.mode == "voice":
                await asyncio.to_thread(
                    self.services.cost.record_local, "stt", self.services.stt.name, ctx.conversation_id
                )
            if tts:
                await tts.drain()
            await self._send(ctx, "json", events.turn_end(usage.to_dict() if usage else {}, cost_rmb))
        except asyncio.CancelledError:
            logger.info("会话被中断（conversation=%s）", ctx.conversation_id)
            if tts:
                tts.cancel()
            partial = "".join(assistant_parts).strip()
            if partial:
                # fire-and-forget：取消路径里不能再 await
                asyncio.create_task(asyncio.to_thread(
                    self._save_message, ctx.conversation_id, "assistant", partial + "（已打断）"
                ))
            raise
        finally:
            flusher.cancel()
            ctx.turn_running = False
            # 后台记忆提取（不阻塞、不打扰取消）
            if cfg.memory.auto_extract and assistant_parts:
                asyncio.create_task(self._extract_memories(user_text, "".join(assistant_parts)))

    # ------------------------------------------------------------------ 内部

    @staticmethod
    async def _send(ctx: SessionContext, kind: str, payload) -> None:
        """统一发送入口（测试时可直接换 ctx 的 send_json/send_audio）。"""
        if kind == "json":
            if ctx.send_json is not None:
                await ctx.send_json(payload)
        else:
            if ctx.send_audio is not None:
                await ctx.send_audio(payload)

    async def _periodic_flush(self, splitter: SentenceSplitter, tts: TTSQueue | None, last_feed: list) -> None:
        """长句无标点兜底：距上次增量 1.2s 且缓冲 ≥ min_len 就出句。"""
        try:
            while True:
                await asyncio.sleep(0.3)
                if tts and splitter.pending() and (time.monotonic() - last_feed[0]) > 1.2:
                    for sentence in splitter.flush(force=False):
                        tts.enqueue(sentence)
        except asyncio.CancelledError:
            pass

    async def ensure_conversation(self, ctx: SessionContext) -> None:
        def _do():
            with self.services.db() as s:
                if s.get(Conversation, ctx.conversation_id) is None:
                    s.add(Conversation(id=ctx.conversation_id, persona=ctx.persona_name))
                    s.commit()
        await asyncio.to_thread(_do)

    def _build_system_prompt(self, ctx: SessionContext) -> str:
        memory_blocks = self.services.memory.prompt_blocks(
            episodes_max=self.services.config.memory.episodes_max_in_prompt
        )
        return self.services.persona.build_system_prompt(ctx.persona, memory_blocks)

    def _load_attachments(self, conversation_id: str, attachment_ids: list[str]) -> list[Attachment]:
        if not attachment_ids:
            return []
        ids = list(dict.fromkeys(x for x in attachment_ids if isinstance(x, str) and x))
        if len(ids) > self.services.config.attachments.max_images_per_turn:
            raise ValueError(f"单次最多发送 {self.services.config.attachments.max_images_per_turn} 个附件")
        with self.services.db() as s:
            rows = s.scalars(
                select(Attachment).where(
                    Attachment.conversation_id == conversation_id,
                    Attachment.id.in_(ids),
                )
            ).all()
        if len(rows) != len(ids):
            raise ValueError("存在无效或不属于当前会话的附件")
        return rows

    def _build_user_content(self, user_text: str, attachments: list[Attachment]) -> tuple[str, str | list[dict], str]:
        """图片原样进入 Vision；文件解析结果随后由文档管线作为文本加入。"""
        instruction = user_text.strip()
        if not instruction:
            raise ValueError("请先输入或说出你希望如何处理附件，再一起发送")
        labels = [f"[附件：{item.filename}]" for item in attachments]
        stored = "\n".join([instruction, *labels]).strip()
        images = [item for item in attachments if item.kind == "image"]
        documents = [item for item in attachments if item.kind != "image"]
        uses_vision = bool(images)
        blocks: list[dict] = [{"type": "text", "text": instruction}]
        remaining_document_chars = self.services.config.attachments.max_extracted_chars_per_turn
        for image in images:
            blocks.append(image_content_block(image.local_path))
        for document in documents:
            try:
                previews = json.loads(document.preview_paths or "[]")
            except json.JSONDecodeError:
                previews = []
            for preview in previews:
                blocks.append(image_content_block(preview))
                uses_vision = True
            if document.extracted_text.strip():
                excerpt = document.extracted_text[:remaining_document_chars]
                remaining_document_chars = max(remaining_document_chars - len(excerpt), 0)
                blocks.append({
                    "type": "text",
                    "text": (
                        f"\n附件《{document.filename}》提取内容：\n{excerpt}"
                        + ("\n（本轮文档上下文达到上限，后续正文已截断）"
                           if len(excerpt) < len(document.extracted_text) else "")
                    ),
                })
            else:
                blocks.append({
                    "type": "text",
                    "text": f"\n附件《{document.filename}》未能提取正文：{document.error or '正在准备解析'}。",
                })
        if uses_vision:
            return self.services.config.llm.vision_model, blocks, stored
        return self.services.config.llm.model, "\n".join(
            str(block.get("text", "")) for block in blocks
        ), stored

    def _load_history(self, conversation_id: str) -> list[dict]:
        max_chars = self.services.config.memory.history_max_chars
        with self.services.db() as s:
            rows = s.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.id.desc())
                .limit(100)
            ).all()
        rows = list(reversed(rows))
        out, chars = [], 0
        for r in rows:
            if chars + len(r.content) > max_chars:
                break
            out.append({"role": r.role, "content": r.content})
            chars += len(r.content)
        return out

    def _save_message(self, conversation_id: str, role: str, content: str) -> None:
        if not content.strip():
            return
        with self.services.db() as s:
            s.add(Message(conversation_id=conversation_id, role=role, content=content))
            conv = s.get(Conversation, conversation_id)
            if conv:
                if not conv.title and role == "user":
                    conv.title = content[:30]
                conv.updated_at = utcnow()
            s.commit()

    def _save_tool_call(self, conversation_id: str, call, result) -> None:
        with self.services.db() as s:
            s.add(ToolCall(
                conversation_id=conversation_id,
                name=call.name,
                args=json.dumps(call.arguments, ensure_ascii=False, default=str),
                result=result.to_llm() if result else None,
                ok=int(result.ok) if result else 0,
            ))
            s.commit()

    async def _budget_note(self) -> dict | None:
        cfg = self.services.config
        status = await asyncio.to_thread(self.services.cost.budget_status, "total")
        if not status["limit_rmb"]:
            return None
        if status["pct"] >= 100 and cfg.budget.hard_block:
            return events.error(
                "budget_exceeded",
                f"本月 AI 预算已用完（{status['spent_rmb']:.0f}/{status['limit_rmb']:.0f} 元），请在设置中调整。",
            )
        if status["pct"] >= 80:
            return events.server_note(
                f"本月 AI 预算已用 {status['pct']:.0f}%（{status['spent_rmb']:.0f}/{status['limit_rmb']:.0f} 元）"
            )
        return None

    async def _extract_memories(self, user_text: str, assistant_text: str) -> None:
        try:
            await self.extractor.run_after_turn(user_text, assistant_text)
        except Exception as e:
            logger.warning("后台记忆提取失败: %s", e)


def new_conversation_id() -> str:
    return uuid.uuid4().hex
