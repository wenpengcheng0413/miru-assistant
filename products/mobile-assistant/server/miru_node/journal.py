"""Bounded local journal used for reconnect/idempotency handshakes."""
from __future__ import annotations

import json
import os
from pathlib import Path


class JobJournal:
    def __init__(self, path: str | Path, *, limit: int = 100) -> None:
        self.path = Path(path)
        self.limit = max(1, min(limit, 100))

    def _rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = raw.get("completed", []) if isinstance(raw, dict) else []
        valid: list[dict] = []
        for item in rows:
            if isinstance(item, str) and 1 <= len(item) <= 128:
                valid.append({"job_id": item, "result": None})
            elif isinstance(item, dict):
                job_id = item.get("job_id")
                result = item.get("result")
                if isinstance(job_id, str) and 1 <= len(job_id) <= 128 and (
                    result is None or isinstance(result, dict)
                ):
                    valid.append({"job_id": job_id, "result": result})
        return valid[-self.limit:]

    def completed_ids(self) -> list[str]:
        return [item["job_id"] for item in self._rows()]

    def get_result(self, job_id: str) -> dict | None:
        for item in reversed(self._rows()):
            if item["job_id"] == job_id and isinstance(item["result"], dict):
                return item["result"]
        return None

    def record_completed(self, job_id: str) -> None:
        self.record_result(job_id, None)

    def record_result(self, job_id: str, result: dict | None) -> None:
        if not isinstance(job_id, str) or not (1 <= len(job_id) <= 128):
            raise ValueError("invalid job_id")
        if result is not None:
            if not isinstance(result, dict):
                raise ValueError("invalid job result")
            encoded = json.dumps(result, ensure_ascii=False, default=str)
            if len(encoded) > 16_384:
                raise ValueError("job result too large")
        rows = [item for item in self._rows() if item["job_id"] != job_id]
        rows.append({"job_id": job_id, "result": result})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"version": 2, "completed": rows[-self.limit:]}, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
