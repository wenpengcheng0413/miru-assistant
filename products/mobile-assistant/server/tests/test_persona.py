"""Persona 测试：加载、固定顺序组装、缺失回退、保存。"""
from miru_server.persona.builder import PersonaManager


def test_load_and_build_prompt(app_config):
    mgr = PersonaManager(app_config.persona.dir)
    persona = mgr.load("miru")
    assert persona.name == "Miru"
    prompt = mgr.build_system_prompt(persona, {"profile": {"称呼": "老板"}})
    # 固定顺序：人设 → 记忆 → 工具规则 → 禁止事项 → 当前时间（缓存前缀关键）
    assert prompt.index("你是 Miru") < prompt.index("[记忆]")
    assert prompt.index("[记忆]") < prompt.index("[工具使用规则]")
    assert prompt.index("[工具使用规则]") < prompt.index("[禁止事项]")
    assert prompt.index("[禁止事项]") < prompt.index("[当前时间]")
    assert "称呼=老板" in prompt
    assert "手机客户端具备语音播放能力" in prompt
    assert "不要声称自己没有播放声音的能力" in prompt


def test_missing_persona_falls_back_to_default(app_config):
    mgr = PersonaManager(app_config.persona.dir)
    persona = mgr.load("不存在的名字")
    assert persona.name == "不存在的名字"   # 名字保留，其余用默认
    assert persona.role


def test_save_and_list(app_config):
    mgr = PersonaManager(app_config.persona.dir)
    mgr.save("测试人设", "name: 测试\nrole: 测试角色\n")
    assert "测试人设" in mgr.list_names()
    assert mgr.load("测试人设").role == "测试角色"


def test_save_invalid_yaml(app_config):
    import pytest
    mgr = PersonaManager(app_config.persona.dir)
    with pytest.raises(ValueError):
        mgr.save("坏的", "- just\n- a\n- list")
