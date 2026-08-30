# Miru Phase 4 Production Execution Report

Recorded: 2026-08-30T17:07:55+08:00  
Result: **PHASE 4 PASSED**  
Next phase: Phase 5 — Flutter -> Cloud  
Automatic Phase 5 entry: **NO**

## 1. Scope and source identity

- Production release: `p4-20260829-1430-194b844-b9be8488`
- Git branch: `master`
- Git HEAD: `194b8442608b3cc516d0a3ddf8118a0695cc0f44`
- The source worktree was dirty before execution and was preserved without reset, prune or unrelated cleanup.
- Production was deployed from the recorded value-free release manifest rather than from an assumed clean commit.
- Sanitized service class: `https://<neutral-server>.<tailnet>.ts.net` over private Tailscale HTTPS/WSS.
- No public application domain, Funnel or public business listener was introduced.

## 2. Runtime inventory

| Component | Final value |
| --- | --- |
| Host runtime | Tencent Lighthouse, Ubuntu Server 22.04 LTS 64-bit |
| Docker | 29.7.2, build a7dcaa6 |
| Tailscale | 1.102.3 |
| Python in API image | 3.12.14 |
| Miru server | 0.1.0 |
| Caddy | 2.11.4 |
| API image ID | `sha256:90a1733e760b270a0afa70ed48bb13e366010483f7360e3e156c2044f44139ad` |
| Caddy image ID | `sha256:e2c8984e916372c4ca49b272d3c3bd3455214a41e8a8b19acb3b8c49939b3159` |
| API container | running, healthy, OOM false |
| Caddy container | running, healthy, OOM false |
| SQLite schema | 2 |
| SQLite integrity | `ok` |

Both containers recovered automatically after independent container restarts and an authorized host reboot. The container IDs and image IDs remained unchanged after reboot.

## 3. Artifact and configuration hashes

| Artifact | SHA-256 |
| --- | --- |
| `deploy/production/compose.production.yaml` | `4d3d0de364480d53e70e9fbea455284aff99f9eb0ef8112e23a8ed310d0355ad` |
| `deploy/production/settings.production.yaml` | `bbd935d44dc6b3a4a3f9e061a2ff6a85e46946cb8d7f6e9d65cf0850abe421b4` |
| `deploy/production/Caddyfile.production` | `05fc5356eae11e7b0431b85dfd86f8489092203629ed63bfb888f059dfbefe2d` |
| Tailscale production policy candidate | `73a3c3d81386844f0a66cd4ebca894e3d64ae4685b84f0802f4e09ebfcf15251` |
| Release environment file | `be198a29d484ecdb384a0eccf6d4c586d47603f93dfb1f20a61f1e33661d52fe` |
| Reused Miru API image archive | `6cb04b84dc69a04ecbb3244273efff59a68eb035db5bd498cfd7c856e45ef6ba` |
| Derived no-cap Caddy tar | `e335f1846e3b40c93c9f538567f534761a5c7b01388023db9401c910d6db9647` |
| Derived no-cap Caddy gzip tar | `41f7e5fb1998426bc927a5e8af9094b45f24c7b7442a64eafe6d1ed78bc822b3` |
| Reused-image manifest | `5b7abb9a430bf282f95756a6f69f9871a1189ecae12f41ad0cc12d14c7155813` |

The deployed configuration hashes match the local production templates.

## 4. Network and access-control result

- Server identity is a neutral tagged non-human Tailscale device.
- Production Grant is Owner-authenticated devices -> production server tag -> TCP 443 only.
- Default tailnet allow-all Grant was removed.
- Tailscale SSH policy is empty and Tailscale SSH is disabled on the server.
- MagicDNS and Tailscale HTTPS are enabled.
- Tailscale Serve proxies HTTPS 443 to Caddy at loopback `127.0.0.1:18080`.
- Funnel is disabled; Serve reports tailnet-only.
- API port 8765 is private to the Compose network.
- Caddy host binding is loopback-only on 18080.
- Public business listeners on 80/443/8765/18080: 0.
- UFW is active and publicly allows only SSH TCP 22 for IPv4 and IPv6.
- Tencent Lighthouse firewall now contains only SSH TCP 22 and ICMP Ping rules.
- The discovered all-IPv4 TCP 80 allow rule was deleted after explicit user confirmation.
- Tencent public business rules for 80/443/8765/18080: none.
- Independent direct public probes to 80/443/8765/18080 all timed out.
- Tailnet HTTPS `healthz` and `readyz` returned 200 after the firewall change.

## 5. Production behavior gate

| Gate | Result |
| --- | --- |
| Miru Cloud deployed | PASS |
| Production containers healthy | PASS |
| Production storage persistence | PASS |
| Production authentication | PASS |
| Streaming | PASS |
| WebSocket hello and ping/pong | PASS |
| WS no-token/wrong-token close 4401 | PASS |
| Conversation history | PASS |
| Memory | PASS |
| Persona | PASS |
| Cost ledger/report | PASS |
| Cloud-only tools | PASS |
| Later-phase routes blocked at Caddy | PASS |
| iPhone 5G private HTTPS/WSS | PASS |
| iPhone background/reopen history | PASS |
| API container restart | PASS |
| Caddy container restart | PASS |
| Host reboot persistence | PASS |
| SQLite Backup API snapshot | PASS |
| Isolated read-only restore | PASS |

