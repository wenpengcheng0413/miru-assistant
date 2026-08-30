# Miru Cloud + Home Node — Phase 4 Final Execution Runbook

**Planning date:** 2026-08-28  
**Document status:** FINAL PLAN / NOT EXECUTED  
**Execution boundary:** This document was produced by read-only audit and planning. Phase 4 was not executed while writing it.

## 0. Controlling scope

```text
Frozen Phase 4 Scope = Phase 4 — Tailscale + HTTPS
Required enabling subset = first Miru Cloud API + loopback Caddy production deployment
Ingress = Tailscale Serve private HTTPS/WSS only
Permanent Flutter cutover = Phase 5
Home Node/RPC = Phase 6+
WeChat = Phase 8
Attachment worker and Cloud STT/TTS = Phase 9
Full backup/monitoring/recovery = Phase 10
```

The enabling deployment is in scope because the frozen Phase 4 gate requires a working
`miru-cloud.<tailnet>.ts.net` HTTPS/WSS endpoint and a streaming test. It does not broaden
Phase 4 into the later Flutter, Home Node, WeChat, attachment-worker, voice, or public-domain
phases. No custom domain, ICP action, DNS change, Tailscale Funnel, public HTTP(S) listener,
or Home Node inbound listener is allowed.

## 1. PHASE 4 RECONSTRUCTED BASELINE

### 1.1 Local repository

| Fact | State | Evidence / consequence |
| --- | --- | --- |
| Repository | VERIFIED | `E:\vibe coding\miru-assistant`, branch `master`, HEAD `194b844`, aligned with `origin/master` at audit time. |
| Worktree | VERIFIED | Dirty: 16 modified backend files plus untracked Phase 1/2 deployment, tests, docs, benchmark, and temporary artifacts. Do not clean, reset, stash, or assume HEAD alone identifies the build. |
| Phase gates | VERIFIED | Phase 0 PASS; Phase 1 PASS (83 tests at that gate); Phase 2 PASS (89 tests, 2C2G verified); Phase 3B PASS. |
| Current source tests on planning day | INFERRED | Latest recorded complete backend result is `89 passed, 1 warning`; tests were not rerun during this read/audit/plan-only turn. Execution must rerun them. |
| Secret signature scan | VERIFIED | No high-confidence private-key, Tailscale-key, `sk-*`, or long Bearer signature in the audited working tree. This is not proof that every arbitrary string is non-secret. |
| Flutter | VERIFIED | Existing settings UI can temporarily set an HTTPS base URL and stores its token in secure storage. Its defaults/error text remain LAN-oriented; permanent Cloud cutover is Phase 5. |

### 1.2 Backend and Docker artifacts

| Fact | State | Evidence / consequence |
| --- | --- | --- |
| Cloud profile | VERIFIED | Fail-closed `MIRU_SERVER_TOKEN`; no Bonjour; local STT disabled; WeChat tools excluded from Cloud tool schema; `/healthz`, `/readyz`, authenticated `/api/status`; SQLite schema version 2; attachment `storage_key`. |
| Cloud image | VERIFIED | Phase 2 Dockerfile is Linux/amd64, Python 3.12, non-root UID/GID 10001, and excludes models, Daily Report, Flutter, data, WeChat snapshots and Windows-only packages. Recorded inspect size 109,548,179 bytes; logical listing 453 MB. |
| Phase 2 Compose | VERIFIED / NOT PRODUCTION | Synthetic fixed tokens, mock provider URL, named test volume, project `miru-phase2`. It must never be copied to production unchanged. |
| Phase 2 Caddyfile | VERIFIED / NOT PRODUCTION | Local `127.0.0.1:18080` topology is useful, but `header -Tailscale-*` manipulates response headers, not upstream request headers. Production must use `request_header` or avoid trusting these headers. |
| Current attachment path | VERIFIED | Synchronous in API process; safe only for the bounded Phase 2 fixture. Parser isolation/bomb protection remains Phase 9. Phase 4 uses 10 MB limit and does not claim full attachment production readiness. |
| Current backup implementation | VERIFIED | SQLite Backup API and day retention exist. Complete cloud attachment backup, off-host copy, long retention and recovery automation remain Phase 10. |

### 1.3 Production host (read-only SSH verification, 2026-08-28)

| Fact | State | Evidence / consequence |
| --- | --- | --- |
| OS/resources | VERIFIED | Ubuntu 22.04 x86_64, 2 vCPU, 2,010,704 KiB RAM, 2 GiB swap, ext4 50 GB root, 40 GB free, swappiness 10. |
| Docker | VERIFIED | Engine/CLI 29.7.2, Compose 5.5.0, overlayfs, json-file logging, Docker/containerd enabled and active. Zero containers; one Phase 3B probe image. |
| Host paths | VERIFIED | `/opt/miru/app` `ubuntu:ubuntu 0750`; `/opt/miru/data` `10001:10001 0750`; `/opt/miru/backups` `root:root 0700`; `/opt/miru/logs` `ubuntu:ubuntu 0750`; all empty. |
| Host firewall/listeners | VERIFIED | UFW active, deny inbound/routed, allow outbound; only 22/tcp allowed for IPv4/IPv6. Only SSH is a public TCP listener. No 80/443/8765/18080 listener. |
| Tailscale | VERIFIED | Not installed. |
| Caddy | VERIFIED | No host Caddy package/service. Caddy will be a container bound to loopback only. |
| Production data/secrets | VERIFIED | No Miru files below `/opt/miru`, no DB, attachment, backup, env file, token, API key, WeChat material or media. |
| Tencent console firewall/security group | UNKNOWN | Host commands cannot prove console rules. User must inspect it; Phase 4 must not add public business ports. |
| Tailnet/policy/MagicDNS/HTTPS/iPhone membership | UNKNOWN | Requires the user's authenticated Tailscale admin console. |

### 1.4 Phase 3B inheritance

Do not reinstall Docker, recreate swap, redo SSH hardening, reset UFW, or upgrade Ubuntu.
Docker Hub registry/auth timeout is inherited. No random mirror, daemon proxy, Docker Hub
login, insecure registry, or global registry mirror may be introduced.

### 1.5 Current network and regulatory conclusion

Tencent's current official material says a website or APP served publicly from a mainland
China host must be filed before public service, and even IP-only non-commercial public web
service requires filing while Tencent's filing system currently expects a domain. Therefore
Phase 4 selects no public web service at all. Tailscale Serve is reachable only by authorized
tailnet members over an encrypted overlay; Security Group/UFW keep 80/443/8765/18080 closed
on the public interface. This is an architecture inference, not legal advice. If the service is
later made available to non-tailnet users, STOP and enter a separate domain/ICP/public-ingress
phase first.

