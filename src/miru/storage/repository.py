"""
Miru Assistant — Repository 层。

每个 Repository 封装对一张或多张表的操作。
业务层不应直接写 SQL — 所有数据访问通过 Repository 完成。

设计原则:
    - 方法名清晰表达意图 (get_by_*, insert_*, update_*, delete_*)
    - 返回 dataclass 或 list[dataclass]，不返回 sqlite3.Row
    - 所有写操作自动 commit
"""

import json
import time
from typing import Optional

from loguru import logger

from miru.storage.database import Database
from miru.storage.models import (
    ChatGroup,
    ConfigStore,
    DailyReport,
    RawMessage,
    ReportItem,
    RunLog,
    now_ts,
)


# ============================================================
# 工具函数
# ============================================================

def _row_to_dict(row: object) -> dict:
    """将 sqlite3.Row 转为 dict（处理 None）。"""
    if row is None:
        return {}
    return dict(row)


def _dict_to_dataclass(cls: type, data: dict):
    """将 dict 转为 dataclass 实例。忽略多余字段。"""
    from dataclasses import fields

    field_names = {f.name for f in fields(cls)}
    filtered = {k: v for k, v in data.items() if k in field_names}
    return cls(**filtered)


# ============================================================
# GroupRepository — 群组管理
# ============================================================

