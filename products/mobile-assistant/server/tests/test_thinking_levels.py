import copy
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select
from miru_server.config import LLMConfig
from miru_server.core.llm import LLMClient, Done, Usage, TextDelta, ToolCallsDone, ToolCallSpec
from miru_server.core.pipeline import AgentPipeline, SessionContext
from miru_server.db.models import ApiUsage


@pytest.mark.parametrize('level,budget,thinking', [('low', 8192, False), ('high', 65536, True)])
async def test_level_survives_tool_round_and_counts_all_usage(services, level, budget, thinking):
    class LLM:
        calls = []
        async def stream_chat(self, messages, tools=None, **kwargs):
            self.calls.append((copy.deepcopy(messages), kwargs))
            if len(self.calls) == 1:
                yield TextDelta('正在查询。')
                yield ToolCallsDone([ToolCallSpec('one', 'get_current_time', {})], 'private intermediate')
                yield Done(Usage(10, 20), 'tool_calls', 'private intermediate')
            else:
                yield TextDelta('具体分析结果。')
                yield Done(Usage(30, 40), 'stop')
    llm = LLM()
    services.llm = llm
    events = []
    async def emit(e): events.append(e)
    ctx = SessionContext(conversation_id='mode-'+level, persona_name='miru',
      persona=services.persona.load('miru'), synth_tts=False, thinking_level=level, send_json=emit)
    await AgentPipeline(services).run(ctx, '帮我分析')
    assert len(llm.calls) == 2
    for messages, params in llm.calls:
        assert params['max_tokens'] == budget
        assert params['thinking'] is thinking
        assert f'思考等级：{"高" if thinking else "低"}' in messages[0]['content']
    call = next(m for m in llm.calls[-1][0] if m.get('tool_calls'))
    assert call['reasoning_content'] == 'private intermediate'
    assert call['content'] == '正在查询。'
    assert 'private intermediate' not in str(events)
    assert events[-1]['usage']['completion_tokens'] == 60
    with services.db() as db:
        assert len(db.scalars(select(ApiUsage).where(ApiUsage.kind == 'llm')).all()) == 2


@pytest.mark.parametrize('thinking,forced', [(True, False), (False, False), (True, True)])
async def test_llm_request_and_streamed_reasoning(thinking, forced):
    llm = LLMClient(LLMConfig(api_key='test'))
    requests = []
    async def create(**kwargs):
        requests.append(kwargs)
        async def chunks():
            for content, reasoning, finish, tc in [
                (None, 'private ', None, None),
                (None, 'thought', None, None),
                ('查到了', None, 'tool_calls', [NS(index=0, id='x', function=NS(name='get_current_time', arguments='{}'))]),
            ]:
                yield NS(usage=NS(prompt_tokens=2, completion_tokens=3), choices=[NS(
                    finish_reason=finish, delta=NS(content=content, reasoning_content=reasoning, tool_calls=tc))])
        return chunks()
    llm._client.chat.completions.create = create
    events = [e async for e in llm.stream_chat([{'role':'user','content':'hi'}],
      thinking=thinking, tool_choice={'type':'function','function':{'name':'get_current_time'}} if forced else None)]
    assert requests[0]['extra_body']['thinking']['type'] == ('enabled' if thinking and not forced else 'disabled')
    assert next(e for e in events if isinstance(e, ToolCallsDone)).reasoning_content == 'private thought'
    assert events[-1].reasoning_content == 'private thought'
    await llm._client.close()
