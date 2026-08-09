# Changelog

All notable changes to Miru Daily Report will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — 2026-08-09

### Added

**语音转文字（媒体导出）**
- `media/voice.py` — 从 `media_0.db` `VoiceInfo` 表提取微信语音（SILK V3，按 `svr_id` 关联消息，命中率 99.99%），pysilk 解码为 PCM/WAV
- `media/transcribe.py` — faster-whisper 本地转写封装（懒加载模型、磁盘缓存 `data/stt_cache.json`、hf-mirror 模型下载）
- `chat.txt` 语音行渲染 `[语音转文字] 文本（时长 Xs）`，转写失败降级 `[语音] (时长 Xs)`

**图片保留（媒体导出）**
- `media/image.py` — 微信 4.x 图片 `.dat` 解密（V1 固定密钥 / V2 内存密钥，AES-128-ECB + XOR 分段），attach 目录定位（`msg/attach/MD5(wxid)/YYYY-MM/Img/`），格式嗅探（jpg/png/gif/webp/bmp）
- `media/v2key.py` — V2 AES 密钥进程内存扫描（32-hex + 签名附近原始块 + 完整虚拟内存遍历），`.dat` 解密验证筛选，磁盘缓存
- 解密失败自动保留 `.dat` 原件并标注 `[图片未解密]`；成功导出到 `media/img/` 并在 `chat.txt` 引用路径
- `media/processor.py` — 媒体处理编排（MediaConfig 配置注入、语音/图片批量处理、进度日志）

**集成与配置**
- `offline_exporter.py` — `export()` 新增 `media_config` 参数，渲染 overrides 支持语音转写/图片路径
- `cli/main.py` — `miru export --with-media/--no-media` 开关（覆盖 settings 配置）
- `scripts/analyze_all.py` — `--with-media/--no-media` 透传 + `--parallel` 并行处理 + 汇总显示转写/图片统计
- `settings.yaml` — `miru.export.media` 配置段（enabled/images/voice_transcribe/stt_model/stt_cache/keep_voice_files/convert_wxgf）
- 依赖新增：`pysilk`（SILK 解码）、`faster-whisper`（本地 STT）

**图片色度问题修复（微信 WXGF/HEVC 私有格式）**
- 实测确认：微信 4.x 高清原图为私有 HEVC 编码（slice_qp_delta=-110 超标准范围），
  ffmpeg 8.1.2 / libde265 1.1.1 均无法恢复色度（U/V 平面全丢，输出绿色图）
- 解决方案：图片导出改用微信标准缩略图（`_t.dat`，标准 jpg，颜色正确），
  高清原图解密后保留 `.wxgf` 备份（微信客户端可正常查看）

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
