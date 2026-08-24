"""应用入口：miru-server 命令 → uvicorn。

启动：cd products/mobile-assistant/server && python -m miru_server
    或安装后：miru-server --config config/settings.yaml
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import secrets
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import rest, ws
from .config import AppConfig
from .db.backup import backup_database
from .discovery import LanServiceAdvertiser
from .logging_setup import setup_logging
from .services import create_services

logger = logging.getLogger(__name__)


def create_app(config: AppConfig) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        import asyncio

        services = create_services(config)
        if not config.server.token:
            config.server.token = secrets.token_urlsafe(24)
            logger.warning(
                "MIRU_SERVER_TOKEN 未设置，本次会话随机令牌: %s（重启会变，请尽快固定）",
                config.server.token,
            )
        app.state.services = services

        # Bonjour/mDNS：手机可按服务名发现电脑，不再依赖固定 DHCP 地址。
        # 开机早期网卡可能尚未就绪，所以后台定期刷新；失败不阻塞主服务。
        advertiser = LanServiceAdvertiser(config.server)

        async def _advertise_loop() -> None:
            while True:
                try:
                    await asyncio.to_thread(advertiser.refresh)
                except Exception:
                    logger.warning("局域网服务发布检查失败", exc_info=True)
                await asyncio.sleep(30)

        advertiser_task = asyncio.create_task(_advertise_loop())

        # 每天一个一致性 SQLite 快照；应用或 IPA 升级不会触碰 data/backups。
        backup_task: asyncio.Task | None = None
        if config.backup.enabled:
            async def _backup_loop() -> None:
                while True:
                    try:
                        saved = await asyncio.to_thread(
                            backup_database,
                            config.resolve(config.db.path),
                            config.resolve(config.backup.dir),
                            config.backup.retention_days,
                        )
                        logger.info("Miru 数据库备份完成: %s", saved)
                    except Exception:
                        logger.warning("Miru 数据库备份失败", exc_info=True)
                    await asyncio.sleep(6 * 60 * 60)

            backup_task = asyncio.create_task(_backup_loop())

        # 后台任务：每分钟检查一次，STT 闲置超时则卸载模型释放内存
        unloader: asyncio.Task | None = None
        if hasattr(services.stt, "maybe_unload"):

            async def _unload_loop() -> None:
                while True:
                    await asyncio.sleep(60)
                    services.stt.maybe_unload()

            unloader = asyncio.create_task(_unload_loop())

        yield

        if unloader is not None:
            unloader.cancel()
        if backup_task is not None:
            backup_task.cancel()
        advertiser_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await advertiser_task
        await asyncio.to_thread(advertiser.close)

    app = FastAPI(title="Miru Server", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],           # 局域网工具访问；安全靠 token 鉴权
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(ws.router)
    app.include_router(rest.router)

    @app.get("/")
    async def root():
        return {
            "service": "Miru Server",
            "docs": "/docs",
            "ws": "/ws/session",
            "api": "/api",
        }

    return app


def run() -> None:
    parser = argparse.ArgumentParser(description="Miru 语音 AI 工作台后端")
    parser.add_argument("--config", default=None, help="settings.yaml 路径")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    config = AppConfig.load(args.config)
    host = args.host or config.server.host
    port = args.port or config.server.port
    # Keep runtime config aligned with CLI overrides so health/discovery report
    # the address actually used by Uvicorn.
    config.server.host = host
    config.server.port = port
    setup_logging(config.config_dir.parent / "data" / "logs")
    app = create_app(config)
    logger.info("Miru Server 启动: http://%s:%d（WS: /ws/session）", host, port)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    run()
