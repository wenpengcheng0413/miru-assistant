"""Advertise Miru on the home LAN with Bonjour/mDNS.

The phone discovers ``_miru._tcp`` and no longer depends on a DHCP address
remaining unchanged. Discovery is best-effort: a missing or broken network
adapter must never prevent the HTTP/WebSocket server from starting.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Any

from .config import ServerConfig

logger = logging.getLogger(__name__)

SERVICE_TYPE = "_miru._tcp.local."


def lan_ipv4_addresses() -> tuple[str, ...]:
    """Return usable IPv4 addresses for the current machine.

    Windows hostname resolution is not always complete during early boot, so
    use both hostname lookup and a route probe. The UDP probe sends no data.
    """
    candidates: set[str] = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.add(item[4][0])
    except OSError:
        pass

    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("192.0.2.1", 9))
            candidates.add(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass

    usable: list[str] = []
    for value in candidates:
        try:
            addr = ipaddress.ip_address(value)
        except ValueError:
            continue
        if (
            addr.version == 4
            and not addr.is_loopback
            and not addr.is_link_local
            and not addr.is_multicast
            and not addr.is_unspecified
        ):
            usable.append(value)
    return tuple(sorted(set(usable)))


def should_advertise(config: ServerConfig) -> bool:
    """Only advertise a server that is actually reachable from the LAN."""
    if not config.advertise_lan:
        return False
    host = config.host.strip().lower()
    return host in {"0.0.0.0", "::", "[::]"} or host not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }


class LanServiceAdvertiser:
    """Small restartable wrapper around python-zeroconf."""

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self._zeroconf: Any | None = None
        self._info: Any | None = None
        self._addresses: tuple[str, ...] = ()
        self._missing_dependency_logged = False

    @property
    def addresses(self) -> tuple[str, ...]:
        return self._addresses

    def refresh(self) -> bool:
        """Register, or re-register after an adapter/DHCP address change."""
        if not should_advertise(self.config):
            self.close()
            return False

        addresses = lan_ipv4_addresses()
        if not addresses:
            self.close()
            logger.debug("mDNS 暂无可用局域网 IPv4，稍后重试")
            return False
        if self._zeroconf is not None and addresses == self._addresses:
            return True

        self.close()
        try:
            from zeroconf import IPVersion, ServiceInfo, Zeroconf
        except ImportError:
            if not self._missing_dependency_logged:
                logger.warning("未安装 zeroconf，手机自动发现暂不可用")
                self._missing_dependency_logged = True
            return False

        hostname = socket.gethostname().strip() or "Windows-PC"
        instance = f"{self.config.service_name} on {hostname}"
        info = ServiceInfo(
            SERVICE_TYPE,
            f"{instance}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(value) for value in addresses],
            port=self.config.port,
            properties={
                "path": "/ws/session",
                "scheme": "http",
                "version": "1",
            },
            server=f"{hostname}.local.",
        )
        zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        try:
            zeroconf.register_service(info, allow_name_change=True)
        except Exception:
            zeroconf.close()
            logger.warning("Miru 局域网服务发布失败，稍后重试", exc_info=True)
            return False

        self._zeroconf = zeroconf
        self._info = info
        self._addresses = addresses
        logger.info(
            "已发布局域网服务 %s -> %s:%d",
            SERVICE_TYPE,
            ",".join(addresses),
            self.config.port,
        )
        return True

    def close(self) -> None:
        zeroconf, info = self._zeroconf, self._info
        self._zeroconf = None
        self._info = None
        self._addresses = ()
        if zeroconf is None:
            return
        try:
            if info is not None:
                zeroconf.unregister_service(info)
        except Exception:
            logger.debug("mDNS 注销失败", exc_info=True)
        finally:
            zeroconf.close()
