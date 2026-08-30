"""Collect redacted Phase 2 Docker/probe measurements.

This helper never prints environment values or request bodies. It is intended
to run only after Docker Desktop/Linux is available; it deliberately reports
unavailable metrics instead of inventing benchmark numbers.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def run(*args: str) -> tuple[int, str]:
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout.strip()


def http_probe(url: str, token: str = "") -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(url, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read(4096)
            return {
                "status": response.status,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "body_bytes_sampled": len(body),
            }
    except (OSError, urllib.error.URLError) as exc:
        return {"status": "NOT AVAILABLE", "error_type": type(exc).__name__}


def docker_stats(project: str) -> list[dict]:
    code, output = run(
        "docker", "stats", "--no-stream", "--format",
        "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.PIDs}}",
    )
    if code != 0:
        return [{"status": "NOT AVAILABLE"}]
    prefix = f"{project}-"
    rows = []
    for line in output.splitlines():
        parts = line.split("|", 4)
        if len(parts) != 5 or not parts[0].startswith(prefix):
            continue
        rows.append({
            "name": parts[0],
            "cpu_percent": parts[1],
            "memory_usage": parts[2],
            "memory_percent": parts[3],
            "pids": parts[4],
        })
    return rows or [{"status": "NOT AVAILABLE"}]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="miru-phase2")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("phase2-benchmark.json"))
    args = parser.parse_args()

    token = os.environ.get("MIRU_SERVER_TOKEN", "")
    code, version = run("docker", "version", "--format", "{{.Server.Version}}")
    result: dict = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "project": args.project,
        "docker_server_version": version if code == 0 else "NOT AVAILABLE",
        "api": {},
        "health_samples": [],
        "containers": docker_stats(args.project),
        "swap": "NOT AVAILABLE",
        "major_page_faults": "NOT AVAILABLE",
        "oom_killed": "NOT AVAILABLE",
        "restart_count": "NOT AVAILABLE",
        "disk_use": "NOT AVAILABLE",
        "websocket": "NOT AVAILABLE (requires an explicit WS client test)",
    }
    for path in ("/healthz", "/readyz", "/api/status"):
        result["api"][path] = http_probe(args.base_url + path, token if path == "/api/status" else "")
    for _ in range(max(1, args.samples)):
        result["health_samples"].append(http_probe(args.base_url + "/healthz"))
    latencies = [x["latency_ms"] for x in result["health_samples"] if isinstance(x.get("latency_ms"), (int, float))]
    if latencies:
        result["health_latency_ms"] = {
            "p50": round(statistics.median(latencies), 2),
            "p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2),
        }
    else:
        result["health_latency_ms"] = "NOT AVAILABLE"
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"benchmark written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