## 2. PHASE 4 ARCHITECTURE DECISIONS

### 2.1 Public/private ingress

```text
Decision = Model 2, Tailscale private-only. Serve HTTPS 443 -> 127.0.0.1:18080 Caddy -> private Compose network -> Miru API:8765.
Why = Single user; mainland host; no custom domain/ICP; frozen design; no need for a public business port.
Rejected alternatives = Direct public IP; public Caddy + App token; hybrid mode; Funnel.
Risk = Tailnet control-plane/account compromise or overly broad default policy.
Rollback = tailscale serve reset; stop Compose; no public firewall change to undo.
Future migration path = After domain/ICP, add a separate public Caddy host while keeping `/ws/node` tailnet-only.
```

### 2.2 Tailscale

```text
Decision = Host-installed stable Tailscale; interactive browser authorization; neutral node name `miru-cloud`; MagicDNS + HTTPS; explicit Grants policy.
Why = Persistent server identity without placing auth keys in files, commands, chat, Git, or images.
Rejected alternatives = Reusable auth key, embedded sidecar, Funnel, FRP, family router forwarding.
Risk = Enabling HTTPS publishes the machine FQDN to Certificate Transparency; reauth can cut remote access.
Rollback = Reset Serve first; retain public key SSH; user may remove the device and run logout if fully withdrawing it.
Future migration path = Tag the server and automate enrollment later with a one-off/OAuth-issued key held by a proper secret store.
```

Before enabling HTTPS, the user must confirm neither machine name nor randomized tailnet name
contains a private identity. Do not run forced reauthentication over a Tailscale-only SSH session;
public key SSH or provider console must remain available. For compromise recovery: reset Serve,
remove the device in the Machines page, rotate App/provider secrets, then re-enroll. Revoking an
auth key alone does not deauthorize an already enrolled node.

### 2.3 Caddy

```text
Decision = Caddy container on host loopback 127.0.0.1:18080 only; Serve terminates `.ts.net` TLS; Caddy performs routing and WS proxy.
Why = Matches frozen trust boundary and the validated Phase 2 topology without public certificate automation.
Rejected alternatives = Host Caddy package, Caddy public 443, Serve direct to API.
Risk = Misusing response-header directives or exposing 18080 on all interfaces.
Rollback = Revert release/Caddyfile or stop Caddy; Serve then returns upstream failure but remains private.
Future migration path = A separate public hostname/profile after ICP; Node paths stay denied on public host.
```

Phase 4 Miru does not authorize from Tailscale identity headers; it retains the application token.
Serve already strips spoofed incoming identity headers. Production Caddy additionally removes
those headers before Miru using `request_header`, so Miru cannot accidentally trust them. Block
`/api/wechat/*`, `/api/debug/*`, and `/ws/node*` at Caddy in this phase.

### 2.4 Docker artifact delivery

```text
Decision = Option A: local linux/amd64 build, immutable build tag, docker save, SHA-256, SCP, verify, docker load. Transfer the pinned Caddy image in the same bundle.
Why = Small single-host system; current image content about 110 MB; 4 Mbps is adequate; no registry credential; source stays local; exact tar supports rollback.
Rejected alternatives = Source upload/build (Docker Hub/base-image dependency and source exposure); TCR now (account/network/credential/SLA complexity); Docker Hub push (forbidden); random mirror (forbidden).
Risk = Dirty worktree and mutable base tags reduce reproducibility unless the exact manifest, image ID and tar hash are recorded.
Rollback = Load/retag the retained previous tar and switch the release symlink.
Future migration path = When update frequency justifies it, use private Tencent TCR with digest pins and least-privilege pull credentials.
```

### 2.5 Compose and secrets

```text
Decision = Separate `miru-prod`; restart unless-stopped; one API; one Caddy; bind data; read-only roots; tmpfs; existing Phase 2 resource limits; no mock/worker.
Why = Minimal single-user 2C2G topology already validated.
Rejected alternatives = Deploying Phase 2 Compose, Kubernetes, database/message-broker services.
Risk = Compose `environment`/`env_file` values appear in docker inspect to Docker admins.
Rollback = Release-local Compose plus immutable images; switch `current` and restart.
Future migration path = Add worker only in Phase 9 after resource validation.
```

Secrets are host files `/opt/miru/secrets/server_token` and `deepseek_api_key`, owner
`10001:10001`, mode `0400`, directory `0700`. They are bind-mounted read-only and read by a
literal entrypoint script; values are never present in Compose `environment`, image metadata or
Docker inspect Config.Env. They remain visible to root, a Docker administrator, or process-level
inspection; Docker group membership is root-equivalent. Do not add PushPlus in Phase 4: the Cloud
backend does not use it. Never back up the secret directory. Rotation uses a new file, validation,
atomic rename and API restart; retain an offline previous value only for a bounded rollback window.

### 2.6 SQLite, attachments and backup

```text
Decision = Fresh production DB under `/opt/miru/data`; schema v2 migration on first start; no Windows DB import. Attachments share `/opt/miru/data/attachments` with 10 MB file limit.
Why = Frozen single-user SQLite WAL model and existing UID 10001 ownership.
Rejected alternatives = Uploading Windows DB, NFS, RDS/Postgres, COS/S3/MinIO.
Risk = Startup migration is not a downgrade mechanism; synchronous parsers are not Phase 9-safe.
Rollback = Before later migrations use SQLite Backup API; on failure stop and quarantine, never overwrite. First-deploy rollback preserves the fresh DB offline.
Future migration path = Phase 9 worker/storage limits; Phase 10 complete DB+attachment backup/off-host recovery.
```

Phase 4 performs one post-start SQLite Backup API snapshot and isolated integrity/read drill.
This is a rollback proof, not the final Phase 10 backup system. No unlimited retention: keep at
most 7 Phase 4 operator snapshots locally; never include secrets.

### 2.7 Flutter and Home Node boundary

```text
Decision = No Flutter source modification. Existing settings may be changed manually for a bounded iPhone 5G acceptance test, then either retained by user choice or restored. Permanent profile/default work is Phase 5.
Why = Avoids destabilizing current LAN client while still satisfying the frozen mobile-network endpoint test.
Rejected alternatives = Editing Dart defaults in Phase 4 or skipping mobile-path validation.
Risk = Current UI text still refers to LAN/8765; user may confuse temporary and permanent configuration.
Rollback = Restore the prior base URL/token in App settings.
Future migration path = Phase 5 development/tailnet/public profiles and Cloud/Node status UI.
```

