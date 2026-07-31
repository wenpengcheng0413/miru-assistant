"""
Miru Assistant — 日报生成层单元测试 (Task 8)。

测试覆盖:
    - Jinja2 模板渲染
    - 内容合并
    - AI 提醒生成
    - 空日报
    - API 失败群
    - 内容截断
    - DB 持久化
    - 完整 generate 流程
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from miru.llm.schemas import (
    Deadline,
    FileItem,
    GroupAnalysis,
    LLMCallResult,
    Notice,
    TokenUsage,
    UrgentTask,
)
from miru.report.formatter import count_chars, safe_md, truncate, truncate_report
from miru.report.generator import ReportGenerator, generate_daily_report
from miru.storage.database import Database
from miru.storage.migrations import run_migrations
from miru.storage.models import DailyReport, ReportItem
from miru.storage.repository import ReportRepository


# ============================================================
# Helpers
# ============================================================

def _make_success_result(
    group_name: str = "测试群",
    urgent: int = 0,
    deadlines: int = 0,
    notices: int = 0,
    files: int = 0,
) -> LLMCallResult:
    """创建成功的 LLMCallResult。"""
    tasks = [
        UrgentTask(content=f"任务{i}", source_group=group_name,
                    source_sender="老师", deadline="2026-07-30")
        for i in range(urgent)
    ]
    dls = [
        Deadline(content=f"截止{i}", date="2026-08-01",
                  source_group=group_name, source_sender="助教")
        for i in range(deadlines)
    ]
    ns = [
        Notice(content=f"通知{i}", source_group=group_name, source_sender="班主任")
        for i in range(notices)
    ]
    fs = [
        FileItem(content=f"文件{i}", source_group=group_name, source_sender="同学")
        for i in range(files)
    ]
    return LLMCallResult(
        group_name=group_name,
        analysis=GroupAnalysis(
            group_name=group_name,
            total_messages=10 + urgent + deadlines,
            valid_messages=urgent + deadlines + notices + files,
            urgent_tasks=tasks,
            deadlines=dls,
            notices=ns,
            files=fs,
            summary=f"{group_name}今日摘要",
            ignored_topics="闲聊",
        ),
        usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        success=True,
    )


def _make_failed_result(group_name: str = "失败群") -> LLMCallResult:
    return LLMCallResult(group_name=group_name, success=False, error="Connection timeout")


# ============================================================
# Test: Formatter
# ============================================================


class TestFormatter:
    def test_truncate_short(self):
        assert truncate("hello") == "hello"

    def test_truncate_long(self):
        long_text = "x" * 250
        result = truncate(long_text)
        assert len(result) <= 200
        assert result.endswith("...")

    def test_safe_md(self):
        assert safe_md("hello *world*") == "hello \\*world\\*"

    def test_count_chars(self):
        assert count_chars("hello世界") == 7

    def test_truncate_report_short(self):
        md = "# Short report\njust a bit of text"
        assert truncate_report(md, 10000) == md

    def test_truncate_report_long(self):
        sections = "\n## Section\n" + "x" * 15000
        result = truncate_report(sections, 2000)
        assert len(result) < 2000
        assert "截断" in result


# ============================================================
# Test: Report Generator
# ============================================================


class TestReportGenerator:
    def test_generate_basic(self, tmp_path):
        """基本日报生成。"""
        gen = ReportGenerator()
        results = [
            _make_success_result("班群", urgent=1, deadlines=1, notices=1),
            _make_success_result("AI群", files=2),
        ]
        db_path = str(tmp_path / "test.db")

        report, items = gen.generate(results, "2026-07-24", db_path)

        assert isinstance(report, DailyReport)
        assert report.report_date == "2026-07-24"
        assert "班群" in report.content_md
        assert "AI群" in report.content_md
        assert "🔴 需要处理" in report.content_md
        assert "📢 今日通知" in report.content_md
        assert "📂 文件资料" in report.content_md
        assert len(items) == 5  # 1 urgent + 1 deadline + 1 notice + 2 files

        # 检查分类
        categories = {i.category for i in items}
        assert "urgent" in categories
        assert "deadline" in categories
        assert "notice" in categories
        assert "file" in categories

    def test_empty_report(self, tmp_path):
        """所有群都没有重要消息时生成空日报。"""
        gen = ReportGenerator()
        results = [
            _make_success_result("空群1", urgent=0, deadlines=0, notices=0, files=0),
            _make_success_result("空群2", urgent=0, deadlines=0, notices=0, files=0),
        ]
        db_path = str(tmp_path / "empty.db")

        report, items = gen.generate(results, "2026-07-24", db_path)

        assert "Miru 日报" in report.content_md
        assert items == []
        assert "0 项" in report.content_md or "各群无重要" in report.content_md

    def test_failed_groups(self, tmp_path):
        """部分群分析失败时的日报。"""
        gen = ReportGenerator()
        results = [
            _make_success_result("正常群", notices=1),
            _make_failed_result("失败群"),
        ]
        db_path = str(tmp_path / "failed.db")

        report, items = gen.generate(results, "2026-07-24", db_path)

        assert "正常群" in report.content_md
        assert "失败群" in report.content_md  # failed warning
        assert len(items) == 1

    def test_all_failed(self, tmp_path):
        """所有群分析失败。"""
        gen = ReportGenerator()
        results = [
            _make_failed_result("群A"),
            _make_failed_result("群B"),
        ]
        db_path = str(tmp_path / "allfail.db")

        report, items = gen.generate(results, "2026-07-24", db_path)

        assert "Miru 日报" in report.content_md
        assert items == []
        assert report.message_count == 0

    def test_generate_with_no_date_uses_today(self, tmp_path):
        """不指定日期时自动使用今天。"""
        gen = ReportGenerator()
        results = [_make_success_result("群")]
        db_path = str(tmp_path / "today.db")

        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")

        report, _ = gen.generate(results, db_path=db_path)
        assert report.report_date == today

    def test_db_persistence(self, tmp_path):
        """日报成功保存到数据库。"""
        gen = ReportGenerator()
        results = [
            _make_success_result("班群", urgent=2, notices=1),
        ]
        db_path = str(tmp_path / "persist.db")

        report, items = gen.generate(results, "2026-07-24", db_path)
        assert report.id is not None
        assert report.id > 0

        # 验证可以读出
        db = Database(db_path)
        run_migrations(db)
        repo = ReportRepository(db)
        fetched = repo.get_by_date("2026-07-24")
        fetched_items = repo.get_items(fetched.id)
        db.close()

        assert fetched is not None
        assert fetched.content_md == report.content_md
        assert len(fetched_items) == 3  # 2 urgent + 1 notice

    def test_duplicate_date_overwrites(self, tmp_path):
        """同日重复生成会覆盖（日志警告）。"""
        gen = ReportGenerator()
        db_path = str(tmp_path / "dup.db")

        report1, _ = gen.generate(
            [_make_success_result("群A")], "2026-07-24", db_path,
        )
        report2, _ = gen.generate(
            [_make_success_result("群B")], "2026-07-24", db_path,
        )

        # 两次生成应成功
        assert report1.id is not None
        assert report2.id is not None

    def test_generate_daily_report_convenience(self, tmp_path):
        """便捷 API。"""
        db_path = str(tmp_path / "conv.db")
        results = [_make_success_result("群", notices=1)]
        report, items = generate_daily_report(results, "2026-07-24", db_path)
        assert report.report_date == "2026-07-24"
        assert len(items) == 1


# ============================================================
# Test: AI Suggestion
# ============================================================


class TestAISuggestion:
    def test_no_items(self):
        gen = ReportGenerator()
        merged = {"urgent_tasks": [], "deadlines": [], "notices": [], "files": []}
        sug = gen._generate_suggestion(merged)
        assert "无重要" in sug

    def test_with_urgent(self):
        gen = ReportGenerator()
        merged = {
            "urgent_tasks": [{"content": "test"} for _ in range(2)],
            "deadlines": [],
            "notices": [],
            "files": [],
        }
        sug = gen._generate_suggestion(merged)
        assert "2 项待处理" in sug
        assert "优先处理" in sug


# ============================================================
# Test: Template
# ============================================================


class TestTemplate:
    def test_full_template(self):
        """完整模板渲染。"""
        gen = ReportGenerator()
        merged = {
            "urgent_tasks": [
                {"content": "交报告", "source_group": "班群",
                 "source_sender": "老师", "deadline": "7月30日"},
            ],
            "deadlines": [
                {"content": "考试", "date": "8月15日",
                 "source_group": "课程群", "source_sender": ""},
            ],
            "notices": [
                {"content": "明天调课", "source_group": "班群",
                 "source_sender": "班主任"},
            ],
            "files": [
                {"content": "课件PDF", "source_group": "课程群",
                 "source_sender": "老师"},
            ],
            "summaries": [
                {"group": "班群", "text": "今日有调课通知"},
            ],
            "successful_groups": ["班群", "课程群"],
            "total_messages": 120,
        }

        md = gen._render_template(
            merged=merged,
            report_date="2026-07-24",
            ai_suggestion="今日有2项待处理事项，请注意截止日期。",
            failed_groups=[],
        )

        assert "# 📋 Miru 日报" in md
        assert "2026-07-24" in md
        assert "## 🔴 需要处理" in md
        assert "交报告" in md
        assert "7月30日" in md
        assert "## ⏰ 截止日期" in md
        assert "8月15日" in md
        assert "## 📢 今日通知" in md
        assert "明天调课" in md
        assert "## 📂 文件资料" in md
        assert "课件PDF" in md
        assert "## 💬 群聊摘要" in md
        assert "## 🤖 AI 提醒" in md
        assert "Miru Assistant" in md

    def test_template_with_failed_groups(self):
        """包含失败群的模板。"""
        gen = ReportGenerator()
        merged = {
            "urgent_tasks": [],
            "deadlines": [],
            "notices": [],
            "files": [],
            "summaries": [],
            "successful_groups": ["群1"],
            "total_messages": 10,
        }
        md = gen._render_template(
            merged, "2026-07-24", "无重要事项", ["群2(超时)", "群3(401)"],
        )
        assert "群2(超时)" in md
        assert "群3(401)" in md
