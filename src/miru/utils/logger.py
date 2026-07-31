"""
Miru Assistant — 日志系统。

基于 Loguru，提供：
- 控制台 + 文件双输出
- 按大小自动轮转
- 按时间自动清理
- 结构化格式
"""

import sys
from pathlib import Path

from loguru import logger


def setup_logging(
    log_path: str = "./data/logs",
    log_level: str = "INFO",
    log_retention: str = "30 days",
    log_rotation: str = "10 MB",
) -> None:
    """
    初始化 Miru 日志系统。

    应在应用启动时调用一次。

    Args:
        log_path: 日志文件目录。
        log_level: 日志级别 (DEBUG/INFO/WARNING/ERROR)。
        log_retention: 日志保留时间。
        log_rotation: 单个日志文件最大大小。
    """
    # 移除默认 handler
    logger.remove()

    # 确保日志目录存在
    Path(log_path).mkdir(parents=True, exist_ok=True)

    # --- 控制台输出 ---
    logger.add(
        sys.stderr,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<level>{message}</level>"
        ),
        level=log_level,
        colorize=True,
    )

    # --- 文件输出 (普通日志) ---
    logger.add(
        Path(log_path) / "miru_{time:YYYY-MM-DD}.log",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} | "
            "{message}"
        ),
        level=log_level,
        rotation=log_rotation,
        retention=log_retention,
        encoding="utf-8",
        enqueue=True,         # 线程安全
        backtrace=True,
        diagnose=True,
    )

    # --- 文件输出 (仅错误) ---
    logger.add(
        Path(log_path) / "miru_error_{time:YYYY-MM-DD}.log",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} | "
            "{message}\n"
            "{exception}"
        ),
        level="ERROR",
        rotation=log_rotation,
        retention=log_retention,
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    logger.info(f"日志系统已初始化 — 级别={log_level}, 路径={log_path}")
