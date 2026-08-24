"""记忆存储测试：五类 scope CRUD + 检索 + prompt 组装。"""
import asyncio


def test_kv_scopes(services):
    store = services.memory
    store.set("profile", "称呼", "老板", source="user")
    assert store.get("profile", "称呼")["value"] == "老板"
    store.set("preferences", "回答详细程度", "简短")
    assert store.list("preferences")[0]["key"] == "回答详细程度"
    assert store.delete("profile", "称呼") is True
    assert store.get("profile", "称呼") is None


def test_projects_and_knowledge(services):
    store = services.memory
    store.set("projects", "Miru", "后端 MVP 阶段")
    store.set("knowledge", "", "用户每周三晚上开组会", source="user")
    projects = store.list("projects")
    assert projects[0]["name"] == "Miru" and projects[0]["status"] == "后端 MVP 阶段"
    knowledge = store.list("knowledge")
    assert any("开组会" in k["content"] for k in knowledge)


def test_search(services):
    store = services.memory
    store.set("profile", "常联系人", "小明")
    store.set("knowledge", "", "小明喜欢喝咖啡")
    hits = store.search("小明")
    assert len(hits) >= 2
    assert store.search("不存在的词xyz") == []


def test_prompt_blocks_and_episodes(services):
    from miru_server.db.models import Conversation
    with services.db() as s:
        s.add(Conversation(id="conv-1"))
        s.commit()
    store = services.memory
    store.set("profile", "职业", "开发者")
    store.add_episode("conv-1", "聊了 Miru 项目")
    blocks = store.prompt_blocks(episodes_max=5)
    assert blocks["profile"]["职业"] == "开发者"
    assert any("Miru" in e for e in blocks["episodes"])


def test_clean_auto(services):
    store = services.memory
    store.set("profile", "自动条目", "x", source="auto")
    store.set("profile", "手动条目", "y", source="user")
    n = store.clean_auto()
    assert n >= 1
    assert store.get("profile", "自动条目") is None
    assert store.get("profile", "手动条目")["value"] == "y"
