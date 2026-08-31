# Phase 6 — Home Node transport execution report

Status: **AUTOMATED PASS — PHYSICAL APP GATE PENDING**
Updated: 2026-08-31 08:07 CST

The production Home Node identity, outbound transport, liveness state machine,
secure Windows credential storage, login startup task, and recovery paths are
implemented and live. The only remaining Phase 6 gate is a short visual status
check in the physical iPhone app.

## Completed

- Added the authenticated `/ws/node` protocol v1 endpoint with fixed
  `node-home` identity, bounded messages, a capability allowlist, and a
  thread-safe live registry.
- Added 20-second heartbeat handling with `online`, `stale`, and `offline`
  states. The production thresholds are 30 seconds stale and 60 seconds
  offline.
- Added a Windows outbound-only WSS client with bounded journal state,
  exponential reconnect, and no inbound listener.
- Generated a high-entropy Node Token that is independent of the App Token.
  The Cloud copy is a mode-0400 secret and the Windows copy is protected by
  DPAPI CurrentUser encryption. The plaintext token is absent from config,
  source, evidence, and logs.
- Registered `Miru Home Node` in Windows Task Scheduler for the current user's
  logon. Its guardian uses the repository virtual environment and an explicit
  server working directory; the task is running.
- Deployed production release `p6-20260831-0745-2afc75a-03ae6b12`. The first
  activation detected unreadable non-secret bind-mounted configuration and
  automatically rolled back to Phase 5. After changing only those config files
  to mode 0644, the isolated candidate and second activation passed.
- Production currently reports API and Caddy `running/healthy`, Cloud `ready`,
  Home Node `online`, protocol version 1, and no Phase 7 capabilities.
- Negative identity tests passed: bad Node Token closed with 4401, unknown
  `node_id` with 4403, and unsupported protocol with 4400.
- Real liveness testing passed: stopping the Windows task produced
  `stale/node_reconnecting`, then `offline/heartbeat_timeout`; Cloud stayed
  ready. Restarting the task restored `online`.
- Controlled restarts of the Miru Cloud containers and the Windows Tailscale
  service both recovered automatically to Home Node `online`.
- Regression results: Phase 6 targeted `7 passed, 1 skipped`; full server suite
  `99 passed, 1 skipped`. The skip is the sandbox DPAPI case, which passed in
  the real Windows user profile. Both PowerShell scripts parse cleanly.
- The Phase 4 network boundary remains frozen: private Tailscale HTTPS/WSS,
  Funnel off, no public business ports, no Windows inbound listener, and no
  new public exposure.

## Mandatory gate remaining

On the physical iPhone, confirm that the status shows Cloud Online and Home
Node Online. Then, during one controlled node pause, confirm that Home Node
changes to Offline while Cloud chat remains usable; after restart, confirm it
returns to Online. The automated API-side version of this transition has
already passed.

## Rollback

- Active production release:
  `p6-20260831-0745-2afc75a-03ae6b12`.
- Rollback release:
  `p5-20260830-1747-194b844-2a26ad6c`.
- The pre-activation database backup remains retained and verified.

Evidence is archived under
`docs/evidence/phase6/p6-20260831-0745-2afc75a-03ae6b12`.