class GroupRepository:
    """管理 chat_groups 表的读写。"""

    def __init__(self, db: Database):
        self.db = db

    # --- 查询 ---

    def get_all(self) -> list[ChatGroup]:
        """获取所有群（包括已停用的）。"""
        rows = self.db.conn.execute(
            "SELECT * FROM chat_groups ORDER BY id"
        ).fetchall()
        return [_dict_to_dataclass(ChatGroup, dict(r)) for r in rows]

    def get_active(self) -> list[ChatGroup]:
        """获取所有启用的群。"""
        rows = self.db.conn.execute(
            "SELECT * FROM chat_groups WHERE is_active = 1 ORDER BY id"
        ).fetchall()
        return [_dict_to_dataclass(ChatGroup, dict(r)) for r in rows]

    def get_by_id(self, group_id: int) -> Optional[ChatGroup]:
        """按 ID 查找。"""
        row = self.db.conn.execute(
            "SELECT * FROM chat_groups WHERE id = ?", (group_id,)
        ).fetchone()
        if row is None:
            return None
        return _dict_to_dataclass(ChatGroup, dict(row))

    def get_by_wechat_username(self, username: str) -> Optional[ChatGroup]:
        """按微信内部 ID 查找。"""
        row = self.db.conn.execute(
            "SELECT * FROM chat_groups WHERE wechat_username = ?", (username,)
        ).fetchone()
        if row is None:
            return None
        return _dict_to_dataclass(ChatGroup, dict(row))

    def get_by_name(self, name: str) -> Optional[ChatGroup]:
        """按群显示名称精确查找。"""
        row = self.db.conn.execute(
            "SELECT * FROM chat_groups WHERE group_name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        return _dict_to_dataclass(ChatGroup, dict(row))

    # --- 写入 ---

    def insert_or_update(self, group: ChatGroup) -> ChatGroup:
        """
        插入或更新群信息。

        按 wechat_username 去重:
          - 不存在 → INSERT，返回带新 ID 的对象
          - 已存在 → UPDATE last_seen_at，返回已有对象
        """
        existing = self.get_by_wechat_username(group.wechat_username)
        ts = now_ts()

        if existing is not None:
            # 更新 last_seen_at 和 member_count
            self.db.conn.execute(
                """UPDATE chat_groups
                   SET member_count = ?, last_seen_at = ?, updated_at = ?
                   WHERE id = ?""",
                (group.member_count, ts, ts, existing.id),
            )
            self.db.conn.commit()
            existing.member_count = group.member_count
            existing.last_seen_at = ts
            existing.updated_at = ts
            return existing

        # 新群 — 插入
        cursor = self.db.conn.execute(
            """INSERT INTO chat_groups
               (group_name, wechat_username, is_active, member_count,
                first_seen_at, last_seen_at, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                group.group_name,
                group.wechat_username,
                group.is_active,
                group.member_count,
                ts,  # first_seen_at
                ts,  # last_seen_at
                group.notes,
                ts,
                ts,
            ),
        )
        self.db.conn.commit()
        group.id = cursor.lastrowid
        group.first_seen_at = ts
        group.last_seen_at = ts
        group.created_at = ts
        group.updated_at = ts
        return group

    def set_active(self, group_id: int, active: bool) -> None:
        """启用或停用一个群。"""
        self.db.conn.execute(
            "UPDATE chat_groups SET is_active = ?, updated_at = ? WHERE id = ?",
            (1 if active else 0, now_ts(), group_id),
        )
        self.db.conn.commit()


# ============================================================
# MessageRepository — 消息管理
# ============================================================

class MessageRepository:
    """管理 raw_messages 表的读写。"""

    def __init__(self, db: Database):
        self.db = db

    # --- 查询 ---

    def get_by_id(self, msg_id: int) -> Optional[RawMessage]:
        """按主键 ID 查找。"""
        row = self.db.conn.execute(
            "SELECT * FROM raw_messages WHERE id = ?", (msg_id,)
        ).fetchone()
        if row is None:
            return None
        return _dict_to_dataclass(RawMessage, dict(row))

    def get_by_msg_svr_id(self, msg_svr_id: int) -> Optional[RawMessage]:
        """按微信服务端消息 ID 查找（去重用）。"""
        row = self.db.conn.execute(
            "SELECT * FROM raw_messages WHERE msg_svr_id = ?", (msg_svr_id,)
        ).fetchone()
        if row is None:
            return None
        return _dict_to_dataclass(RawMessage, dict(row))

    def get_by_group(
        self,
        group_id: int,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 1000,
    ) -> list[RawMessage]:
        """按群 + 时间范围查询消息。"""
        query = (
            "SELECT * FROM raw_messages WHERE group_id = ?"
        )
        params: list = [group_id]

        if start_time is not None:
            query += " AND create_time >= ?"
            params.append(start_time)
        if end_time is not None:
            query += " AND create_time <= ?"
            params.append(end_time)

        query += " ORDER BY create_time ASC LIMIT ?"
        params.append(limit)

        rows = self.db.conn.execute(query, tuple(params)).fetchall()
        return [_dict_to_dataclass(RawMessage, dict(r)) for r in rows]

    def get_unprocessed(self, group_id: Optional[int] = None) -> list[RawMessage]:
        """获取未处理的消息。"""
        if group_id is not None:
            rows = self.db.conn.execute(
                "SELECT * FROM raw_messages WHERE is_processed = 0 AND group_id = ?",
                (group_id,),
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                "SELECT * FROM raw_messages WHERE is_processed = 0"
            ).fetchall()
        return [_dict_to_dataclass(RawMessage, dict(r)) for r in rows]

    def get_processed_svr_ids(self, svr_ids: list[int]) -> set[int]:
        """批量查询 — 返回已存在于数据库中的 msg_svr_id 集合。"""
        if not svr_ids:
            return set()
        placeholders = ",".join("?" * len(svr_ids))
        rows = self.db.conn.execute(
            f"SELECT msg_svr_id FROM raw_messages WHERE msg_svr_id IN ({placeholders})",
            tuple(svr_ids),
        ).fetchall()
        return {row["msg_svr_id"] for row in rows}

    # --- 写入 ---

    def insert(self, msg: RawMessage) -> RawMessage:
        """
        插入一条原始消息。

        如果 msg_svr_id 已存在则不插入（去重保护）。
        """
        existing = self.get_by_msg_svr_id(msg.msg_svr_id)
        if existing is not None:
            logger.debug(f"消息已存在 (msg_svr_id={msg.msg_svr_id})，跳过插入")
            return existing

        ts = now_ts()
        cursor = self.db.conn.execute(
            """INSERT INTO raw_messages
               (msg_svr_id, group_id, sender_name, content_text, msg_type,
                create_time, is_processed, processed_in, collected_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                msg.msg_svr_id,
                msg.group_id,
                msg.sender_name,
                msg.content_text,
                msg.msg_type,
                msg.create_time,
                msg.is_processed,
                msg.processed_in,
                ts,
                ts,
            ),
        )
        self.db.conn.commit()
        msg.id = cursor.lastrowid
        msg.collected_at = ts
        msg.created_at = ts
        return msg

    def insert_batch(self, messages: list[RawMessage]) -> int:
        """
        批量插入消息。自动跳过已存在的 msg_svr_id。

        Returns:
            实际插入的消息数量。
        """
        if not messages:
            return 0

        # 先查哪些 svr_id 已存在
        all_svr_ids = [m.msg_svr_id for m in messages]
        existing_ids = self.get_processed_svr_ids(all_svr_ids)
        new_messages = [m for m in messages if m.msg_svr_id not in existing_ids]

        if not new_messages:
            return 0

        ts = now_ts()
        data = [
            (
                m.msg_svr_id, m.group_id, m.sender_name, m.content_text,
                m.msg_type, m.create_time, m.is_processed, m.processed_in,
                ts, ts,
            )
            for m in new_messages
        ]

        self.db.conn.executemany(
            """INSERT INTO raw_messages
               (msg_svr_id, group_id, sender_name, content_text, msg_type,
                create_time, is_processed, processed_in, collected_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            data,
        )
        self.db.conn.commit()
        logger.debug(f"批量插入 {len(new_messages)} 条新消息 (跳过 {len(messages) - len(new_messages)} 条重复)")
        return len(new_messages)

    def mark_processed(self, msg_ids: list[int], report_id: int) -> None:
        """将一批消息标记为已处理。"""
        if not msg_ids:
            return
        placeholders = ",".join("?" * len(msg_ids))
        self.db.conn.execute(
            f"UPDATE raw_messages SET is_processed = 1, processed_in = ? "
            f"WHERE id IN ({placeholders})",
            (report_id, *msg_ids),
        )
        self.db.conn.commit()

    def delete_by_group(self, group_id: int) -> int:
        """删除某个群的所有消息（测试用）。"""
        cursor = self.db.conn.execute(
            "DELETE FROM raw_messages WHERE group_id = ?", (group_id,)
        )
        self.db.conn.commit()
        return cursor.rowcount

    def count(self) -> int:
        """消息总数。"""
        row = self.db.conn.execute("SELECT COUNT(*) as cnt FROM raw_messages").fetchone()
        return row["cnt"] if row else 0


# ============================================================
# ReportRepository — 日报管理
# ============================================================

class ReportRepository:
    """管理 daily_reports + report_items 表的读写。"""

    def __init__(self, db: Database):
        self.db = db

    # --- 查询 ---

    def get_by_id(self, report_id: int) -> Optional[DailyReport]:
        """按 ID 查询日报。"""
        row = self.db.conn.execute(
            "SELECT * FROM daily_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if row is None:
            return None
        return _dict_to_dataclass(DailyReport, dict(row))

    def get_by_date(self, date_str: str) -> Optional[DailyReport]:
        """按日期查询日报。"""
        row = self.db.conn.execute(
            "SELECT * FROM daily_reports WHERE report_date = ?", (date_str,)
        ).fetchone()
        if row is None:
            return None
        return _dict_to_dataclass(DailyReport, dict(row))

    def get_latest(self, limit: int = 7) -> list[DailyReport]:
        """获取最近的日报。"""
        rows = self.db.conn.execute(
            "SELECT * FROM daily_reports ORDER BY report_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_dict_to_dataclass(DailyReport, dict(r)) for r in rows]

    def get_unpushed(self) -> list[DailyReport]:
        """获取推送失败的日报（需要补推）。"""
        rows = self.db.conn.execute(
            "SELECT * FROM daily_reports WHERE push_status != 'sent' ORDER BY report_date"
        ).fetchall()
        return [_dict_to_dataclass(DailyReport, dict(r)) for r in rows]

    def get_items(self, report_id: int) -> list[ReportItem]:
        """获取日报的所有条目。"""
        rows = self.db.conn.execute(
            "SELECT * FROM report_items WHERE report_id = ? ORDER BY sort_order",
            (report_id,),
        ).fetchall()
        return [_dict_to_dataclass(ReportItem, dict(r)) for r in rows]

    # --- 写入 ---

    def insert_report(self, report: DailyReport) -> DailyReport:
        """插入日报主记录。"""
        ts = report.generated_at or now_ts()
        cursor = self.db.conn.execute(
            """INSERT OR REPLACE INTO daily_reports
               (report_date, content_md, stats_json, groups_covered,
                message_count, generated_at, push_status, pushed_at,
                push_error, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.report_date,
                report.content_md,
                report.stats_json,
                report.groups_covered,
                report.message_count,
                ts,
                report.push_status,
                report.pushed_at,
                report.push_error,
                now_ts(),
            ),
        )
        self.db.conn.commit()
        report.id = cursor.lastrowid
        report.generated_at = ts
        report.created_at = now_ts()
        return report

    def insert_items(self, items: list[ReportItem]) -> int:
        """批量插入日报条目。"""
        if not items:
            return 0

        ts = now_ts()
        data = [
            (
                item.report_id, item.category, item.content,
                item.source_group, item.source_sender,
                item.importance, item.deadline,
                item.action_required, item.sort_order, ts,
            )
            for item in items
        ]
        self.db.conn.executemany(
            """INSERT INTO report_items
               (report_id, category, content, source_group, source_sender,
                importance, deadline, action_required, sort_order, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            data,
        )
        self.db.conn.commit()
        return len(items)

    def update_push_status(
        self, report_id: int, status: str, error: str = ""
    ) -> None:
        """更新推送状态（按 ID）。"""
        self.db.conn.execute(
            """UPDATE daily_reports
               SET push_status = ?, push_error = ?, pushed_at = ?
               WHERE id = ?""",
            (status, error, now_ts() if status == "sent" else None, report_id),
        )
        self.db.conn.commit()

    def update_push_status_by_date(
        self, report_date: str, status: str, error: str = ""
    ) -> None:
        """更新推送状态（按日期）。"""
        self.db.conn.execute(
            """UPDATE daily_reports
               SET push_status = ?, push_error = ?, pushed_at = ?
               WHERE report_date = ?""",
            (status, error, now_ts() if status == "sent" else None, report_date),
        )
        self.db.conn.commit()


# ============================================================
# RunLogRepository — 运行日志
# ============================================================

class RunLogRepository:
    """管理 run_log 表的读写。"""

    def __init__(self, db: Database):
        self.db = db

    def insert(self, entry: RunLog) -> RunLog:
        """插入运行日志。"""
        cursor = self.db.conn.execute(
            """INSERT INTO run_log
               (run_id, phase, status, message, duration_ms,
                error_traceback, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.run_id,
                entry.phase,
                entry.status,
                entry.message,
                entry.duration_ms,
                entry.error_traceback,
                now_ts(),
            ),
        )
        self.db.conn.commit()
        entry.id = cursor.lastrowid
        entry.created_at = now_ts()
        return entry

    def get_by_run_id(self, run_id: str) -> list[RunLog]:
        """获取某次运行的所有日志。"""
        rows = self.db.conn.execute(
            "SELECT * FROM run_log WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [_dict_to_dataclass(RunLog, dict(r)) for r in rows]

    def get_recent(self, limit: int = 20) -> list[RunLog]:
        """获取最近的运行日志。"""
        rows = self.db.conn.execute(
            "SELECT * FROM run_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_dict_to_dataclass(RunLog, dict(r)) for r in rows]


# ============================================================
# ConfigStoreRepository — 配置快照
# ============================================================

class ConfigStoreRepository:
    """管理 config_store 表的读写。"""

    def __init__(self, db: Database):
        self.db = db

    def save_snapshot(self, config_data: dict) -> int:
        """保存配置快照。返回记录的 ID。"""
        import hashlib

        config_json = json.dumps(config_data, ensure_ascii=False, indent=2)
        config_hash = hashlib.sha256(config_json.encode()).hexdigest()

        cursor = self.db.conn.execute(
            """INSERT INTO config_store (config_hash, config_snapshot, created_at)
               VALUES (?, ?, ?)""",
            (config_hash, config_json, now_ts()),
        )
        self.db.conn.commit()
        return cursor.lastrowid

    def get_latest(self) -> Optional[ConfigStore]:
        """获取最新的配置快照。"""
        row = self.db.conn.execute(
            "SELECT * FROM config_store ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return _dict_to_dataclass(ConfigStore, dict(row))
