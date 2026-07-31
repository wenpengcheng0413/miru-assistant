"""
Miru Assistant — 日报生成器。

输入: Task 7 的 List[LLMCallResult]
输出: DailyReport (Markdown) + 持久化到 SQLite
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import jinja2
from loguru import logger

from miru.llm.schemas import (
    Deadline,
    FileItem,
    GroupAnalysis,
    LLMCallResult,
    Notice,
    UrgentTask,
)
from miru.report.formatter import truncate, truncate_report
from miru.storage.models import DailyReport, ReportItem, now_ts

TEMPLATE_DIR = Path(__file__).parent / "templates"
MAX_AI_SUGGESTION_LEN = 120


class ReportGenerator:
    """
    日报生成器。

    合并多个群的分析结果，渲染 Markdown 日报，持久化到数据库。

    使用方式:
        gen = ReportGenerator()
        report, items = gen.generate(results, report_date="2026-07-24")
        gen.save(report, items, db)
    """

    def __init__(self):
        self._jinja = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=False,
        )

    # ---- 主入口 ----

    def generate(
        self,
        llm_results: list[LLMCallResult],
        report_date: str = "",
        db_path: str = "data/miru.db",
        skip_db_save: bool = False,
    ) -> tuple[DailyReport, list[ReportItem]]:
        """
        生成日报并保存到数据库。

        Args:
            llm_results: Task 7 输出的分析结果列表。
            report_date: 日报日期 (YYYY-MM-DD)。为空则用今天。
            db_path: 数据库路径。
            skip_db_save: True 时不写入数据库 (回放模式)。

        Returns:
            (DailyReport, list[ReportItem])
        """
        if not report_date:
            report_date = datetime.now().strftime("%Y-%m-%d")

        # 1. 合并所有群的分析
        merged = self._merge_results(llm_results)

        # 2. 生成 AI 提醒
        ai_suggestion = self._generate_suggestion(merged)

        # 3. 渲染 Markdown
        content_md = self._render_template(
            merged=merged,
            report_date=report_date,
            ai_suggestion=ai_suggestion,
            failed_groups=merged["failed_groups"],
        )

        # 4. 截断保护
        content_md = truncate_report(content_md)

        # 5. 构建数据对象
        groups_covered = merged["successful_groups"]
        total_messages = merged["total_messages"]

        stats = {
            "total_messages_collected": total_messages,
            "groups_summarized": len(groups_covered),
            "groups_failed": len(merged["failed_groups"]),
            "urgent_tasks": len(merged["urgent_tasks"]),
            "deadlines": len(merged["deadlines"]),
            "notices": len(merged["notices"]),
            "files": len(merged["files"]),
        }

        report = DailyReport(
            report_date=report_date,
            content_md=content_md,
            stats_json=json.dumps(stats, ensure_ascii=False),
            groups_covered=json.dumps(groups_covered, ensure_ascii=False),
            message_count=total_messages,
            generated_at=now_ts(),
        )

        # 6. 构建 report_items
        items = self._build_report_items(merged)

        # 7. 持久化 (回放模式跳过)
        if not skip_db_save:
            self._save_to_db(report, items, db_path)

        logger.info(
            f"日报生成完成 — {report_date} | "
            f"{len(groups_covered)} 群, {total_messages} 消息, "
            f"{len(merged['urgent_tasks'])} urgent, "
            f"{len(items)} items"
        )
        return report, items

    # ---- 合并结果 ----

    def _merge_results(self, results: list[LLMCallResult]) -> dict:
        """合并所有 LLMCallResult 的 GroupAnalysis。"""
        merged = {
            "urgent_tasks": [],
            "deadlines": [],
            "notices": [],
            "files": [],
            "summaries": [],
            "successful_groups": [],
            "failed_groups": [],
            "total_messages": 0,
            "total_valid_messages": 0,
        }

        for r in results:
            if r.success and r.analysis is not None:
                a = r.analysis
                merged["successful_groups"].append(a.group_name)
                merged["total_messages"] += a.total_messages
                merged["total_valid_messages"] += a.valid_messages

                for t in a.urgent_tasks:
                    merged["urgent_tasks"].append({
                        "content": truncate(t.content),
                        "source_group": t.source_group,
                        "source_sender": t.source_sender,
                        "deadline": t.deadline,
                    })
                for d in a.deadlines:
                    merged["deadlines"].append({
                        "content": truncate(d.content),
                        "date": d.date,
                        "source_group": d.source_group,
                        "source_sender": d.source_sender,
                    })
                for n in a.notices:
                    merged["notices"].append({
                        "content": truncate(n.content),
                        "source_group": n.source_group,
                        "source_sender": n.source_sender,
                    })
                for f in a.files:
                    merged["files"].append({
                        "content": truncate(f.content),
                        "source_group": f.source_group,
                        "source_sender": f.source_sender,
                    })
                if a.summary:
                    merged["summaries"].append({
                        "group": a.group_name,
                        "text": a.summary,
                    })
            else:
                merged["failed_groups"].append(
                    f"{r.group_name}({r.error[:30] if r.error else '未知错误'})"
                )

        return merged

    # ---- AI 提醒 ----

    def _generate_suggestion(self, merged: dict) -> str:
        """基于合并结果生成一句 AI 行动建议。"""
        urgent_count = len(merged["urgent_tasks"])
        deadline_count = len(merged["deadlines"])
        notice_count = len(merged["notices"])
        file_count = len(merged["files"])

        parts = []

        if urgent_count > 0:
            parts.append(f"{urgent_count} 项待处理事项")
        if deadline_count > 0:
            parts.append(f"{deadline_count} 个截止日期")
        if notice_count > 0:
            parts.append(f"{notice_count} 条通知")
        if file_count > 0:
            parts.append(f"{file_count} 个文件/资料")

        if not parts:
            return "今日各群无重要事项，可以放松一下~"

        suggestion = f"今日共收到 {', '.join(parts)}。"
        if urgent_count > 0:
            suggestion += " 建议优先处理标记为【需要处理】的事项。"
        elif deadline_count > 0:
            suggestion += " 请注意截止日期，提前规划时间。"
        else:
            suggestion += " 空闲时可以浏览通知和文件资料。"

        return suggestion[:MAX_AI_SUGGESTION_LEN]

    # ---- 模板渲染 ----

    def _render_template(
        self,
        merged: dict,
        report_date: str,
        ai_suggestion: str,
        failed_groups: list[str],
    ) -> str:
        """渲染 Jinja2 模板。"""
        template = self._jinja.get_template("daily.md.j2")

        failed_str = "、".join(failed_groups) if failed_groups else ""

        return template.render(
            date=report_date,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            groups_covered=len(merged["successful_groups"]),
            message_count=merged["total_messages"],
            urgent_items=merged["urgent_tasks"],
            deadline_items=merged["deadlines"],
            notice_items=merged["notices"],
            file_items=merged["files"],
            summaries=merged["summaries"],
            ai_suggestion=ai_suggestion,
            failed_groups=failed_str,
        )

    # ---- 构建 ReportItem ----

    def _build_report_items(self, merged: dict) -> list[ReportItem]:
        """将合并结果拆分为 ReportItem 列表。"""
        items: list[ReportItem] = []
        order = 0

        for t in merged["urgent_tasks"]:
            items.append(ReportItem(
                category="urgent",
                content=t["content"],
                source_group=t["source_group"],
                source_sender=t.get("source_sender", ""),
                importance="high",
                deadline=t.get("deadline"),
                action_required=1,
                sort_order=order,
            ))
            order += 1

        for d in merged["deadlines"]:
            items.append(ReportItem(
                category="deadline",
                content=d["content"],
                source_group=d["source_group"],
                source_sender=d.get("source_sender", ""),
                importance="high",
                deadline=d.get("date"),
                action_required=1,
                sort_order=order,
            ))
            order += 1

        for n in merged["notices"]:
            items.append(ReportItem(
                category="notice",
                content=n["content"],
                source_group=n["source_group"],
                source_sender=n.get("source_sender", ""),
                importance="medium",
                action_required=0,
                sort_order=order,
            ))
            order += 1

        for f in merged["files"]:
            items.append(ReportItem(
                category="file",
                content=f["content"],
                source_group=f["source_group"],
                source_sender=f.get("source_sender", ""),
                importance="low",
                action_required=0,
                sort_order=order,
            ))
            order += 1

        return items

    # ---- 持久化 ----

    def _save_to_db(
        self,
        report: DailyReport,
        items: list[ReportItem],
        db_path: str,
    ) -> None:
        """保存日报和条目到数据库。"""
        try:
            from miru.storage.database import Database
            from miru.storage.migrations import run_migrations
            from miru.storage.repository import ReportRepository

            db = Database(db_path)
            # 确保数据库已初始化（运行迁移）
            run_migrations(db)
            repo = ReportRepository(db)

            # 检查是否已存在同日日报
            existing = repo.get_by_date(report.report_date)
            if existing is not None:
                logger.warning(
                    f"日期 {report.report_date} 的日报已存在，将被覆盖"
                )

            # 删除同日的旧条目（如果存在），再插入新条目
            existing = repo.get_by_date(report.report_date)
            if existing is not None and existing.id is not None:
                # 清理旧条目
                try:
                    db.conn.execute(
                        "DELETE FROM report_items WHERE report_id = ?",
                        (existing.id,),
                    )
                    db.conn.commit()
                except Exception:
                    pass

            saved_report = repo.insert_report(report)
            report.id = saved_report.id

            for item in items:
                item.report_id = report.id
            if items:
                repo.insert_items(items)

            db.close()
            logger.info(f"日报已保存 — report_id={report.id}, {len(items)} items")

        except Exception as e:
            logger.error(f"日报保存失败: {e}")
            # 不抛出 — 日报生成成功但保存失败不应阻断 Pipeline


# ============================================================
# 便捷 API
# ============================================================


def generate_daily_report(
    llm_results: list[LLMCallResult],
    report_date: str = "",
    db_path: str = "data/miru.db",
    skip_db_save: bool = False,
) -> tuple[DailyReport, list[ReportItem]]:
    """
    一键生成日报。

    Args:
        llm_results: LLM 分析结果列表。
        report_date: 日期。
        db_path: 数据库路径。
        skip_db_save: True 时不写入数据库 (回放模式)。

    Returns:
        (DailyReport, list[ReportItem])
    """
    gen = ReportGenerator()
    return gen.generate(llm_results, report_date, db_path, skip_db_save=skip_db_save)
