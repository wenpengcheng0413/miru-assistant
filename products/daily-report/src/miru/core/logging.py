"""
Miru Assistant — 统一生产日志系统 (V1.1)。

特性:
    - 控制台 + 文件双输出
    - 按日期自动切割
    - 保留 30 天
    - 支持 run_id 上下文
    - 多次调用安全（不重复添加 handler）
"""

import sys
from pathlib import Path
from typing import Optional

from loguru import logger

# 日志格式
CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<level>{message}</level>"
)

FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level: <8} | "
    "{extra[run_id]: <12} | "
    "{name}:{function}:{line} | "
    "{message}"
)

# 全局状态: 是否已初始化
_initialized = False
# 当前 run_id (Pipeline 运行时设置)
_current_run_id: Optional[str] = None


def init_logging(
    log_dir: str = "data/logs",
    level: str = "INFO",
    retention: str = "30 days",
    rotation: str = "10 MB",
) -> None:
    """
    初始化 Miru 日志系统。

    应在应用启动时尽早调用（CLI main callback）。
    多次调用安全——不会创建重复 handler。

    Args:
        log_dir: 日志目录。
        level: 日志级别。
        retention: 保留时间。
        rotation: 切割大小。
    """
    global _initialized
    if _initialized:
        return

    Path(log_dir).mkdir(parents=True, exist_ok=True)

    # 移除 loguru 默认 handler
    logger.remove()

    # 设置默认 run_id（Pipeline 启动时会覆盖）
    logger.configure(extra={"run_id": "-"})

    # --- 控制台 (INFO+) ---
    logger.add(
        sys.stderr,
        format=CONSOLE_FORMAT,
        level=level,
        colorize=True,
    )

    # --- 文件: 按日期命名 ---
    logger.add(
        Path(log_dir) / "miru_{time:YYYY-MM-DD}.log",
        format=FILE_FORMAT,
        level="DEBUG",
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    # --- 文件: 错误单独记录 ---
    logger.add(
        Path(log_dir) / "miru_error_{time:YYYY-MM-DD}.log",
        format=FILE_FORMAT,
        level="ERROR",
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    _initialized = True
    logger.info("Miru 日志系统已初始化")


def set_run_id(run_id: str) -> None:
    """
    设置当前 run_id。

    所有后续日志消息的 {extra[run_id]} 字段将使用此值。

    Args:
        run_id: Pipeline run_id。
    """
    global _current_run_id
    _current_run_id = run_id
    # 通过 loguru 的 contextualize 绑定到 logger
    logger.configure(extra={"run_id": run_id})


def get_run_id() -> Optional[str]:
    """获取当前 run_id。"""
    return _current_run_id


def is_initialized() -> bool:
    """日志系统是否已初始化。"""
    return _initialized
