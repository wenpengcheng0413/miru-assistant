# Miru Cloud + Home Node — Phase 1 Cloud-ready Backend

**Review:** DESIGN FREEZE / IMPLEMENTATION READY REVIEW  
**Phase:** 1 — Cloud-ready Backend  
**Date:** 2026-08-28 (Asia/Shanghai)  
**Repository:** `E:\vibe coding\miru-assistant`  
**Baseline HEAD:** `194b8442608b3cc516d0a3ddf8118a0695cc0f44`  
**Scope:** backend source and offline tests only. No cloud account, server, Docker, Tailscale, Flutter, Home Node, production configuration, or real database was changed.

> This document contains no Secret Value, API key, token, chat content, WeChat database content, or provider response.

## Executive Result

**PASS — PHASE 1 PASSED**

The Mobile Assistant backend now has an explicit `development`, `cloud`, and future-compatible `node` profile. Cloud startup is dependency-light: it does not prepare the Daily Report import path, load WeChat/Windows modules, initialize Bonjour, or load local SenseVoice/Whisper models. Missing `MIRU_SERVER_TOKEN` fails closed in cloud mode.

Cloud exposes bounded liveness/readiness/status endpoints, keeps REST and WebSocket authentication, filters Windows-only tools out of the cloud LLM schema, adds structured node-unavailable errors, keeps SQLite WAL with a versioned migration mechanism, and removes sensitive response/exception text from the Phase 1 logging paths. Attachment files now have a stable storage key abstraction while the existing development `local_path` behavior remains compatible.

The existing regression suite remains **70/70 passed**. The new Phase 1 suite is **13/13 passed**. The combined run is **83 passed, 1 warning**. The warning is the pre-existing Starlette/httpx TestClient deprecation warning.

`READY FOR PHASE 2 = YES` means Phase 1 acceptance is complete; it does not mean Docker/2 GB resource testing or an Aliyun purchase has been performed.

## Files Changed

### Modified (16)

| File | Phase 1 change |
|---|---|
| `products/mobile-assistant/server/miru_server/config.py` | Adds profile parsing/validation, `MIRU_PROFILE` override, cloud gating for LAN advertisement, local STT, and WeChat tool names; adds explicit CORS origins. |
| `products/mobile-assistant/server/miru_server/main.py` | Cloud fail-closed token gate, no cloud Bonjour task, bounded startup logging, explicit CORS policy, public probe router, and `--profile`. |
| `products/mobile-assistant/server/miru_server/services.py` | Missing MiniMax in cloud is optional and does not block text-chat service construction. |
| `products/mobile-assistant/server/miru_server/api/rest.py` | Adds `/healthz`, `/readyz`, authenticated `/api/status`, bounded compatibility health output, and attachment `storage_key`. |
| `products/mobile-assistant/server/miru_server/attachments.py` | Adds rooted `AttachmentStorage` and stable storage keys; existing upload API remains compatible. |
| `products/mobile-assistant/server/miru_server/tools/base.py` | Adds execution-location metadata and structured `ToolResult` error fields. |
| `products/mobile-assistant/server/miru_server/tools/registry.py` | Adds profile-aware routing, cloud schema filtering, node-unavailable errors, timeout/error codes, and value-free exception logging. |
| `products/mobile-assistant/server/miru_server/db/database.py` | Uses the versioned migration runner after table creation. |
| `products/mobile-assistant/server/miru_server/db/models.py` | Adds cloud-neutral `Attachment.storage_key`. |
| `products/mobile-assistant/server/miru_server/core/llm.py` | Stops logging provider exception bodies and invalid JSON response prefixes. |
| `products/mobile-assistant/server/miru_server/core/pipeline.py` | Background memory failure logs only type/error code. |
| `products/mobile-assistant/server/miru_server/memory/extractor.py` | Same value-free memory extraction logging. |
| `products/mobile-assistant/server/miru_server/tts/queue.py` | Value-free provider/fallback error logging. |
| `products/mobile-assistant/server/miru_server/tts/minimax_tts.py` | Does not log raw malformed SSE response lines. |
| `products/mobile-assistant/server/config/settings.example.yaml` | Documents `profile` and explicit cloud CORS configuration. |
| `products/mobile-assistant/server/README.md` | Documents cloud profile startup and fail-closed token behavior. |

### New (3)

| File | Purpose |
|---|---|
| `products/mobile-assistant/server/miru_server/db/migrations.py` | SQLite schema version and savepoint-protected migrations. Current version is 2. |
| `products/mobile-assistant/server/tests/test_phase1_cloud.py` | 13 offline Phase 1 profile, auth, probe, routing, storage, migration, dependency, CORS, and logging tests. |
| `docs/phase1-cloud-ready.md` | This implementation evidence and acceptance record. |

