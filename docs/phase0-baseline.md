# Miru Cloud + Home Node — Phase 0 Baseline

**Review type:** DESIGN FREEZE / IMPLEMENTATION READY REVIEW  
**Execution scope:** Phase 0 — Baseline / Backup / Security Preparation only  
**Audit timestamp:** 2026-08-28 (Asia/Shanghai)  
**Frozen design source:** `E:\vibe coding\Miru Cloud + Home Node 专项实施设计.md`

> The original Phase 0 run recorded read-only evidence and local backup artifacts. Phase 0.1B subsequently changed only the two explicitly authorized ignored `settings.yaml` files and current-user Secret environment variables; no Miru source, Flutter code, database schema, Windows startup item, WeChat code, or cloud resource was changed.

## 1. Executive Result

**PASS**

The code/test baseline and both database backup drills passed. Phase 0.1B migrated the four literal credential fields from the two ignored, non-tracked `settings.yaml` files into three current-user environment variables, without printing, hashing, encoding, or copying any Secret Value. A value-free re-audit now reports zero literal credentials.

No production secret was found in the tracked current tree or in the tested Git history token-signature scan. DeepSeek and PushPlus provider rotation remains recommended before public cloud exposure; it is not a local migration blocker.

**Phase 1 was not started.**

## 2. Git / Environment Baseline

Repository: `E:\vibe coding\miru-assistant`  
Git root: `E:/vibe coding/miru-assistant`  
Branch: `master`  
HEAD: `194b8442608b3cc516d0a3ddf8118a0695cc0f44`  
Tracked files: 250  
Tracked modifications: 0  
Untracked status entries: 629 (workspace already dirty, primarily generated test-artifact directories; not removed)  
Ignored status entries reported by Git: 109,161 (includes ignored data/output trees; names were not exported)

Git emitted a pre-existing permission warning while reading the user-level global ignore file. Repository resolution and status still completed. No cleanup, reset, stash, commit, or history rewrite was performed.

Runtime:

- Python: 3.12.10, 64-bit Windows, from `miru-assistant/venv/Scripts/python.exe`.
- Flutter CLI: not available on PATH in this shell; Flutter source was inspected but no Flutter command was run.
- All 18 expected key source files for the Miru mobile assistant audit were present.
- Frozen-design marker check: no material design drift detected. The 2 vCPU / 2 GB RAM / 50–60 GB SSD baseline remains authoritative; 2C4G is upgrade-only and 2C1G is experimental.

## 3. Test Baseline

Command:

```text
E:\vibe coding\miru-assistant\venv\Scripts\python.exe -m pytest -q --basetemp E:\vibe coding\miru-assistant\.test-tmp-final-doc
```

Result: **70 passed, 1 warning**, approximately 5.94 seconds.  
Warning: Starlette deprecation warning related to the current `httpx`/`TestClient` combination. It is recorded, not fixed in Phase 0.

The test run may create untracked temporary artifacts. Existing and newly observed artifacts were left intact as required.

## 4. SQLite Backup

Source: `products/mobile-assistant/server/data/miru_server.db`  
Observed source sidecars: `.db` 3,489,792 bytes; `.db-wal` 4,124,152 bytes; `.db-shm` 32,768 bytes.

Backup artifact:

`E:\vibe coding\miru-phase0-backup\20260828-131528\database\miru_server-phase0.db`

- Method: Python `sqlite3.Connection.backup()` (SQLite Backup API), not a raw file copy.
- Backup size: 3,665,920 bytes.
- SHA-256: `01D1256379D26B63697117B38576B8D386FCC64A2E685144306C36655D6675F4`.
- `PRAGMA integrity_check`: `ok`.
- Schema table count: 16.
- Schema includes the expected conversation, message, trace, attachment, WeChat metadata/transcript, tool-call, usage/budget, and memory tables.
- No database row bodies, message text, media, keys, or chat content were exported.

## 5. SQLite Restore Drill

An isolated copy was created at:

`E:\vibe coding\miru-phase0-backup\20260828-131528\restore-drill\miru_server-restore-drill.db`

- Restore SHA-256 matched the Backup API artifact.
- `PRAGMA integrity_check`: `ok`.
- Schema table count: 16.
- Read-only row-count comparison completed without exporting row content.
- The original database and its WAL/SHM sidecars were not modified.

**SQLite backup:** PASS  
**Isolated restore drill:** PASS

## 6. Attachment Baseline

Source directory: `products/mobile-assistant/server/data/attachments`