Windows may join the same tailnet in Phase 4 as an ordinary client for verification. It does not
run Node software, listen publicly, expose a router port, or send WeChat data. Raw WeChat DB,
keys, snapshots, chat, media and local runtime state remain on Windows.

## 3. Production configuration contract

The execution model must create release-local, non-secret files from this contract. Do not edit
the Phase 2 files in place.

### 3.1 `compose.production.yaml`

- Project name `miru-prod`; services only `miru-api` and `caddy`.
- Image references come from non-secret `.release.env` (`MIRU_IMAGE_REF`, `CADDY_IMAGE_REF`).
- API: UID/GID `10001:10001`; `/opt/miru/data:/app/data`; two fixed secret-file binds to
  `/run/secrets/*`; `read_only`; `/tmp` tmpfs 64 MB; `cap_drop: [ALL]`;
  `no-new-privileges:true`; 640 MB RAM, 768 MB memory+swap, 1 CPU, 128 PIDs;
  `restart: unless-stopped`; expose 8765 only; healthcheck `/healthz`.
- API command must literally read the two mounted files, export `MIRU_SERVER_TOKEN` and
  `MIRU_DEEPSEEK_API_KEY`, then `exec python -m miru_server --profile cloud --host 0.0.0.0
  --port 8765`. The Compose file contains no secret value.
- Non-secret environment only: `MIRU_PROFILE=cloud`, config path, build ID, and fixed DeepSeek
  base URL if the YAML uses a reference.
- Caddy: only `127.0.0.1:18080:8080`; config read-only; private Compose network; 96 MB RAM,
  128 MB memory+swap, 0.2 CPU, 64 PIDs; restart/healthcheck; no public port.
- Per-service Docker logs `json-file`, `max-size=10m`, `max-file=3` (stricter than inherited
  daemon 20m x3).
- No `container_name`; Compose project isolation is sufficient and avoids name collisions.

### 3.2 `settings.production.yaml`

- `profile: cloud`; token and API key remain `${...}` references.
- DeepSeek `base_url: https://api.deepseek.com`, model `deepseek-v4-flash`, no real-provider
  value in the file; `stt.engine: none`; `tts.provider: none`.
- Cloud tools only; no name starting `wechat_`.
- `db.path: ./data/miru_server.db`; attachment dir `./data/attachments`; max file 10 MB.
- `backup.enabled: false` for Phase 4. Operator backup is explicit; Phase 10 will own scheduling.
- Explicit empty CORS origins; Bonjour is disabled by Cloud profile.

### 3.3 `Caddyfile.production`

- Listen `:8080` inside the container; no auto public TLS/domain.
- Return 404 for `/api/wechat/*`, `/api/debug/*`, and `/ws/node*`.
- Set request-body maximum to 12 MB (multipart overhead over the 10 MB application file cap).
- Remove request headers `Tailscale-User-Login`, `Tailscale-User-Name`,
  `Tailscale-User-Profile-Pic`, and `Tailscale-App-Capabilities` with `request_header`.
- Reverse proxy `miru-api:8765`; WebSocket upgrade is automatic. Use streaming-friendly flush
  behavior and do not impose a finite WS stream timeout in Phase 4.
- Do not enable request access logs in Phase 4; URI query strings can contain private search
  terms. Caddy runtime/error output and Docker logs are sufficient. Revisit redacted access logs
  in Phase 10. Caddy's default credential-header redaction is not permission to log bodies.

## 4. PHASE 4 FINAL EXECUTION RUNBOOK

### Command conventions

- Local commands are PowerShell in repository root. Remote commands are Ubuntu shell after
  key-auth SSH as `ubuntu`. Never embed a public IP, token or API key in this tracked document.
- Define non-secret `BUILD_ID` as `p4-YYYYMMDD-HHMM-<short-head>-<manifest8>` and use it exactly.
- Every `sudo`, Tailscale browser consent, console policy/firewall operation, and secret entry is
  an explicit user gate. Never request a secret in chat.
- On any FAIL/STOP, do not continue merely because the next command might fix it.

### P4-R0 — Baseline reconciliation and source freeze

**Objective:** prove execution starts from the audited state and identify the exact dirty-tree build input.  
**Preconditions:** Phase 3B report and this runbook available; no server mutation begun.  
**Read-only Checks:** `git status --short --branch`; `git diff --check`; `git log -1 --oneline`; compare Phase documents; SSH the same key-pinned host and repeat OS/resource/UFW/listener/Docker/path checks.  
**Commands:** run backend tests with the repository venv, `PYTHONDONTWRITEBYTECODE=1`, pytest cache disabled and a new workspace `--basetemp`; hash every Dockerfile COPY input plus production config files into `source-manifest.sha256`; compute `BUILD_ID`.  
**Mutations:** only test temp files and an execution evidence directory under `docs/evidence/phase4/<BUILD_ID>`; no source cleanup.  
**Verification:** 89 or more expected tests pass with only documented warning; manifest has no data/model/WeChat/settings/secret path; host still has zero containers and only SSH public.  
**PASS Criteria:** test, manifest, Git, host and Phase 3B facts reconcile.  
**FAIL Criteria:** regression, secret signature, unexpected listener/container/file, changed host identity, or unreviewed Docker build input.  
**Rollback:** remove only the newly created test/evidence temp path if desired; never delete pre-existing untracked files.  
**SSH Risk:** read-only; key fingerprint must match known host.  
**Secret Risk:** do not run `env`, `set`, `docker inspect` on future production containers, or print settings.  
**User Action Required:** approve the exact dirty-tree manifest as the release source.  
**STOP Conditions:** user does not approve manifest; any Phase 3B drift; console target cannot be unambiguously matched.

### P4-R1 — Prepare and statically validate production definitions

