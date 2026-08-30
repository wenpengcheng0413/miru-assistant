"""In-memory Home Node identity, capability, and heartbeat state.

The registry intentionally stores no Node token, job parameters, private paths,
or result content.  Phase 6 only establishes identity and liveness; the job
router is added in Phase 7.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import threading
import time
import uuid
from typing import Callable

from .config import HomeNodeConfig


@dataclass(frozen=True)
class NodeSnapshot:
    state: str
    reason: str
    last_seen: str | None
    protocol_version: int
    capabilities: tuple[str, ...]

    def public_dict(self) -> dict:
        return {
            "state": self.state,
            "reason": self.reason,
            "last_seen": self.last_seen,
            "protocol_version": self.protocol_version,
            "capabilities": list(self.capabilities),
        }


class HomeNodeRegistry:
    def __init__(
        self,
        config: HomeNodeConfig,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.config = config
        self._monotonic = monotonic
        self._utcnow = utcnow
        self._lock = threading.RLock()
        self._connection_id: str | None = None
        self._connected = False
        self._last_seen_mono: float | None = None
        self._last_seen_utc: str | None = None
        self._protocol_version = 1
        self._capabilities: tuple[str, ...] = ()

    def register(
        self,
        *,
        protocol_version: int,
        capabilities: list[str],
    ) -> str:
        allowed = set(self.config.allowed_capabilities)
        bounded = tuple(sorted({item for item in capabilities if item in allowed}))
        connection_id = str(uuid.uuid4())
        with self._lock:
            self._connection_id = connection_id
            self._connected = True
            self._protocol_version = protocol_version
            self._capabilities = bounded
            self._touch_locked()
        return connection_id

    def heartbeat(self, connection_id: str) -> bool:
        with self._lock:
            if connection_id != self._connection_id:
                return False
            self._connected = True
            self._touch_locked()
            return True

    def disconnect(self, connection_id: str) -> None:
        with self._lock:
            if connection_id == self._connection_id:
                self._connected = False

    def _touch_locked(self) -> None:
        self._last_seen_mono = self._monotonic()
        self._last_seen_utc = self._utcnow().isoformat()

    def snapshot(self) -> NodeSnapshot:
        if not self.config.enabled:
            return NodeSnapshot("not_configured", "disabled", None, 1, ())
        with self._lock:
            last_mono = self._last_seen_mono
            last_utc = self._last_seen_utc
            connected = self._connected
            protocol = self._protocol_version
            capabilities = self._capabilities
        if last_mono is None:
            return NodeSnapshot("offline", "node_never_connected", None, 1, ())
        age = max(0.0, self._monotonic() - last_mono)
        if connected and age < self.config.stale_after_s:
            state, reason = "online", ""
        elif age < self.config.offline_after_s:
            state, reason = "stale", "node_reconnecting"
        else:
            state, reason = "offline", "heartbeat_timeout"
        return NodeSnapshot(state, reason, last_utc, protocol, capabilities)
