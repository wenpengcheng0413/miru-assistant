"""对话后自动记忆提取：一次非思考模式的 JSON 调用，提取画像/偏好/项目/知识。

后台执行（不阻塞流式），失败只记日志。所有写入 source=auto，可一键清空。
"""
from __future__ import annotations

import logging

from ..core.llm import LLMClient
from .store import MemoryStore

logger = logging.getLogger(__name__)

EXTRACT_SYSTEM = """你是记忆提取器。从对话中提取值得长期记住的用户信息，只输出 JSON：
{"profile_updates": {"条目名": "内容"}, "preferences_updates": {"条目名": "内容"},
 "projects": {"项目名": "状态"}, "knowledge": ["一句话事实"]}

规则：
1. profile=长期稳定事实（称呼、职业、常联系人、设备等）；preferences=用户偏好（回答详略、语气等）
2. projects=用户正在做的事；knowledge=用户明确要求记住或明显重要的事实
3. 只提取长期有效的信息，闲聊内容不提取；没有内容就输出空对象 {}
4. 严禁记录密码、密钥、token、身份证号等敏感凭据
5. 用用户的原话来概括，不要编造"""


class MemoryExtractor:
    def __init__(self, llm: LLMClient, store: MemoryStore):
        self.llm = llm
        self.store = store

    async def run_after_turn(self, user_text: str, assistant_text: str) -> None:
        """后台任务入口：提取并落库。任何异常都不影响主流程。"""
        try:
            result = await self.llm.chat_json(
                EXTRACT_SYSTEM,
                f"用户说：{user_text}\n助手回答：{assistant_text[:2000]}",
            )
            if not result:
                return
            self.apply(result)
        except Exception as e:
            logger.warning("记忆提取失败: %s", e)

    def apply(self, result: dict) -> int:
        """落库（同步），返回写入条数。"""
        n = 0
        for key, value in (result.get("profile_updates") or {}).items():
            self.store.set("profile", str(key), str(value), source="auto")
            n += 1
        for key, value in (result.get("preferences_updates") or {}).items():
            self.store.set("preferences", str(key), str(value), source="auto")
            n += 1
        for name, status in (result.get("projects") or {}).items():
            self.store.set("projects", str(name), str(status), source="auto")
            n += 1
        for fact in result.get("knowledge") or []:
            self.store.set("knowledge", "", str(fact), source="auto")
            n += 1
        if n:
            logger.info("记忆提取写入 %d 条", n)
        return n
