"""Value-free Home Node configuration."""
from __future__ import annotations

import os
from pathlib import Path
import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field
import yaml


class NodeClientConfig(BaseModel):
    cloud_url: str
    node_id: str = "node-home"
    token_path: str
    journal_path: str
    capabilities: list[str] = Field(default_factory=list)
    wechat_data_root: str = ""
    wechat_max_days: int = Field(default=90, ge=1, le=90)
    wechat_max_results: int = Field(default=20, ge=1, le=20)
    wechat_stt_model_dir: str = "./data/models/sensevoice"
    connect_timeout_s: float = Field(default=12.0, ge=3, le=60)
    max_backoff_s: float = Field(default=60.0, ge=5, le=300)

    def model_post_init(self, __context: object) -> None:
        parsed = urlparse(self.cloud_url)
        if parsed.scheme != "wss" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Home Node cloud_url must be a credential-free WSS URL")
        if parsed.path not in {"", "/", "/ws/node"}:
            raise ValueError("Home Node cloud_url path must be /ws/node")
        self.cloud_url = parsed._replace(path="/ws/node", params="", query="", fragment="").geturl()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", self.node_id):
            raise ValueError("invalid node_id")
        clean = []
        for item in self.capabilities:
            value = item.strip()
            if value and len(value) <= 64 and re.fullmatch(r"[a-z0-9_.-]+", value):
                clean.append(value)
        self.capabilities = sorted(set(clean))
        self.token_path = str(Path(os.path.expandvars(self.token_path)).expanduser())
        self.journal_path = str(Path(os.path.expandvars(self.journal_path)).expanduser())
        if self.wechat_data_root:
            self.wechat_data_root = str(
                Path(os.path.expandvars(self.wechat_data_root)).expanduser()
            )
        self.wechat_stt_model_dir = str(
            Path(os.path.expandvars(self.wechat_stt_model_dir)).expanduser()
        )

    @classmethod
    def load(cls, path: str | Path) -> "NodeClientConfig":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)