- Files: 14.
- Aggregate bytes: 866,638.
- Attachment table rows: 14.
- DB-declared aggregate bytes: 866,638.
- DB paths missing on disk: 0.
- Orphan files not represented by DB metadata: 0.
- External backup: `E:\vibe coding\miru-phase0-backup\20260828-131528\attachments\` (14 files, 866,638 bytes).
- Integrity method: aggregate count/size plus DB-path existence and orphan comparison. No filenames or file bodies were written to the report.

Current implementation evidence to carry into later phases:

- Upload handling reads up to the configured file limit plus one byte into request memory.
- Document extraction currently occurs synchronously in the request path.
- Accepted formats include common image/PDF/Office/text types; `.xls` compatibility is not yet a deployment guarantee.
- Conversation deletion removes database rows but does not establish a complete attachment-file lifecycle cleanup.

These are design inputs for the isolated Attachment Worker, one-job concurrency, document-bomb limits, temporary-disk quota, and OOM recovery specified in the frozen design. No attachment code was changed.

## 7. WeChat Data Boundary

Read-only source audit confirmed the following boundary.

### Home Node only / never raw cloud

- `products/daily-report/src/miru/collector/wechat_db_decrypt.py`: process-memory access (`pymem`) and Windows-only database-key/decryption workflow.
- `products/daily-report/src/miru/chat_analyzer/offline_reader.py`: local SQLite account/database reads and local account paths.
- `products/daily-report/src/miru/chat_analyzer/media/voice.py`: local voice database/media access and `pysilk` decoding.
- `products/daily-report/src/miru/chat_analyzer/media/image.py` and `v2key.py`: local media and process-key handling.
- `products/mobile-assistant/server/miru_server/wechat_runtime.py`: local snapshot/runtime management; current snapshot copy is near-raw and remains local.
- `products/mobile-assistant/server/miru_server/tools/builtin/wechat.py`: tool wrapper that must route to Home Node RPC, not execute cloud-side WeChat access.

### Cloud allowed

- Bounded status and error codes.
- Tool availability/online state.
- User-requested, minimum-necessary aggregates or summaries.
- Explicitly approved redacted result payloads (C2 recommended sync mode).
- Code and non-secret schemas.

### Local only

- Decrypted WeChat databases while being read.
- Temporary media, process keys, local source paths, and unsubmitted raw attachments.
- Windows account directories and local RTX/ComfyUI work files.

### Never cloud

- Original WeChat databases.
- Any database/decryption key.
- Near-raw `wechat_snapshot` content.
- Full media collections.
- Raw chat exports or unrestricted full chat text.

Observed local scale (metadata only): `wechat_snapshot` contains approximately 82,004 files and 12,546,099,823 bytes. It is not a candidate for cloud upload or a 2C2G disk migration.

## 8. Secret Inventory

The audit intentionally inspected names, metadata, safe examples, and redacted classifications only. It did not print or export any `.env`, real `settings.yaml`, token, password, key, database value, log body, or chat content.

### Tracked examples

- `products/mobile-assistant/server/.env.example`: five empty environment-variable slots (`MIRU_DEEPSEEK_API_KEY`, `MINIMAX_API_KEY`, `MINIMAX_GROUP_ID`, `MIRU_SERVER_TOKEN`, `DASHSCOPE_API_KEY`).
- `products/mobile-assistant/server/config/settings.example.yaml` and the Daily Report example files contain placeholders/environment references, not observed production values.

### Current ignored configuration

The following files are ignored and not tracked. Their credential fields are now environment references; no literal credential remains:

- `products/daily-report/config/settings.yaml` — DeepSeek and PushPlus fields use environment references.
- `products/mobile-assistant/server/config/settings.yaml` — server, DeepSeek, and MiniMax fields use environment references; Group ID remains an identifier.

The new `MIRU_SERVER_TOKEN` was generated locally from a system-safe random source and stored at current-user scope. No value was written to this report, Git, or another file.

The values were not read, copied, hashed, or printed. They must be treated as real until verified and rotated/removed by the owner. This is the Phase 0 blocker.

## 9. Git Secret History Audit

Audited the tracked tree and reachable Git history without emitting matching lines or values.

- No high-confidence provider-token signatures were found in the current tracked tree: `sk-…`, AWS access-key style, GitHub PAT style, Slack token style, or PEM private-key headers: 0 matches.
- No such signatures were found in reachable history commits: 0 matching commits in the scan.
- Example/document references such as `sk-xxx`, environment-variable names, and “new API key” instructions were classified as placeholders/documentation.
- Tracked tree and reachable history are **PASS**. The ignored target configuration re-audit is also **PASS** after migration.

No rotation, deletion, history rewrite, or commit operation was performed.

## 10. Logging Risk Inventory

Source-only logging review found no change applied in Phase 0.

| Risk | Evidence area | Severity | Phase 0 handling |
|---|---|---:|---|
| Random server token can be logged when configured token is absent | `miru_server/main.py` startup path | P1 | Record; fix in Phase 1 security work |
| Health/diagnostic response exposes WeChat runtime details and paths | `miru_server/api/rest.py` health endpoint and `runtime_diagnostics` | P1 | Record; later return bounded/redacted status |
| Failed LLM response text prefix can enter logs (up to 200 chars) | `miru_server/core/llm.py` | P1 | Record; redact/truncate by field class in Phase 1 |
| Exception text may include provider/path details | registry/tool and service exception logging | P2 | Record; normalize error codes later |
| Conversation IDs, modes, personas, and tool names in metadata logs | WebSocket/pipeline logs | P2 | Keep identifiers redacted/short-lived in target design |
| Wildcard CORS is present in current app setup | `miru_server/main.py` | P1 | Record; constrain to explicit cloud origins later |

Logs were not opened or exported. Existing local log metadata was only counted (six files, 222,754 bytes).

## 11. Cloud Blocking Dependency Inventory

| Dependency / behavior | Classification | Target boundary |
|---|---|---|
| FastAPI/Starlette REST and WebSocket | Portable cloud | Miru API, one Uvicorn worker |
| SQLAlchemy + SQLite WAL | Portable cloud | Cloud volume; no Redis/PostgreSQL/RDS in baseline |
| Tool registry/router, memory/persona/history/cost pipeline | Portable cloud | API process |
| `pymem`, Windows process memory, local WeChat DB/key access | Cloud blocker | Home Node only |
| `pysilk`, local voice/image databases and media keys | Cloud blocker | Home Node only |
| `wechat_runtime` raw/near-raw snapshot | Cloud blocker | Home Node local storage only |
| SenseVoice/ONNX local model (approximately 937,617,178-byte model file) | Cloud blocker under 2C2G | Never load in cloud; use external STT API |
| Whisper/faster-whisper/sherpa-onnx class local inference | Cloud blocker under 2C2G | Never load in cloud; external STT/TTS providers |
| Absolute Windows paths and drive-letter file tools | Portable only after boundary | Home Node RPC; cloud receives bounded results |
| Flutter client | Portable client | Cloud endpoint/status contract in later Phase 5 |

Observed local model inventory is approximately 937,933,072 bytes across two files. Models, RTX, ComfyUI, and Windows-only tools are excluded from the cloud resource budget.

## 12. Backup Manifest

Detailed manifest (also intentionally free of filenames, row bodies, keys, and chat content):

`E:\vibe coding\miru-phase0-backup\20260828-131528\phase0-manifest.md`

Backup root:

`E:\vibe coding\miru-phase0-backup\20260828-131528\`

The backup is an external local artifact. It is not a production configuration, deployment, or source change.

## 13. Problems Found (P0–P3)

### P0 — resolved

1. The previous ignored-configuration Secret blocker was resolved by local environment migration. DeepSeek and PushPlus rotation remain recommended before public cloud exposure.

### P1 — must be addressed before public/cloud exposure

1. Startup fallback token logging.
2. Health diagnostics/path disclosure.
3. LLM failure text logging.
4. Wildcard CORS.
5. Attachment parsing currently in request memory/path; target must use an isolated worker, strict parser limits, timeout, temporary disk quota, and OOM-to-`resource_exhausted` job failure.

### P2 — design/implementation follow-up

1. Attachment file lifecycle cleanup and orphan monitoring.
2. `.xls` parser compatibility and malformed Office/PDF handling.
3. Normalized error codes and redacted exception logging.
4. Absolute-path assumptions in local tools.

### P3 — observation

1. Current test warning from Starlette/httpx compatibility.
2. Flutter CLI is not installed on this shell; client tests remain a later environment check.

## 14. Phase 0 Acceptance Criteria

- [x] Frozen design rechecked; no material drift found.
- [x] Git branch, HEAD, status, runtime, and test command recorded.
- [x] Current baseline tests executed: 70 passed, one warning.
- [x] SQLite Backup API artifact created outside the repository.
- [x] Backup integrity validated.
- [x] Isolated restore drill completed and validated.
- [x] Attachment count/bytes, DB existence comparison, and external copy recorded.
- [x] WeChat/Windows/large-model cloud boundary recorded.
- [x] Tracked-tree and reachable-history token-signature audit completed without exposing values.
- [x] Logging/privacy risks inventoried without exporting logs.
- [x] No Miru business source, Flutter code, database schema, production config, or startup item modified.
- [x] Current ignored configuration is cleared of literal-credential risk.
- [x] Phase 0 Secret Gate can be declared passed.

## 15. Updated Implementation Readiness Gate

```text
[x] Current baseline tests pass
[x] Backup validated
[x] Restore validated
[x] Secret inventory completed (zero literal credentials after migration)
[x] No production secret committed (tracked tree/history scan passed)
[ ] Cloud profile defined (intentionally deferred; no profile created in Phase 0)
[x] Windows-only dependency boundary confirmed
[ ] 2GB test environment available (required in Phase 2)
[x] Rollback path defined (external backup + isolated restore artifact)
[x] Phase 1 acceptance criteria frozen in the design document
```

### Final Phase 0 status

```text
PASSED
```

Secret Gate result: **PASSED**. Four literal credential field instances were migrated to three current-user environment variables; MiniMax remains optional for Phase 0 and no provider API was called. DeepSeek and PushPlus rotation are recommended before public cloud exposure.

```text
PHASE 0 PASSED
READY FOR PHASE 1 = YES
Phase 1 NOT STARTED
```