**Objective:** create the three files in section 3 without modifying business code or Phase 2 fixtures.  
**Preconditions:** P4-R0 PASS and BUILD_ID fixed.  
**Read-only Checks:** inspect current Dockerfile/requirements/settings and current official DeepSeek model list.  
**Commands:** create `deploy/production/compose.production.yaml`, `settings.production.yaml`, and `Caddyfile.production`; run `docker compose --env-file <non-secret-release-env> config`; run Caddy `validate` in the locally pinned image; run secret-signature and forbidden-string checks.  
**Mutations:** tracked-safe deployment definitions only; `.release.env` and evidence artifacts stay ignored/untracked.  
**Verification:** rendered Compose has no `phase2-test`, mock service, public bind, secret value, WeChat tool, source/data mount, or Docker Hub credential.  
**PASS Criteria:** contract 3.1–3.3 fully satisfied and static tests pass.  
**FAIL Criteria:** any secret in rendered config; Caddy validation failure; port bind other than loopback 18080; identity headers not removed as request headers.  
**Rollback:** revert only the newly created production definitions after preserving evidence; do not touch existing user work.  
**SSH Risk:** none.  
**Secret Risk:** use synthetic non-secret files for local config rendering; never reference Windows user Secret environment variables.  
**User Action Required:** review that public ingress and later-phase routes are absent.  
**STOP Conditions:** production contract requires a business-code change; return to architecture review rather than silently changing scope.

### P4-R2 — Build, pin, scan and export artifacts locally

**Objective:** produce immutable linux/amd64 Miru and Caddy image artifacts without a registry.  
**Preconditions:** P4-R1 PASS; local Docker available; no real secrets in build environment.  
**Read-only Checks:** `docker version`; `docker buildx version`; confirm platform; inspect local base/Caddy provenance and current official tags/digests.  
**Commands:** build `miru-cloud:<BUILD_ID>` for `linux/amd64` with no secret build args; pull an official Caddy image at version 2.10.0 or newer by digest (required for the standard `request_body` directive); tag it `miru-caddy:<CADDY_DIGEST12>`; inspect image OS/architecture/history/config; `docker image save` both images; compress; calculate SHA-256 and byte size; copy production configs and manifest into the release bundle.  
**Mutations:** local Docker cache/images and release bundle only; no push.  
**Verification:** linux/amd64; non-root Miru UID 10001; no secret-like Config.Env/history; excluded trees absent; tar hash recorded twice independently.  
**PASS Criteria:** exact image IDs/digests, source manifest, tar SHA-256, sizes and scan result recorded.  
**FAIL Criteria:** build needs Docker Hub from server; secret found; wrong architecture; mutable `latest` is the only recorded identity.  
**Rollback:** retain or remove only newly built local tags/bundle; do not prune Docker globally.  
**SSH Risk:** none.  
**Secret Risk:** build args are never a secret channel; inspect provenance for accidental build-arg disclosure.  
**User Action Required:** none unless local Docker network cannot retrieve official bases.  
**STOP Conditions:** official image digest cannot be established or a random mirror is proposed.

### P4-R3 — Create host release boundary

**Objective:** create a versioned release without touching data or enabling service.  
**Preconditions:** P4-R2 PASS; Phase 3B host unchanged.  
**Read-only Checks:** resolve `/opt/miru/app` and target release path; confirm target does not exist; `df -h`; `docker system df`; `ss -lntup`; `ufw status verbose`.  
**Commands:** user-approved `sudo install -d -o ubuntu -g ubuntu -m 0750 /opt/miru/app/releases/<BUILD_ID>` and subdirectories `artifacts`, `config`, `evidence`; create no `current` symlink yet.  
**Mutations:** those exact new directories only.  
**Verification:** `readlink -f` remains under `/opt/miru/app/releases`; stat owner/mode; `/opt/miru/data` remains empty.  
**PASS Criteria:** isolated empty release exists with at least 5 GB free disk.  
**FAIL Criteria:** target exists unexpectedly, path escapes `/opt/miru/app`, or disk/resource drift.  
**Rollback:** remove only the verified empty new release directory; never recursively delete a computed/unverified path.  
**SSH Risk:** first remote mutation; keep independent SSH session open.  
**Secret Risk:** none.  
**User Action Required:** approve sudo.  
**STOP Conditions:** path/owner ambiguity or active Miru container appears.

### P4-R4 — Secure transfer, verify and load

**Objective:** move the non-secret bundle and load exact images.  
**Preconditions:** P4-R3 PASS.  
**Read-only Checks:** local and remote free space; bundle hash/size.  
**Commands:** SCP bundle to the exact release `artifacts` directory; remote `sha256sum -c`; unpack only after listing archive paths; `docker load`; inspect loaded image IDs/OS/architecture and compare with local evidence; place configs mode 0640.  
**Mutations:** files in the new release and two Docker images/tags.  
**Verification:** hashes and image IDs match; no source tree, DB, secret, Windows path or WeChat artifact present.  
**PASS Criteria:** byte-identical artifact and immutable release metadata.  
**FAIL Criteria:** mismatch, unexpected archive path, load error, or tag collision with different image ID.  
**Rollback:** remove only uploaded bundle/release and the newly loaded image tags if unreferenced; no global prune.  
**SSH Risk:** SCP uses the same pinned host/key.  
**Secret Risk:** the bundle is explicitly non-secret; scan remote names and image config, not file contents that could print values.  
**User Action Required:** none.  
**STOP Conditions:** any hash mismatch.

### P4-R5 — Human secret injection gate

**Objective:** create two production credential files without exposing their values.  
**Preconditions:** P4-R4 PASS; user has the values in a personal password manager/secure source.  
**Read-only Checks:** `/opt/miru/secrets` absent or empty; no prior production credential to overwrite.  
**Commands:** user opens the server terminal, uses `sudo -s`, `umask 077`, creates `/opt/miru/secrets` mode 0700, creates each file via hidden `read -rsp` and shell redirection, unsets the variable, then sets owner `10001:10001` and mode 0400. Do not put the value after `echo`, in an argument, clipboard log, `.env`, or chat.  
**Mutations:** exactly `/opt/miru/secrets/server_token` and `deepseek_api_key`.  
**Verification:** stat name/owner/mode and non-zero byte count only; never display, hash, compare prefix/suffix, or run `docker compose config` in a way that expands them.  
**PASS Criteria:** both non-empty, correct metadata; no PushPlus/Tailscale key.  
**FAIL Criteria:** value appeared in history/output/log or permissions are broader. Rotate an exposed credential before continuing.  
**Rollback:** user securely removes newly created files only if deployment is abandoned; provider-side revoke/rotate as appropriate.  
**SSH Risk:** use the user's trusted terminal; do not lose session during hidden input.  
**Secret Risk:** CRITICAL; only the user performs this stage.  
**User Action Required:** mandatory credential entry; never send values to Codex.  
**STOP Conditions:** any request to reveal a value, inability to guarantee hidden input, or credential suspected compromised.

