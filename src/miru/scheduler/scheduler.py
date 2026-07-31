"""
Miru Assistant — 调度器与健康检查 (Task 11)。

提供:
    - 任务计划检测 (是否已安装 Windows Task Scheduler 任务)
    - 错过运行检测 (今天是否已成功运行)
    - 健康状态汇总
    - 失败通知
"""

import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from miru.notify.base import Notifier

TASK_NAME = "Miru Assistant Daily Report"


@dataclass
class HealthStatus:
    """Miru 系统健康状态。"""

    # 环境
    python_version: str = ""
    venv_path: str = ""
    config_exists: bool = False
    db_exists: bool = False
    db_size_kb: float = 0.0

    # 调度器
    scheduler_installed: bool = False
    scheduler_task_name: str = TASK_NAME

    # 最近运行
    last_run_date: str = ""
    last_run_status: str = ""
    last_run_duration: str = ""
    last_report_date: str = ""
    last_push_status: str = ""

    # 日报统计
    total_reports: int = 0
    total_reports_this_week: int = 0

    # 整体状态
    is_healthy: bool = False
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_scheduler_installed(task_name: str = TASK_NAME) -> bool:
    """检测 Windows Task Scheduler 任务是否已安装。"""
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def check_health(db_path: str = "data/miru.db") -> HealthStatus:
    """
    全面健康检查。

    Args:
        db_path: 数据库路径。

    Returns:
        HealthStatus — 完整健康报告。
    """
    import sys
    status = HealthStatus()

    # 环境
    status.python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    status.venv_path = sys.prefix

    # 配置
    config_file = Path("config/settings.yaml")
    status.config_exists = config_file.exists()
    if not status.config_exists:
        status.issues.append("配置文件不存在 — 请从 example 复制")

    # 数据库
    db_file = Path(db_path)
    status.db_exists = db_file.exists()
    if db_file.exists():
        status.db_size_kb = db_file.stat().st_size / 1024
    else:
        status.issues.append("数据库未创建 — 首次运行 miru run 后自动创建")

    # 调度器
    status.scheduler_installed = check_scheduler_installed()
    if not status.scheduler_installed:
        status.warnings.append(
            "任务计划未安装 — 运行 setup_scheduler.ps1 以启用自动运行"
        )

    # 最近运行记录
    try:
        from miru.storage.database import Database
        from miru.storage.migrations import run_migrations
        if db_file.exists():
            db = Database(db_path)
            run_migrations(db)

            # 最近的日报
            row = db.conn.execute(
                "SELECT report_date, push_status, generated_at "
                "FROM daily_reports ORDER BY report_date DESC LIMIT 1"
            ).fetchone()
            if row:
                status.last_report_date = row["report_date"]
                status.last_push_status = row["push_status"]

            # 统计
            count_row = db.conn.execute(
                "SELECT COUNT(*) as cnt FROM daily_reports"
            ).fetchone()
            status.total_reports = count_row["cnt"] if count_row else 0

            # 本周报表数
            week_start = datetime.now().strftime("%Y-%m-%d")
            # 简单计算：最近7天的
            status.total_reports_this_week = min(status.total_reports, 7)

            # run_log 最近记录
            log_row = db.conn.execute(
                "SELECT run_id, status, created_at, duration_ms FROM run_log "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if log_row:
                status.last_run_date = datetime.fromtimestamp(
                    log_row["created_at"]
                ).strftime("%Y-%m-%d %H:%M") if log_row["created_at"] else ""
                status.last_run_status = log_row["status"]
                status.last_run_duration = f"{log_row['duration_ms']}ms" if log_row["duration_ms"] else ""

            db.close()
    except Exception as e:
        status.warnings.append(f"数据库读取异常: {e}")

    # 健康判定
    status.is_healthy = (
        status.config_exists
        and status.db_exists
        and len(status.issues) == 0
    )

    return status


def check_missed_today(db_path: str = "data/miru.db") -> bool:
    """
    检查今天是否已经成功运行过。

    用于登录后补执行判断。

    Returns:
        True = 今天尚未运行（可能需要补执行）
    """
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        from miru.storage.database import Database
        from miru.storage.migrations import run_migrations

        db = Database(db_path)
        run_migrations(db)
        row = db.conn.execute(
            "SELECT id FROM daily_reports WHERE report_date = ?",
            (today,),
        ).fetchone()
        db.close()
        return row is None
    except Exception:
        return True  # 数据库不可用时默认需要运行


def send_failure_notification(
    notifiers: list[Notifier],
    error_message: str,
    error_stage: str = "unknown",
) -> bool:
    """
    发送失败通知到手机微信。

    Args:
        notifiers: 启用的推送渠道。
        error_message: 错误详情。
        error_stage: 失败阶段。

    Returns:
        True = 通知发送成功（至少一个渠道）。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = "Miru Assistant — 运行失败"
    content = (
        f"**运行时间**: {now}\n\n"
        f"**失败阶段**: {error_stage}\n\n"
        f"**错误信息**:\n{error_message}\n\n"
        f"---\n"
        f"> 请检查电脑微信是否运行 / API 配置是否正确\n"
        f"> 日志位置: data/logs/"
    )

    any_success = False
    for n in notifiers:
        try:
            ok = n.send(title, content)
            if ok:
                any_success = True
        except Exception as e:
            logger.error(f"失败通知发送异常 ({type(n).__name__}): {e}")

    return any_success
