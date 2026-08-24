"""
Miru Assistant — 推送调度器。

集成 DB 状态追踪:
    - 推送前记录 pending
    - 推送成功记录 sent + pushed_at
    - 推送失败记录 failed + error_message

支持补推未推送的日报。
"""

import time
from pathlib import Path
from typing import Optional

from loguru import logger

from miru.notify.base import Notifier
from miru.notify.console import ConsoleNotifier
from miru.notify.pushplus import PushPlusNotifier
from miru.storage.database import Database
from miru.storage.migrations import run_migrations
from miru.storage.repository import ReportRepository


class DispatchResult:
    """推送结果。"""
    def __init__(self):
        self.total: int = 0
        self.success: int = 0
        self.failed: int = 0
        self.errors: list[str] = []


def dispatch_report(
    content_md: str,
    notifiers: list[Notifier],
    report_date: str = "",
    db_path: str = "data/miru.db",
) -> DispatchResult:
    """
    推送日报到所有启用的渠道，并更新数据库状态。

    Args:
        content_md: 日报 Markdown 内容。
        notifiers: 启用的推送渠道列表。
        report_date: 日报日期（用于更新 DB）。
        db_path: 数据库路径。

    Returns:
        DispatchResult — 推送结果统计。
    """
    title = f"Miru Daily — {report_date}" if report_date else "Miru Daily Assistant"
    result = DispatchResult()
    result.total = len(notifiers)

    # 更新 DB: pending
    if report_date and db_path:
        _update_db_status(report_date, "pending", db_path)

    for notifier in notifiers:
        try:
            ok = notifier.send(title, content_md)
            if ok:
                result.success += 1
            else:
                result.failed += 1
                result.errors.append(f"{type(notifier).__name__}: send returned False")
        except Exception as e:
            result.failed += 1
            result.errors.append(f"{type(notifier).__name__}: {e}")

    # 更新 DB: final status
    if report_date and db_path:
        status = "sent" if result.failed == 0 else "failed"
        error_msg = "; ".join(result.errors) if result.errors else ""
        _update_db_status(report_date, status, db_path, error_msg)

    logger.info(
        f"推送完成 — {result.success}/{result.total} 成功"
        + (f", 失败: {result.errors}" if result.errors else "")
    )
    return result


def retry_failed_pushes(
    notifiers: list[Notifier],
    db_path: str = "data/miru.db",
    max_days: int = 7,
) -> int:
    """
    补推最近 N 天内推送失败的日报。

    Args:
        notifiers: 推送渠道列表。
        db_path: 数据库路径。
        max_days: 最多补推多少天内的。

    Returns:
        成功补推的日报数量。
    """
    try:
        db = Database(db_path)
        run_migrations(db)
        repo = ReportRepository(db)
        unpushed = repo.get_unpushed()
        db.close()
    except Exception as e:
        logger.error(f"查询未推送日报失败: {e}")
        return 0

    if not unpushed:
        logger.info("没有需要补推的日报")
        return 0

    # 只补推最近 N 天的
    cutoff = time.time() - max_days * 86400
    recent = [r for r in unpushed if r.generated_at > cutoff]

    logger.info(f"找到 {len(recent)} 条未推送日报 (最近 {max_days} 天)")

    count = 0
    for report in recent:
        # 重新发送
        title = f"Miru Daily — {report.report_date} [补]"
        for notifier in notifiers:
            try:
                ok = notifier.send(title, report.content_md)
                if ok:
                    _update_db_status(report.report_date, "sent", db_path)
                    count += 1
                    break  # 有一个渠道成功即可
            except Exception:
                continue

    logger.info(f"补推完成 — {count}/{len(recent)} 成功")
    return count


def _update_db_status(
    report_date: str,
    status: str,
    db_path: str,
    error_msg: str = "",
) -> None:
    """更新日报的推送状态。"""
    try:
        db = Database(db_path)
        run_migrations(db)
        repo = ReportRepository(db)
        repo.update_push_status_by_date(report_date, status, error_msg)
        db.close()
    except Exception as e:
        logger.error(f"更新推送状态失败: {e}")