### P4-R6 — Fresh SQLite and storage migration gate

**Objective:** prove first startup targets a fresh production DB and schema v2 without importing Windows data.  
**Preconditions:** P4-R5 PASS; `/opt/miru/data` still belongs to 10001 and is empty.  
**Read-only Checks:** list names only; assert no `.db`, `-wal`, `-shm`, attachment, WeChat or model file; inspect image migration version.  
**Commands:** validate Compose; create a release `.release.env` containing only image refs/build ID, mode 0640; set `current` symlink atomically to this release; do not start yet.  
**Mutations:** non-secret `.release.env` and `current` symlink.  
**Verification:** resolved symlink/references match exact loaded IDs; data still empty.  
**PASS Criteria:** declared migration path `empty -> schema 2`; no legacy import.  
**FAIL Criteria:** any existing DB/data or newer unsupported schema.  
**Rollback:** restore previous symlink (if any); preserve any unexpected DB untouched and STOP.  
**SSH Risk:** symlink target must be resolved before replacement.  
**Secret Risk:** Compose config must show secret file paths only.  
**User Action Required:** approve fresh DB initialization.  
**STOP Conditions:** request to upload the Windows DB or any WeChat table/material.

### P4-R7 — First private-loopback production startup

**Objective:** start API/Caddy while still inaccessible from public and tailnet networks.  
**Preconditions:** P4-R6 PASS; Tailscale/Serve not active.  
**Read-only Checks:** 18080 free on loopback; public UFW remains SSH-only.  
**Commands:** from `current`, run `docker compose -p miru-prod --env-file .release.env -f compose.production.yaml up -d`; inspect service state/health/restart/OOM and bounded logs; curl loopback Caddy `/healthz`, `/readyz`; query schema version via a fixed in-container Python check that prints only version/integrity result.  
**Mutations:** fresh DB/WAL, attachment/log directories and two containers/network.  
**Verification:** both healthy; schema 2; WAL; ownership 10001; Caddy only `127.0.0.1:18080`; API not host-published; no provider call yet.  
**PASS Criteria:** health/readiness 200 and schema/integrity pass with zero restarts/OOMKilled.  
**FAIL Criteria:** unhealthy/restart loop, public bind, migration error, permission error, secret in logs.  
**Rollback:** `compose down` without `-v`; reset symlink; preserve `/opt/miru/data` and logs for diagnosis; never delete or overwrite DB.  
**SSH Risk:** keep the second session; Docker group is privileged.  
**Secret Risk:** do not print Config.Env/process env; scan logs for secret names/signatures without echoing matches.  
**User Action Required:** approve first startup.  
**STOP Conditions:** any public business listener or secret disclosure.

### P4-R8 — Install and interactively enroll Tailscale

**Objective:** enroll Cloud, iPhone, and Windows in one tailnet without an auth key.  
**Preconditions:** P4-R7 PASS; public SSH fallback works; user controls Tailscale admin account.  
**Read-only Checks:** official stable Ubuntu Jammy repository instructions and signing path current on execution day; package absent.  
**Commands:** add the official signed Tailscale apt repository (manual package instructions, no random script/mirror), install package, verify service/version; run `sudo tailscale up --hostname=miru-cloud` without `--auth-key`; STOP at login URL. User authenticates in browser and installs/signs in on iPhone and Windows.  
**Mutations:** official apt source/package/service and Tailscale state.  
**Verification:** three expected devices online; names contain no private identity; no subnet router, exit node, Funnel or Tailscale SSH enabled; `tailscale status`/ping work.  
**PASS Criteria:** device identities are unambiguous and only outbound NAT traversal was needed.  
**FAIL Criteria:** auth key requested, wrong tailnet/account, sensitive name, or unexpected advertised route/service.  
**Rollback:** `tailscale down`; if abandoning enrollment, user removes device then `tailscale logout`; package removal is unnecessary.  
**SSH Risk:** never force reauth or close public SSH until tailnet access is independently proven.  
**Secret Risk:** login URL is authorization material; do not paste it into chat/report.  
**User Action Required:** mandatory browser/device login and account verification.  
**STOP Conditions:** user cannot verify the tailnet or only remote access path would be cut.

### P4-R9 — Tailnet Grants, MagicDNS and HTTPS human gate

**Objective:** make access least-privilege and enable non-sensitive `.ts.net` HTTPS.  
**Preconditions:** P4-R8 PASS; existing policy exported/backed up by user.  
**Read-only Checks:** inspect current policy; absence of policy means default allow-all and is not acceptance.  
**Commands:** prepare a candidate additive Grants policy: admin owns `tag:miru-cloud`; Cloud device receives that tag; only the user's approved device identity/group may reach `tag:miru-cloud` on TCP 443; policy tests deny unrelated sources/ports. User validates/applies it in admin console. User enables MagicDNS and HTTPS after acknowledging CT name publication.  
**Mutations:** admin-console policy, tag, MagicDNS, HTTPS setting.  
**Verification:** policy tests pass; approved iPhone/Windows reach Cloud tailnet 443 when Serve is later enabled; unrelated tailnet member and all other Cloud ports are denied.  
**PASS Criteria:** explicit Grants exist; no default allow-all; randomized tailnet/machine FQDN is acceptable for public CT.  
**FAIL Criteria:** replacing unrelated policy blindly, lockout, wildcard source/destination/port, or private name in certificate.  
**Rollback:** restore saved policy; disable HTTPS only if abandoning every dependent URL; remove tag only after access recovery.  
**SSH Risk:** policy may affect tailnet SSH, never public provider SSH/security group.  
**Secret Risk:** policy contains identities but no auth key/token; avoid unnecessary personal identifiers in tracked Git.  
**User Action Required:** mandatory admin-console review/apply/HTTPS consent.  
**STOP Conditions:** existing policy cannot be safely merged or user does not accept CT publication.

### P4-R10 — Enable private HTTPS/WSS Serve ingress

