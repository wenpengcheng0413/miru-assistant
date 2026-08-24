"""loguru 日志配置：控制台 + 滚动文件（server/data/logs/）。"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from loguru import logger


def setup_logging(log_dir: Path = Path("data/logs"), level: str = "INFO") -> None:
    log_dir.mkdir(parents=True, exist_ok=True)

    # Most of miru_server uses the standard logging module. Configure it as
    # well as Loguru so startup/discovery failures are not silently discarded.
    std_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d - %(message)s"
    )
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(
        log_dir / "miru_server_stdlib.log", encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(std_level)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)

    logger.remove()
    logger.add(sys.stderr, level=level, backtrace=False, diagnose=False)
    logger.add(
        log_dir / "miru_server.log",
        level="DEBUG",
        rotation="10 MB",
        retention=7,
        encoding="utf-8",
        backtrace=False,
        diagnose=False,
    )
