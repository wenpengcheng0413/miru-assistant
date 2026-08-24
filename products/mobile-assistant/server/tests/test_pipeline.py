"""管线集成测试：用 FakeLLM 验证 流式→工具循环→落库→成本 全链路（不联网）。"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from miru_server.core.llm import Done, StreamError, TextDelta, ToolCallsDone, ToolCallSpec, Usage
from miru_server.core.pipeline import AgentPipeline, SessionContext, new_conversation_id
from miru_server.db.models import ApiUsage, Attachment, Message, ToolCall


class FakeLLM:
    """脚本化 LLM：每次 stream_chat 弹出一段事件脚本。"""

    def __init__(self, scripts: list[list]):
        self.scripts = list(scripts)
        self.calls: list[list[dict]] = []

    async def stream_chat(self, messages, tools=None, model=None):
        self.calls.append((messages, model))
        for ev in self.scripts.pop(0):
            yield ev

    async def chat_json(self, system, user, temperature=0.1):
        return {}


def make_ctx(services, events: list, conversation_id: str | None = None) -> SessionContext:
    async def cap(payload):
        events.append(payload)

    ctx = SessionContext(
        conversation_id=conversation_id or new_conversation_id(),
        persona_name="miru",
        persona=services.persona.load("miru"),
        mode="text",
        synth_tts=False,
    )
    ctx.send_json = cap
    return ctx


def run_pipeline(services, scripts, text="你好"):
    events: list[dict] = []
    services.llm = FakeLLM(scripts)
    pipeline = AgentPipeline(services)
    ctx = make_ctx(services, events)
    asyncio.run(pipeline.run(ctx, text))
    return events, ctx


def test_simple_turn(services):
    events, ctx = run_pipeline(services, [
        [TextDelta("你好，老板。"), Done(Usage(prompt_tokens=100, completion_tokens=50))],
    ])
    types = [e["type"] for e in events]
    assert types[0] == "user_text"
    assert "llm_delta" in types
    assert types[-1] == "turn_end"
    assert events[-1]["cost_rmb"] > 0

    # 落库
    with services.db() as s:
        msgs = s.scalars(select(Message).where(Message.conversation_id == ctx.conversation_id)).all()
        assert [m.role for m in msgs] == ["user", "assistant"]
        usage_rows = s.scalars(select(ApiUsage)).all()
        assert any(u.kind == "llm" and u.cost_rmb > 0 for u in usage_rows)


def test_tool_round(services):
    events, ctx = run_pipeline(services, [
        [ToolCallsDone([ToolCallSpec(id="c1", name="get_current_time", arguments={})])],
        [TextDelta("现在是下午三点。"), Done(Usage(20, 20))],
    ])
    types = [e["type"] for e in events]
    assert "tool_start" in types and "tool_end" in types
    tool_end = next(e for e in events if e["type"] == "tool_end")
    assert tool_end["ok"] is True
    # 第二轮 LLM 消息里应有 tool 结果回填
    assert any(m["role"] == "tool" for m in services.llm.calls[-1][0])
    with services.db() as s:
        row = s.scalars(select(ToolCall).where(ToolCall.conversation_id == ctx.conversation_id)).one()
        assert row.name == "get_current_time" and row.ok == 1


def test_llm_error(services):
    events, ctx = run_pipeline(services, [[StreamError("网络不可达")]])
    types = [e["type"] for e in events]
    assert types[-1] == "error" and types[-2] == "user_text"
    # 用户消息仍落库，但没有 assistant 消息
    with services.db() as s:
        msgs = s.scalars(select(Message).where(Message.conversation_id == ctx.conversation_id)).all()
        assert [m.role for m in msgs] == ["user"]


def test_history_loaded_for_multiturn(services):
    """第二轮应带上第一轮历史（多轮上下文）。"""
    _, ctx = run_pipeline(services, [[TextDelta("第一轮。"), Done(Usage(10, 10))]])
    events2 = []
    services.llm = FakeLLM([[TextDelta("第二轮回答。"), Done(Usage(10, 10))]])
    pipeline = AgentPipeline(services)
    ctx2 = make_ctx(services, events2, conversation_id=ctx.conversation_id)
    asyncio.run(pipeline.run(ctx2, "继续聊"))
    messages = services.llm.calls[0][0]
    roles = [m["role"] for m in messages]
    assert roles.count("user") == 2 and roles.count("assistant") == 1


def test_document_content_keeps_explicit_instruction_and_large_excerpt(services):
    pipeline = AgentPipeline(services)
    document = Attachment(
        id="a1",
        conversation_id="c1",
        filename="budget.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        kind="spreadsheet",
        size_bytes=100,
        sha256="0" * 64,
        local_path="budget.xlsx",
        status="ready",
        extracted_text="月度汇总\n" + ("明细数据\n" * 5000),
        error="",
        preview_paths="[]",
    )

    _, content, stored = pipeline._build_user_content("找出支出异常月份", [document])
    assert content.startswith("找出支出异常月份")
    assert len(content) > 12_000
    assert "[附件：budget.xlsx]" in stored

    with pytest.raises(ValueError, match="请先输入或说出"):
        pipeline._build_user_content("", [document])