**Objective:** expose loopback Caddy only through persistent Tailscale Serve.  
**Preconditions:** P4-R9 PASS; API/Caddy healthy.  
**Read-only Checks:** `tailscale serve status` empty; `tailscale funnel status` empty; loopback endpoint healthy.  
**Commands:** `sudo tailscale serve --bg http://127.0.0.1:18080`; record the returned `.ts.net` FQDN without user identity; inspect Serve status.  
**Mutations:** persistent Serve HTTPS 443 configuration and certificate provisioning.  
**Verification:** approved Windows client gets valid HTTPS `/healthz`; Funnel remains off; public listeners/UFW unchanged; direct public IP 80/443/8765/18080 fail.  
**PASS Criteria:** only tailnet HTTPS reaches Caddy and cert validates.  
**FAIL Criteria:** Funnel enabled, public 443 opens, Serve bypasses Caddy, invalid cert, or other tailnet sources reach it.  
**Rollback:** `sudo tailscale serve reset`; verify status empty and tailnet URL closes.  
**SSH Risk:** none beyond sudo; keep public SSH.  
**Secret Risk:** FQDN is not a credential but may be sensitive inventory; do not combine it with tokens in logs.  
**User Action Required:** HTTPS consent may open a browser if not completed.  
**STOP Conditions:** command proposes Funnel or public ingress.

### P4-R11 — Health, auth, routing, REST and WebSocket gate

**Objective:** distinguish liveness, readiness and real business behavior through `.ts.net`.  
**Preconditions:** P4-R10 PASS; client test script reads token interactively/secure storage, never argv.  
**Read-only Checks:** container health and logs; endpoint inventory.  
**Commands:** test `/healthz`; `/readyz`; `/api/status` with no, wrong, and correct token; authenticated conversations/memory/persona/cost/tools; assert WeChat/debug/Node paths 404 at Caddy; WS no/wrong token closes 4401; correct hello returns `hello_ok`; ping/pong; one minimal text turn streams deltas and ends; second turn proves history; inspect persistence rows/cost without printing content.  
**Mutations:** a clearly named synthetic Phase 4 conversation, minimal memory/persona/cost rows and one paid DeepSeek smoke call.  
**Verification:** no-token/wrong-token rejection for every `/api` family and WS; correct auth succeeds; only cloud tools listed; DeepSeek response and cost entry recorded; logs contain no token/key/body.  
**PASS Criteria:** health, readiness, auth, REST, streaming, WS, history, memory, persona, cost and cloud tool all pass.  
**FAIL Criteria:** HTTP/WS auth gap, later-phase route reachable, provider failure, no stream, data not persisted, or secret/content log leak.  
**Rollback:** delete only explicitly synthetic rows through authenticated APIs if safe; otherwise leave labeled evidence; stop Serve/Compose on security failure.  
**SSH Risk:** do not pass secrets to remote command line.  
**Secret Risk:** CRITICAL; client reads secure input/file. One minimal prompt controls token cost.  
**User Action Required:** supply token only to the local/iPhone secure client UI; never chat.  
**STOP Conditions:** any auth bypass or secret leakage.

### P4-R12 — iPhone 5G acceptance without Flutter source change

**Objective:** prove real mobile private HTTPS/WSS while preserving Phase 5 boundary.  
**Preconditions:** P4-R11 PASS; iPhone Tailscale connected; prior App URL/token recorded privately.  
**Read-only Checks:** phone on cellular with Wi-Fi disabled; correct tailnet device identity.  
**Commands:** user enters `.ts.net` base URL and App token in existing Miru settings, runs settings health/WS test, sends one minimal text turn, backgrounds/reopens once; do not enable voice.  
**Mutations:** App runtime settings and one small conversation only; no Flutter source/IPA change.  
**Verification:** valid certificate, WSS stream, reconnect, history visible; Windows PC may be powered off after the test client setup because Cloud does not depend on it.  
**PASS Criteria:** iPhone 5G HTTPS/WSS and streaming pass.  
**FAIL Criteria:** requires LAN, public port, Flutter source edit, Home Node, or voice provider.  
**Rollback:** restore prior App URL/token in settings; Cloud remains deployed.  
**SSH Risk:** none.  
**Secret Risk:** token only in iOS secure storage/user entry.  
**User Action Required:** mandatory phone interaction.  
**STOP Conditions:** user cannot verify cellular path or token would need to be sent through chat.

### P4-R13 — Persistence, reboot and resource/security audit

**Objective:** prove production survives container and host restarts without exposure or resource failure.  
**Preconditions:** P4-R12 PASS.  
**Read-only Checks:** capture container IDs, image IDs, DB schema/counts, disk, RAM/swap, restarts, OOM, listeners, UFW, Serve/Funnel status.  
**Commands:** restart API container, verify; restart Caddy, verify; user-authorized host reboot; reconnect with independent SSH; repeat complete checks and a read-only authenticated history query.  
**Mutations:** controlled restarts/reboot only.  
**Verification:** restart policy restores both healthy; Serve `--bg` persists; DB/history persist; no OOM; no failed unit; public ports remain closed; swap pressure bounded.  
**PASS Criteria:** all persistence and exposure checks pass after reboot.  
**FAIL Criteria:** data loss, unhealthy loop, Serve/Funnel drift, unexpected listener, OOM, or SSH loss.  
**Rollback:** reset Serve and use previous release/offline mode; use Tencent console only for access recovery; do not reinstall host.  
**SSH Risk:** HIGH; user approves reboot and confirms console recovery path first.  
**Secret Risk:** do not inspect/print runtime environment after reboot.  
**User Action Required:** approve reboot and keep console access available.  
**STOP Conditions:** no recovery channel or pre-reboot health not clean.

### P4-R14 — Minimal backup and isolated restore proof

**Objective:** create a consistent rollback snapshot without claiming Phase 10 completion.  
**Preconditions:** P4-R13 PASS; no active test turn.  
**Read-only Checks:** DB exists/schema 2/integrity; backup disk budget; `/opt/miru/backups` root-only.  
**Commands:** invoke the existing SQLite Backup API inside the API image to a temporary 10001-owned operator directory under data; copy the completed snapshot with sudo into `/opt/miru/backups/<BUILD_ID>` root:root 0600; create a manifest of schema/build/attachment names and hashes but no content/secrets; restore-copy to an isolated directory and use Python sqlite3 read-only `integrity_check`, schema and synthetic conversation lookup; enforce max seven Phase 4 snapshots only after listing exact candidates.  
**Mutations:** one DB backup, manifest and restore-drill copy; no secret backup.  
**Verification:** integrity `ok`, schema 2, expected synthetic rows readable; live DB untouched; attachment manifest matches current small fixture if any.  
**PASS Criteria:** consistent backup and isolated restore proof.  
**FAIL Criteria:** raw DB copy while live, restore over production, secret inclusion, unreadable snapshot, or unbounded retention.  
**Rollback:** quarantine failed snapshot; never overwrite live DB.  
**SSH Risk:** sudo file ownership and retention deletion require exact resolved paths.  
**Secret Risk:** explicitly exclude `/opt/miru/secrets`; manifests contain names/hashes only.  
**User Action Required:** approve deletion only when more than seven verified Phase 4 snapshot directories exist.  
**STOP Conditions:** target resolution ambiguity or integrity failure.