Flutter source was not modified. No production database file, WAL/SHM sidecar, or original WeChat data was modified.

## New Files

The two implementation files are listed above. `migrations.py` does not migrate the existing production database during this phase; it establishes an idempotent mechanism for a later controlled deployment. The test file uses temporary databases and paths only.

## Architecture Diff

### Before

The default process was Windows-oriented: startup always prepared the Daily Report import boundary, could create and log a temporary server token, started Bonjour discovery, exposed wildcard CORS, and built the full local/WeChat tool registry. SQLite had inline compatibility `ALTER TABLE` checks without a schema version marker. Attachments were represented only by a machine-local path.

### After

`MIRU_PROFILE=cloud` (or `--profile cloud`) selects a bounded cloud process:

- one API process owns REST, WebSocket, Tool Router, Node Manager placeholder, memory/persona/history/cost, and SQLite;
- cloud startup never loads local STT, WeChat, `pymem`, `pysilk`, Daily Report readers, RTX, or ComfyUI;
- cloud startup refuses to run without a resolved `MIRU_SERVER_TOKEN`;
- Windows-only tools are absent from cloud schemas and report `node_not_configured` if a declared node-home tool is encountered;
- attachment metadata persists a stable `storage_key`, while a later worker can replace the current synchronous parser without changing the API contract;
- SQLite remains WAL and versioned; failed migration batches roll back through a savepoint;
- cloud CORS is explicit (empty by default for native Flutter; no `*`).

The Home Node, RPC, Tailscale, external voice provider implementation, worker isolation, Docker limits, and Flutter endpoint migration remain later phases by design.

## Cloud Startup Evidence

The offline Phase 1 tests construct a cloud profile using temporary project/data paths and a fake non-empty LLM key. They verify:

1. `TestClient` lifespan startup succeeds without importing blocked `miru`, `pymem`, `pysilk`, `sherpa_onnx`, `faster_whisper`, or `zeroconf` dependencies.
2. `stt.engine` is forced to `none`, `server.advertise_lan` is false, and WeChat names are removed before service construction.
3. Missing cloud token raises `RuntimeError` before a service runtime is created.
4. No provider API is called; MiniMax missing credentials leave `tts_provider` absent and text services usable.

This is a Windows import-boundary and mocked Linux-like path check. A real Linux image, Docker build, and 2 GB memory benchmark are intentionally deferred to Phase 2.

## Windows Dependency Isolation

The cloud path does not call `ensure_miru_import_path`, does not import Daily Report/WeChat tool implementations in `build_registry`, and does not instantiate `LanServiceAdvertiser`. The `wechat_runtime` module remains the existing boundary for development/node behavior; cloud status is a bounded placeholder and never scans a Windows path. Local STT creation is gated by the cloud profile before `create_stt`/`LazySTT` can run.

Development profile keeps the previous local behavior, including optional WeChat imports and Bonjour best-effort discovery. `node` is accepted as a profile name for future work but has no Home Node implementation in Phase 1.

## Auth Result

- REST routes remain protected by `Authorization: Bearer ...` and constant-time comparison.
- `/ws/session` still requires the first `hello` frame to contain the valid token; wrong tokens close with code `4401`.
- Cloud profile with an empty resolved server token refuses startup; it never invents a token or logs one.
- Development mode may retain its temporary-token compatibility fallback, but the fallback log explicitly does not contain the token value.

## Health / Status Result

| Endpoint | Auth | Contract |
|---|---|---|
| `/healthz` | public | Returns only `{"status":"ok"}`; no database, provider, filesystem, or Home Node check. |
| `/readyz` | public | Checks initialized services, required core config, and `SELECT 1` on SQLite; does not call external providers or Home Node. |
| `/api/status` | Bearer | Returns cloud profile/version, `home_node=not_configured`, and a capability matrix. It contains no local path, token, API key, WeChat key, or WeChat database information. |
| `/api/health` | Bearer | Compatibility endpoint retained, but WeChat diagnostics and local paths were removed. |

Phase 1 status reports WeChat and GPU as unavailable with `node_not_configured`; this is a deliberate graceful degradation, not a startup failure.

## Tool Router Result

`Tool`, `ToolResult`, and `ToolRegistry` were extended rather than rewritten. Metadata supports `execution_location` (`cloud`/`node-home`), `required_node`, `permissions`, `fallback`, `error_code`, and `retryable`. Cloud schemas include only enabled cloud tools. A node-home declaration returns `ok=false`, `error_code=node_not_configured`, `retryable=false` without waiting for a network timeout or touching Windows. Timeouts return `tool_timeout` and are retryable; unexpected failures return a generic `tool_failed` with exception type only in logs.

## SQLite / Migration Result

