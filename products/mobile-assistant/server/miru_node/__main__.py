from __future__ import annotations

import argparse
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .client import HomeNodeClient
from .config import NodeClientConfig


def _configure_logging(config: NodeClientConfig) -> None:
    log_path = Path(config.journal_path).parent / "home-node.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def main() -> None:
    parser = argparse.ArgumentParser(description="Miru Windows Home Node")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = NodeClientConfig.load(args.config)
    _configure_logging(config)
    asyncio.run(HomeNodeClient(config).run_forever())


if __name__ == "__main__":
    main()