### P4-R15 — Documentation and final gate

**Objective:** freeze evidence, operating commands and rollback state; do not enter Phase 5.  
**Preconditions:** P4-R0 through R14 PASS.  
**Read-only Checks:** repeat Git manifest, host/container/image/schema, Tailnet/Serve/Funnel, UFW/listener, console firewall, secret metadata, disk/resource and privacy-boundary audits.  
**Commands:** write a value-free Phase 4 execution report with exact versions, image IDs/digests, tar/manifest hashes, sanitized FQDN class, PASS/FAIL matrix, deviations and rollback commands; do not record credentials or personal tailnet identities.  
**Mutations:** documentation only.  
**Verification:** another reader can reproduce deployment/rollback without any secret; every UNKNOWN resolved or explicitly NOT IN SCOPE.  
**PASS Criteria:** final matrix below is satisfied.  
**FAIL Criteria:** missing evidence, unresolved exposure, undocumented drift, or later-phase capability falsely marked PASS.  
**Rollback:** documentation has no runtime rollback; if final security gate fails, reset Serve and stop Compose while preserving data.  
**SSH Risk:** final commands are read-only.  
**Secret Risk:** scan report before saving/committing.  
**User Action Required:** review/accept Phase 4 report.  
**STOP Conditions:** any required gate not PASS. Never auto-start Phase 5.

## 5. Rollback matrix

| Failure | Immediate containment | Recovery |
| --- | --- | --- |
| API/Caddy unhealthy before Serve | Keep Serve absent | Compose down without volumes; inspect bounded logs; revert release. |
| Serve/certificate/policy failure | `tailscale serve reset` | Restore prior policy; keep loopback stack for diagnosis. |
| Auth bypass or secret leak | Reset Serve, stop API | Rotate server/provider credentials; fix config; repeat from R5/R11. |
| Migration/startup failure | Stop API; preserve DB/WAL/SHM | Quarantine exact data directory or restore validated backup; never downgrade in place. |
| Bad image/config | Switch `current` to retained prior release | Load prior verified tar if necessary; Compose up; verify schema compatibility first. |
| Host reboot failure | Tencent console + public key SSH | Restore services individually; do not reinstall/reset the server. |
| Tailscale compromise | Reset Serve; remove device in admin console | Rotate App/provider secrets, re-enroll neutral device, restore Grants. |
| Firewall drift | Do not reset UFW globally | Identify only added numbered rules and remove them; console firewall is a separate user action. |

## 6. Final Phase 4 gate

```text
Miru Cloud deployed = PASS
Production containers healthy = PASS
Production storage persistence = PASS
Production authentication = PASS
Streaming = PASS
WebSocket = PASS
History = PASS
Memory = PASS
Persona = PASS
Cost = PASS
Cloud tools = PASS

General attachment production readiness = NOT IN SCOPE (Phase 9)
Cloud STT/TTS = NOT IN SCOPE (Phase 9)
Home Node transport/RPC = NOT IN SCOPE (Phase 6+)
WeChat = NOT IN SCOPE (Phase 8)
Full scheduled/off-host backup = NOT IN SCOPE (Phase 10)

Tailscale = PASS
Caddy = PASS
Private .ts.net HTTPS/WSS from iPhone 5G = PASS
Tailscale Funnel = OFF

Public exposure conforms to design = PASS
Unexpected public port = NO
Tencent console public business rule = NO
UFW public business rule = NO
Home Node inbound public port = NO

Real Windows production DB uploaded = NO
Real WeChat DB uploaded = NO
WeChat key uploaded = NO
Raw chat uploaded = NO
WeChat media uploaded = NO

Secret leaked = NO
Secret present in Git/image/Compose/argv/log/backup = NO
SQLite rollback snapshot + isolated restore = PASS
Release/image rollback = PASS

PHASE 4 = PASSED
NEXT = Phase 5 — Flutter -> Cloud
AUTO-ENTER NEXT PHASE = NO
STOP
```

## 7. HANDOFF TO EXECUTION MODEL

1. Treat this document, the frozen design, and the Phase 3B report as controlling inputs.
2. Execute exactly one stage at a time: CHECK -> EXECUTE -> VERIFY -> PASS -> NEXT.
3. Never reinterpret a FAIL as a warning. Stop and report the smallest value-free evidence.
4. Never ask for a Secret in chat. At R5/R8/R9/R12, pause for the user.
5. Never deploy `deploy/compose.yaml` or `deploy/Caddyfile` as production files.
6. Never upload source, Windows DB, WeChat material, local models, settings.yaml, or user data.
7. Never open public 80/443/8765/18080, enable Funnel, add a mirror/proxy, or push Docker Hub.
8. Preserve all existing dirty-worktree changes and all production data. No reset, prune, or broad delete.
9. Record exact image IDs, digests and hashes; a Git commit alone does not identify this dirty build.
10. After P4-R15, STOP. Do not modify Flutter source or enter Phase 5 automatically.

## Appendix A — Exact production templates

These templates are value-free. The execution model may change only image/build identifiers,
after recording the change in the execution report. A required behavior change must STOP for
architecture review.

### A.1 `deploy/production/compose.production.yaml`