SQLite remains the only database backend. `init_db` continues to set `journal_mode=WAL` and foreign keys. `migrations.py` reads `PRAGMA user_version`, rejects a newer unsupported database or a missing migration, and applies the current legacy-column and `attachments.storage_key` migrations. A savepoint protects the whole batch so failed DDL/version changes roll back; the current production DB was not opened or migrated in this phase.

## Logging Security Result

Cloud-facing Phase 1 paths no longer log token values, provider exception bodies, invalid JSON response prefixes, raw SSE lines, or raw tool exception text. Error messages prefer an `error_code` and exception type. Health/status responses are bounded and do not include diagnostic paths. Development WeChat tools retain their local result semantics because they are never imported or enabled by cloud startup; they remain a later Home Node redaction boundary.

Cloud CORS no longer uses wildcard origins. Native Flutter does not need browser CORS; browser origins can be explicitly configured later through `server.cors_origins`.

## Attachment Boundary

Phase 1 deliberately does not implement the Phase 9 worker/parser architecture. It adds `AttachmentStorage` with a rooted, traversal-checked `storage_key` (`<attachment-id>/<safe-filename>`), and includes that key in attachment responses. `local_path` remains for current development pipeline compatibility. File-size limits and synchronous extraction remain existing behavior; ZIP/XML/decompression-bomb controls, parser subprocess isolation, one-job concurrency, temporary-disk quotas, and OOM-to-job-failure handling remain Phase 9 work.

## Tests

### Existing regression

Command (from `products/mobile-assistant/server`):

```text
E:\vibe coding\miru-assistant\venv\Scripts\python.exe -m pytest -q --ignore tests/test_phase1_cloud.py --basetemp E:\vibe coding\miru-assistant\.test-tmp-phase1-existing-final
```

Result: **70 passed, 1 warning**.

### New Phase 1 tests

The new `tests/test_phase1_cloud.py` contains **13 passed, 1 warning** tests covering:

- profile gating and optional MiniMax;
- blocked Windows/local-AI imports;
- cloud token fail-closed and profile environment override;
- `/healthz`, `/readyz`, `/api/status`, REST/WS auth;
- non-wildcard CORS;
- cloud/node-home Tool Router behavior and schema filtering;
- rooted attachment storage keys;
- WAL and migration version;
- migration DDL/version rollback safety;
- no response-body logging on JSON failure.

### Combined run

```text
E:\vibe coding\miru-assistant\venv\Scripts\python.exe -m pytest -q --basetemp E:\vibe coding\miru-assistant\.test-tmp-phase1-final
```

Result: **83 passed, 1 warning**. No test calls DeepSeek, MiniMax, PushPlus, DashScope, Tailscale, Aliyun, or any external service.

## Phase 1 Acceptance Criteria

- [x] Cloud Profile exists.
- [x] Cloud startup does not require Windows.
- [x] Cloud startup does not require WeChat.
- [x] Cloud startup does not require a local STT model.
- [x] Cloud startup does not require MiniMax.
- [x] Cloud missing production token fails closed.
- [x] `/healthz` works.
- [x] `/readyz` works.
- [x] Authenticated `/api/status` works.
- [x] WeChat capability reports unavailable.
- [x] Windows Tool does not execute in Cloud.
- [x] Unavailable Tool does not block the cloud service.
- [x] No Windows absolute path is required by the tested cloud startup path.
- [x] No Secret is logged in the covered Phase 1 error paths.
- [x] SQLite WAL still works.
- [x] Versioned migration mechanism and failure rollback work.
- [x] Existing 70 tests still pass.
- [x] All 13 new Phase 1 tests pass.
- [x] Flutter source is unchanged.
- [x] Original database content is preserved; no production DB operation was run.

## Remaining Risks (non-blocking, later phases)

1. Phase 2 must run realistic 2 GB RAM/Docker tests and tune API/worker/parser limits; no Phase 1 number is a memory benchmark.
2. Phase 3 must validate the actual Aliyun profile, disk, IPv4, and pricing before purchase/deployment.
3. Phase 4 must establish Tailscale/Caddy trust boundaries; `/ws/node` must remain private and must not be exposed on a future public host.
4. Phase 5 must move Flutter to the cloud endpoint and prove PC-off operation end to end.
5. Phase 6–8 must implement Home Node/RPC and bounded WeChat results.
6. Phase 9 must replace synchronous attachment parsing with the isolated worker, document-bomb controls, external STT/TTS providers, and OOM recovery specified in the frozen design.
7. Phase 10 must validate backup rotation, monitoring, restore, and recovery on the deployed host.

None of these later-phase risks blocks the Phase 1 cloud-ready backend acceptance.

## Final Status

```text
PHASE 1 PASSED
READY FOR PHASE 2 = YES
```

No Phase 2 operation was started.
