# Changelog

All notable changes to Miru Daily Report will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] — 2026-07-27

### Added

**Core Automation**
- `launcher.bat` — Shell-level entry point with self-locating path (`%~dp0`), immune to spaces in file paths
- `bootstrap.py` — Python pre-flight entry point with 7 staged checks before heavy imports
- Tier 0 logging (`data/logs/launcher.log`) — captures shell-level errors even if Python never starts
- Tier 1 logging (`data/logs/bootstrap.log`) — captures pre-flight check results using only stdlib

**Task Scheduler**
- `scripts/setup_scheduler.ps1` V2 — Task Scheduler configuration that uses `cmd.exe /c "launcher.bat"` with proper quoting, eliminating the path-with-spaces bug
- Daily 22:00 trigger + AtLogon catch-up trigger
- 3 retries at 15-minute intervals for transient/environment errors
- Exit-code-driven retry logic (0=success, 1=permanent no-retry, 2/3=transient retry)

**Logging Architecture**
- Three-tier logging: Shell (Tier 0) → Python Pre-flight (Tier 1) → Pipeline (Tier 2)
- `launcher.log`: Shell-level startup, venv/config checks, exit codes
- `bootstrap.log`: Python version, dependency imports, config YAML validation, admin check, WeChat detection, PushPlus token check
- `miru_YYYY-MM-DD.log`: Full pipeline execution details (loguru, auto-rotated)
- `miru_error_YYYY-MM-DD.log`: Error-only log (loguru, auto-rotated)

**Documentation**
- `MIRU_DAILY_REPORT_V1.0_RELEASE.md` — Comprehensive release document
- `CHANGELOG.md` — This file
- `PROJECT_STATE_V1.0.md` — Development archive for future maintainers
- Operations manual: daily/weekly checks, troubleshooting flow, backup/restore procedures
- Deployment guide: first-time setup and migration between machines

### Fixed

- **Critical: Task Scheduler path-with-spaces bug** — `pythonw.exe` path containing `vibe coding` (space) was not quoted, causing Windows to interpret `E:\vibe` as the executable and `coding\...` as arguments, resulting in `ERROR_FILE_NOT_FOUND (Last Result: 2)`. Fixed by routing Task Scheduler through `cmd.exe /c "<quoted launcher path>"`.
- **Zero-log failure mode** — When Python failed to start, the `logs/` directory did not exist because it was created inside Python code. Now `launcher.bat` creates `data/logs/` at the shell level before any Python code runs.

### Engineering Improvements

- **Self-locating architecture**: `launcher.bat` uses `%~dp0`, `bootstrap.py` uses `Path(__file__).resolve()` — the project can be moved to any directory with any name without modifying these files
- **Pre-flight validation**: 7 checks (Python version, dependencies, config, platform, admin, WeChat, PushPlus) run with minimal imports before the heavy pipeline starts
- **Failure visibility**: Every failure mode produces a log entry with a clear error message, even if Python, loguru, or the venv is completely unavailable
- **Graceful degradation**: Partial pipeline failures (LLM timeout, PushPlus unreachable) do not block report generation and database persistence

---

## [0.x] — 2026-07-24 to 2026-07-27

### Pre-V1.0 History

- MiruPipeline 6-stage orchestration (environment check → message collection → filtering → LLM analysis → report generation → push notification)
- WeChat 4.x SQLCipher database decryption (key extraction from process memory + manual key fallback)
- WeChat 3.x/4.x dual-version message reader with ZSTD decompression
- DeepSeek LLM integration via OpenAI SDK with JSON mode structured output
- Jinja2 Markdown daily report generation
- PushPlus WeChat push notification with retry and content truncation
- SQLite WAL-mode storage with schema migrations and auto-backup
- Typer CLI with `miru run`, `miru status`, `miru doctor`, `miru decrypt`, `miru groups`, `miru read`, `miru push` commands
- Pydantic-based YAML config with `${ENV_VAR}` resolution and `SecretStr` for sensitive fields
- Message deduplication, cleaning, classification, and group filtering pipeline
- Custom exception hierarchy with exit code classification
- Loguru-based production logging with run_id context
- APScheduler dependency (listed but not used — project uses Windows Task Scheduler)
- chatlog_alpha integration for display name resolution via HTTP API

---

## Version History

| Version | Date | Status |
|---|---|---|
| 1.0.0 | 2026-07-27 | **Current** — Stable observation period |
