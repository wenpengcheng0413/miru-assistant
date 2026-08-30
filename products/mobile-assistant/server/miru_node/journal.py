"""Bounded local journal used for reconnect/idempotency handshakes."""
from __future__ import annotations

import json
import os
from pathlib import Path


class JobJournal:
    def __init__(self, path: str | Path, *, limit: int = 100) -> None:
        self.path = Path(path)
        self.limit = max(1, min(limit, 100))

    def completed_ids(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = raw.get("completed", []) if isinstance(raw, dict) else []
        valid = [item for item in rows if isinstance(item, str) and 1 <= len(item) <= 128]
        return valid[-self.limit:]

    def record_completed(self, job_id: str) -> None:
        if not isinstance(job_id, str) or not (1 <= len(job_id) <= 128):
            raise ValueError("invalid job_id")
        rows = [item for item in self.completed_ids() if item != job_id]
        rows.append(job_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"version": 1, "completed": rows[-self.limit:]}, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
