"""长期记忆存储：profile / preferences / projects / knowledge / episodes 五类（docs/05）。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import (
    MemoryEpisode,
    MemoryKnowledge,
    MemoryPreference,
    MemoryProfile,
    MemoryProject,
)

logger = logging.getLogger(__name__)

KEY_VALUE_SCOPES = {"profile": MemoryProfile, "preferences": MemoryPreference}


class MemoryStore:
    def __init__(self, db: sessionmaker[Session]):
        self._db = db

    # ---- 通用 CRUD（同步；调用方用 asyncio.to_thread）----

    def get(self, scope: str, key: str) -> dict | None:
        with self._db() as s:
            if scope in KEY_VALUE_SCOPES:
                row = s.get(KEY_VALUE_SCOPES[scope], key)
                return {"key": row.key, "value": row.value, "source": row.source} if row else None
            if scope == "projects":
                row = s.scalar(select(MemoryProject).where(MemoryProject.name == key))
                return {"name": row.name, "status": row.status, "notes": row.notes} if row else None
            if scope == "knowledge":
                row = s.get(MemoryKnowledge, int(key))
                return {"id": row.id, "content": row.content, "source": row.source} if row else None
            raise ValueError(f"未知记忆 scope: {scope}")

    def set(self, scope: str, key: str, value: str, source: str = "user") -> None:
        with self._db() as s:
            if scope in KEY_VALUE_SCOPES:
                model = KEY_VALUE_SCOPES[scope]
                row = s.get(model, key)
                if row:
                    row.value = value
                    row.source = source
                else:
                    s.add(model(key=key, value=value, source=source))
            elif scope == "projects":
                row = s.scalar(select(MemoryProject).where(MemoryProject.name == key))
                if row:
                    row.status = value
                else:
                    s.add(MemoryProject(name=key, status=value))
            elif scope == "knowledge":
                s.add(MemoryKnowledge(content=value, source=source))
            else:
                raise ValueError(f"未知记忆 scope: {scope}")
            s.commit()

    def delete(self, scope: str, key: str) -> bool:
        with self._db() as s:
            if scope in KEY_VALUE_SCOPES:
                row = s.get(KEY_VALUE_SCOPES[scope], key)
                if row:
                    s.delete(row)
                    s.commit()
                    return True
            elif scope == "projects":
                row = s.scalar(select(MemoryProject).where(MemoryProject.name == key))
                if row:
                    s.delete(row)
                    s.commit()
                    return True
            elif scope == "knowledge":
                row = s.get(MemoryKnowledge, int(key))
                if row:
                    s.delete(row)
                    s.commit()
                    return True
            return False

    def list(self, scope: str) -> list[dict]:
        with self._db() as s:
            if scope in KEY_VALUE_SCOPES:
                rows = s.scalars(select(KEY_VALUE_SCOPES[scope])).all()
                return [{"key": r.key, "value": r.value, "source": r.source} for r in rows]
            if scope == "projects":
                rows = s.scalars(select(MemoryProject)).all()
                return [{"name": r.name, "status": r.status, "notes": r.notes} for r in rows]
            if scope == "knowledge":
                rows = s.scalars(select(MemoryKnowledge).order_by(MemoryKnowledge.id.desc())).all()
                return [{"id": r.id, "content": r.content, "source": r.source} for r in rows]
            raise ValueError(f"未知记忆 scope: {scope}")

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """关键词检索（MVP 用 LIKE；向量检索是预留升级位）。"""
        q = f"%{query}%"
        out: list[dict] = []
        with self._db() as s:
            for model, scope, kf, vf in [
                (MemoryProfile, "profile", "key", "value"),
                (MemoryPreference, "preferences", "key", "value"),
                (MemoryProject, "projects", "name", "status"),
                (MemoryKnowledge, "knowledge", "id", "content"),
            ]:
                rows = s.scalars(
                    select(model).where(text(f"{vf} LIKE :q").bindparams(q=q)).limit(limit)
                ).all()
                for r in rows:
                    out.append({"scope": scope, "key": str(getattr(r, kf)), "value": getattr(r, vf)})
        return out[:limit]

    # ---- 面向 system prompt 的组装 ----

    def prompt_blocks(self, episodes_max: int = 5, knowledge_limit: int = 5) -> dict:
        """全部画像/偏好/项目 + 最近会话摘要 + 最近知识（供 persona builder 用）。"""
        with self._db() as s:
            profile = {
                r.key: r.value for r in s.scalars(select(MemoryProfile)).all()
            }
            prefs = {
                r.key: r.value for r in s.scalars(select(MemoryPreference)).all()
            }
            projects = [
                {"name": r.name, "status": r.status}
                for r in s.scalars(
                    select(MemoryProject).order_by(MemoryProject.updated_at.desc()).limit(10)
                )
            ]
            knowledge = [
                r.content
                for r in s.scalars(
                    select(MemoryKnowledge).order_by(MemoryKnowledge.id.desc()).limit(knowledge_limit)
                )
            ]
            episodes = [
                r.summary
                for r in s.scalars(
                    select(MemoryEpisode).order_by(MemoryEpisode.id.desc()).limit(episodes_max)
                )
            ]
        return {
            "profile": profile,
            "preferences": prefs,
            "projects": projects,
            "knowledge": knowledge,
            "episodes": episodes,
        }

    def add_episode(self, conversation_id: str, summary: str) -> None:
        with self._db() as s:
            s.add(MemoryEpisode(conversation_id=conversation_id, summary=summary))
            s.commit()

    def clean_auto(self) -> int:
        """一键清空自动提取的记忆（source=auto），返回清除条数。"""
        n = 0
        with self._db() as s:
            for model in (MemoryProfile, MemoryPreference, MemoryKnowledge):
                rows = s.scalars(select(model).where(model.source == "auto")).all()
                for r in rows:
                    s.delete(r)
                n += len(rows)
            s.commit()
        return n
