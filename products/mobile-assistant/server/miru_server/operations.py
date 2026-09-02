"""Content-free capacity metrics and threshold classification."""
from __future__ import annotations

import os
import shutil
from pathlib import Path


def pressure_state(percent: float) -> str:
    if percent >= 90:
        return "critical"
    if percent >= 85:
        return "restricted"
    if percent >= 70:
        return "warning"
    return "normal"


def _existing_anchor(path: Path) -> Path:
    candidate = path.resolve()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _proc_memory() -> dict:
    result = {"rss_mb": None, "swap_used_mb": None, "memory_available_mb": None}
    status = Path("/proc/self/status")
    if status.is_file():
        for line in status.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("VmRSS:"):
                result["rss_mb"] = round(int(line.split()[1]) / 1024, 1)
                break
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        values: dict[str, int] = {}
        for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, value = line.partition(":")
            if key in {"MemAvailable", "SwapTotal", "SwapFree"}:
                values[key] = int(value.split()[0])
        if "MemAvailable" in values:
            result["memory_available_mb"] = round(values["MemAvailable"] / 1024, 1)
        if "SwapTotal" in values and "SwapFree" in values:
            result["swap_used_mb"] = round(
                (values["SwapTotal"] - values["SwapFree"]) / 1024,
                1,
            )
    return result


def capacity_snapshot(data_path: str | Path) -> dict:
    """Return only aggregate host/process metrics; never include filesystem paths."""
    try:
        usage = shutil.disk_usage(_existing_anchor(Path(data_path)))
        used_percent = round(((usage.total - usage.free) / max(usage.total, 1)) * 100, 1)
        disk = {
            "state": pressure_state(used_percent),
            "used_percent": used_percent,
            "free_mb": round(usage.free / (1024 * 1024)),
        }
    except (OSError, RuntimeError, ValueError):
        disk = {"state": "unknown", "used_percent": None, "free_mb": None}
    load = None
    if hasattr(os, "getloadavg"):
        try:
            load = round(os.getloadavg()[0], 2)
        except OSError:
            pass
    return {"disk": disk, "process": {**_proc_memory(), "load_1m": load}}