```yaml
name: miru-prod

services:
  miru-api:
    image: ${MIRU_IMAGE_REF:?set MIRU_IMAGE_REF in the non-secret release env file}
    user: "10001:10001"
    environment:
      MIRU_PROFILE: cloud
      MIRU_SERVER_CONFIG: /app/config/settings.production.yaml
      MIRU_BUILD_ID: ${MIRU_BUILD_ID:?set MIRU_BUILD_ID in the non-secret release env file}
    entrypoint: ["/bin/sh", "-ec"]
    command: |
      export MIRU_SERVER_TOKEN="$$(cat /run/secrets/server_token)"
      export MIRU_DEEPSEEK_API_KEY="$$(cat /run/secrets/deepseek_api_key)"
      exec python -m miru_server --profile cloud --host 0.0.0.0 --port 8765
    volumes:
      - type: bind
        source: /opt/miru/data
        target: /app/data
      - type: bind
        source: /opt/miru/secrets/server_token
        target: /run/secrets/server_token
        read_only: true
      - type: bind
        source: /opt/miru/secrets/deepseek_api_key
        target: /run/secrets/deepseek_api_key
        read_only: true
      - type: bind
        source: ./settings.production.yaml
        target: /app/config/settings.production.yaml
        read_only: true
    expose:
      - "8765"
    networks: [miru-prod-network]
    restart: unless-stopped
    read_only: true
    tmpfs:
      - /tmp:size=64m,mode=1777
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    mem_limit: 640m
    memswap_limit: 768m
    cpus: 1.0
    pids_limit: 128
    logging:
      driver: json-file
      options:
        max-size: 10m
        max-file: "3"
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - >-
          import urllib.request;
          urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=2)
      interval: 10s
      timeout: 5s
      retries: 6
      start_period: 15s

  caddy:
    image: ${CADDY_IMAGE_REF:?set CADDY_IMAGE_REF in the non-secret release env file}
    depends_on:
      miru-api:
        condition: service_healthy
    volumes:
      - type: bind
        source: ./Caddyfile.production
        target: /etc/caddy/Caddyfile
        read_only: true
    networks: [miru-prod-network]
    ports:
      - "127.0.0.1:18080:8080"
    restart: unless-stopped
    read_only: true
    tmpfs:
      - /config:size=8m,mode=0700
      - /data:size=8m,mode=0700
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    mem_limit: 96m
    memswap_limit: 128m
    cpus: 0.2
    pids_limit: 64
    logging:
      driver: json-file
      options:
        max-size: 10m
        max-file: "3"
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "-", "http://127.0.0.1:8080/healthz"]
      interval: 10s
      timeout: 5s
      retries: 6
      start_period: 10s

networks:
  miru-prod-network:
    name: miru-prod-network
```

The double dollar signs are mandatory: Compose must pass the literal command substitution into
the container. If rendered Compose includes a secret value, FAIL. The Caddy container is not
given a `user` override in Phase 4 because the exact imported official image must first pass the
read-only/tmpfs/cap-drop runtime gate; do not invent an untested UID during execution.

### A.2 `deploy/production/settings.production.yaml`

```yaml
profile: cloud

server:
  host: 0.0.0.0
  port: 8765
  token: "${MIRU_SERVER_TOKEN}"
  advertise_lan: false
  cors_origins: []

llm:
  base_url: https://api.deepseek.com
  api_key: "${MIRU_DEEPSEEK_API_KEY}"
  model: deepseek-v4-flash
  vision_model: deepseek-v4-flash
  thinking: false
  temperature: 0.7
  max_tokens: 32768
  short_max_tokens: 2048
  timeout_s: 90
  max_tool_rounds: 6

stt:
  engine: none

tts:
  provider: none

memory:
  auto_extract: true
  history_max_chars: 16000
  episodes_max_in_prompt: 5
  summarize_at_rounds: 20

persona:
  default: miru
  dir: ./config/persona

tools:
  enabled:
    - get_current_time
    - memory_set
    - memory_get
    - memory_list
    - memory_delete
    - memory_search
    - api_cost_report
    - api_budget_set

db:
  path: ./data/miru_server.db

backup:
  enabled: false
  dir: ./data/backups
  retention_days: 7

attachments:
  dir: ./data/attachments
  max_file_mb: 10
  max_images_per_turn: 4
  max_preview_pages: 4
  max_extracted_chars_per_turn: 20000
```

The execution-day DeepSeek official model list is a gate. If `deepseek-v4-flash` is no longer a
valid Chat Completions model, STOP and update the plan; do not guess a replacement. Vision and
general attachment readiness remain Phase 9 even though the valid text model is repeated in the
required configuration field.

### A.3 `deploy/production/Caddyfile.production`

```caddyfile
{
    auto_https off
}

:8080 {
    @later_phase_paths path /api/wechat/* /api/debug/* /ws/node*
    respond @later_phase_paths 404

    request_body {
        max_size 12MB
    }

    request_header -Tailscale-User-Login
    request_header -Tailscale-User-Name
    request_header -Tailscale-User-Profile-Pic
    request_header -Tailscale-App-Capabilities

    reverse_proxy miru-api:8765 {
        flush_interval -1
    }
}
```

Run `caddy validate` using the exact imported Caddy image before startup. A directive unsupported
by that pinned version is a FAIL, not permission to silently remove the body limit or header
clearing. Caddy handles WebSocket upgrades automatically.

### A.4 Release environment file (non-secret)

```dotenv
MIRU_BUILD_ID=p4-YYYYMMDD-HHMM-HEAD-MANIFEST8
MIRU_IMAGE_REF=miru-cloud:p4-YYYYMMDD-HHMM-HEAD-MANIFEST8
CADDY_IMAGE_REF=miru-caddy:CADDYDIGEST12
```

This file contains identifiers only and may be mode 0640. It must never contain an API key,
server token, Tailnet auth key, password, personal login URL, or provider credential.

## 8. Official references checked for this plan

- Tencent Cloud: [ICP filing scenarios](https://cloud.tencent.com/document/product/243/18910),
  [filing cloud resources](https://cloud.tencent.com/document/product/243/18908/),
  [Lighthouse regions/network](https://cloud.tencent.com/document/product/1207/50103/),
  [Lighthouse firewall](https://cloud.tencent.com/document/product/1207/89060)
- Tailscale: [Linux install](https://tailscale.com/docs/install/linux),
  [MagicDNS](https://tailscale.com/docs/features/magicdns),
  [HTTPS certificates](https://tailscale.com/docs/how-to/set-up-https-certificates),
  [Serve](https://tailscale.com/docs/features/tailscale-serve),
  [Serve CLI/reset/persistence](https://tailscale.com/docs/reference/tailscale-cli/serve),
  [Grants](https://tailscale.com/docs/features/access-control/grants),
  [auth keys](https://tailscale.com/docs/features/access-control/auth-keys),
  [key expiry](https://tailscale.com/docs/features/access-control/key-expiry),
  [remove a device](https://tailscale.com/kb/1260/device-remove)
- Caddy: [reverse_proxy and WebSocket behavior](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy),
  [request body limit (standard in v2.10.0+)](https://caddyserver.com/docs/caddyfile/directives/request_body),
  [access-log credential redaction](https://caddyserver.com/docs/caddyfile/directives/log)
- Docker: [image save](https://docs.docker.com/reference/cli/docker/image/save/)
- DeepSeek: [current model/pricing page](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/),
  [Chat Completions API](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/)