The P4-R11 client verified every REST family with no and wrong token, authenticated status, eight cloud tools, Persona, cost, memory, two minimal streamed turns and four persisted messages. Production logs contained no token, key or prompt-body matches.

The user then completed the mandatory iPhone test over cellular: REST + WebSocket connection success, a minimal streamed reply, background/reopen, and retained history.

## 6. Data and secret boundary

- Production database contains only two Phase 4 acceptance conversations and six acceptance messages.
- Attachment rows: 0.
- WeChat contact, message, sync and voice-transcript rows: 0.
- Real Windows production DB uploaded: NO.
- Real WeChat DB uploaded: NO.
- WeChat key uploaded: NO.
- Raw personal chat uploaded: NO.
- WeChat media uploaded: NO.
- Server token file: UID/GID 10001:10001, mode 0400, read-only mount.
- Provider key file: UID/GID 10001:10001, mode 0400, read-only mount.
- Git-visible files scanned against the real secret bytes: 2,914; matches: 0.
- Release files, backups, Docker inspect/log output, process argv and both image streams were scanned against the real secret bytes; matches in every category: 0.
- Secret present in Git/image/Compose metadata/argv/log/backup: NO.

## 7. Persistence, resources and backup

- Host reboot completed with independent SSH recovery.
- Failed systemd units after reboot: 0.
- Kernel OOM events: 0.
- Root filesystem remained about 19% used with approximately 39 GiB available.
- Memory and 2 GiB swap remained within budget.
- SQLite `integrity_check` was `ok` before and after restarts, reboot and backup.
- Backup path: `/opt/miru/backups/p4-20260829-1430-194b844-b9be8488/`.
- Backup file is root:root mode 0600, 180224 bytes.
- Backup SHA-256: `3e0da291cbfcf955870a51d8754551cf183bdc9dd65877ac4b6a417b19b77091`.
- Isolated restore-copy SHA-256 matched the backup.
- Restored schema was 2; expected acceptance conversation and messages were readable.
- Phase 4 snapshot count: 1 of maximum 7; no retention deletion was needed.
- The temporary Backup API work copy was removed after the root-only snapshot and isolated restore copy were verified.

## 8. Deviations and resolutions

1. The Tailscale policy test engine rejected `autogroup:owner` as a concrete test source even though it is valid in a Grant. The live Grant retained `autogroup:owner`; the negative test uses the tagged non-user source, and positive Owner access was verified at runtime from Windows and iPhone.
2. Stock Caddy required a low-port file capability that conflicted with `cap_drop: ALL` and `no-new-privileges`. A derived Caddy image removed the unneeded capability while preserving read-only rootfs, all capability drops, loopback-only publishing and the original Caddy binary.
3. The Tencent Lighthouse firewall still had a default public HTTP 80 rule. It was discovered during the final console audit and removed after explicit user confirmation; final rules and direct probes were reverified.
4. Tencent console SPA reads timed out intermittently. Every potentially mutating action was resolved through fresh page state and authoritative post-change rule inspection; no blind retry was performed.

No unresolved deployment or security UNKNOWN remains.

## 9. Rollback and containment

Immediate security containment:

```sh
sudo tailscale serve reset
cd /opt/miru/app/current/config
sudo docker compose --env-file ../.release.env -f compose.production.yaml down
```

Do not add `-v`; production data must remain intact.

Verified release rollback target recorded by P4-R7:

```sh
sudo ln -sfn /opt/miru/app/releases/p4-20260828-2053-194b844-1446158b /opt/miru/app/current
cd /opt/miru/app/current/config
sudo docker compose --env-file ../.release.env -f compose.production.yaml up -d
```

Before switching release, verify schema compatibility and keep the current root-only Backup API snapshot. For host-access failure, use the Tencent console and public-key SSH; do not reinstall or reset the server.

## 10. Explicitly not in scope

- General attachment production readiness: Phase 9.
- Cloud STT/TTS and voice acceptance: Phase 9.
- Home Node transport/RPC: Phase 6+.
- WeChat: Phase 8.
- Full scheduled/off-host backup and long retention: Phase 10.
- Flutter source or IPA modification: Phase 5.

## 11. Final gate

```text
Tailscale = PASS
Caddy = PASS
Private .ts.net HTTPS/WSS from iPhone 5G = PASS
Tailscale Funnel = OFF

Public exposure conforms to design = PASS
Unexpected public port = NO
Tencent console public business rule = NO
UFW public business rule = NO
Home Node inbound public port = NO

Secret leaked = NO
Secret present in Git/image/Compose metadata/argv/log/backup = NO
SQLite rollback snapshot + isolated restore = PASS
Release/image rollback = PASS

PHASE 4 = PASSED
NEXT = Phase 5 — Flutter -> Cloud
AUTO-ENTER NEXT PHASE = NO
STOP
```
