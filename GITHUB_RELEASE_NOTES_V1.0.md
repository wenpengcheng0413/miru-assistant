# Miru Daily Report V1.0.0

> 🎉 First production release — stable, self-healing, fully automated.

---

## Highlights

- **Zero-touch automation**: Runs every day at 22:00. No login, no manual trigger, no babysitting.
- **Self-diagnosing**: Three-layer log architecture catches failures at every level — even if Python itself can't start.
- **Phone delivery**: Daily WeChat group message summaries pushed directly to your phone via PushPlus.

---

## What's New

### 🚀 Automated Execution System (V2)

The entire startup chain has been re-engineered for reliability:

```
Task Scheduler → launcher.bat → bootstrap.py → MiruPipeline
      │                │               │              │
      │          Tier 0 log      Tier 1 log     Tier 2 log
      │     (shell checks)   (7 pre-flights)  (full details)
```

- **`launcher.bat`**: Shell-level entry point. Checks `pythonw.exe` and config exist before Python starts. Logs everything — even if Python is completely absent.
- **`bootstrap.py`**: Python pre-flight entry point. 7 staged checks (Python version, dependencies, config validity, platform, admin rights, WeChat status, PushPlus token) with clear pass/fail logging. Only imports heavy modules after all checks pass.

### 📊 Three-Tier Logging

| Level | File | What It Captures |
|---|---|---|
| Shell | `launcher.log` | pythonw.exe existence, config file presence, exit codes |
| Bootstrap | `bootstrap.log` | All 7 pre-flight check results, pipeline summary |
| Pipeline | `miru_*.log` | Full 6-stage execution trace (loguru, auto-rotated) |

Troubleshooting is now systematic: launcher.log → bootstrap.log → miru.log.

### 🔧 Core Pipeline

- **Environment Check**: Detects WeChat process, locates data directory, verifies admin privileges
- **Message Collection**: Extracts encryption keys, decrypts SQLite databases, reads group messages
- **Message Filtering**: Cross-run deduplication, system message removal, rule-based classification
- **LLM Analysis**: DeepSeek API integration with JSON structured output per group
- **Report Generation**: Jinja2 Markdown rendering with AI action suggestions
- **Push Notification**: PushPlus WeChat push with retry and content truncation

---

## Bug Fixes

- **CRITICAL**: Fixed `ERROR_FILE_NOT_FOUND` when Task Scheduler path contains spaces (e.g., `E:\vibe coding\...`). The task now uses `cmd.exe /c "<quoted path>"` instead of calling `pythonw.exe` directly.
- **CRITICAL**: Fixed zero-log failure mode — `data/logs/` is now created at the shell level before any Python code runs, ensuring startup failures are always logged.

---

## Known Issues

See [MIRU_DAILY_REPORT_V1.0_RELEASE.md](./MIRU_DAILY_REPORT_V1.0_RELEASE.md#10-known-issues) for the full list.

| # | Issue | Severity | Planned Fix |
|---|---|---|---|
| 1 | contact.db decryption may fail on some WeChat versions (Name2Id fallback works) | Low | V1.1 |
| 2 | ConsoleNotifier GBK encoding error on emoji (PushPlus unaffected) | Low | V1.1 |
| 3 | `debug_*` files scattered in logs/ directory | Low | V1.1 |
| 4 | Hardcoded E:/ and C:/ paths in diagnostics.py | Low | V1.1 |
| 5 | No daily "all good" notification (only failure alerts) | Medium | V1.2 |
| 6 | `settings.yaml` has no automatic backup | Medium | V1.2 |

---

## Upgrade Notes

### For existing users (pre-V1.0)

1. Pull the latest code
2. No database migration needed (schema unchanged)
3. Reinstall Task Scheduler (required — the action format has changed):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\setup_scheduler.ps1
   ```
4. Test: `launcher.bat`
5. Remove old scheduled task if it exists with a different name

### For new users

See the full deployment guide in [MIRU_DAILY_REPORT_V1.0_RELEASE.md](./MIRU_DAILY_REPORT_V1.0_RELEASE.md#13-deployment).

### Prerequisites

- Windows 10/11
- Python 3.11+
- WeChat PC client (4.x recommended, 3.x supported)
- DeepSeek API key
- PushPlus account and token
- Administrator privileges (required for WeChat process memory access)

---

## Files Changed

| File | Status |
|---|---|
| `launcher.bat` | **New** — Shell-level automation entry point |
| `src/miru/bootstrap.py` | **New** — Python pre-flight entry point |
| `scripts/setup_scheduler.ps1` | **Modified** — V2 Task Scheduler configuration |
| `MIRU_DAILY_REPORT_V1.0_RELEASE.md` | **New** — Release documentation |
| `CHANGELOG.md` | **New** — Version changelog |
| `PROJECT_STATE_V1.0.md` | **New** — Development archive |

---

**Full Changelog**: [CHANGELOG.md](./CHANGELOG.md)  
**Release Documentation**: [MIRU_DAILY_REPORT_V1.0_RELEASE.md](./MIRU_DAILY_REPORT_V1.0_RELEASE.md)  
**Development Archive**: [PROJECT_STATE_V1.0.md](./PROJECT_STATE_V1.0.md)
