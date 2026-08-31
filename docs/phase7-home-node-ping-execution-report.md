# Phase 7 — `home_node_ping` execution report

Status: **AUTOMATED PASS — PHYSICAL APP GATE PENDING**
Updated: 2026-08-31 08:58 CST

The first Cloud-to-Windows RPC is implemented and active in production. It is
a fixed, read-only liveness probe and cannot execute commands or read local
files, WeChat data, or media.

## Completed

- Added a bounded Cloud RPC manager with at most two in-flight read-only jobs,
  stable job IDs, a send lock, explicit structured failures, timeout-driven
  cancellation, disconnect failure, and late-result rejection.
- Extended `/ws/node` to route `job.request`, `job.result`, and cancellation
  acknowledgement frames while preserving protocol v1 identity and heartbeat.
- Added Windows `home_node_ping` execution returning only node ID, protocol
  version, `ok` state, and UTC node time.
- Upgraded the DPAPI-backed node's local Journal to retain at most 100 bounded
  results, replaying an identical result for duplicate job IDs after reconnect.
- Added dynamic Cloud tool schemas: `home_node_ping` is exposed to the LLM only
  while the authenticated node is online and the capability is accepted by the
  Cloud allowlist.
- The Node and Cloud production allowlists contain only `home_node_ping`; no
  arbitrary shell, local-file, or WeChat capability was added.
- Targeted tests passed `6/6`; the complete server suite passed
  `105 passed, 1 skipped`. The skip is sandbox-only DPAPI and the real Windows
  profile DPAPI test has passed.
- Activated production release `p7-20260831-0849-fe30d3c-f539332e` after an
  integrity-checked database backup. API and Caddy are healthy, SQLite
  integrity is `ok`, and startup logs contain none of the three production
  secret values.
- A real Tailnet HTTPS/WSS synthetic conversation made the production LLM call
  `home_node_ping`; the physical Windows node returned success and the test
  conversation was deleted.
- The same real RPC passed again after a Cloud API restart and after a Windows
  Home Node task restart.

## Mandatory gate remaining

On the physical iPhone, ask Miru to check the Home Node using
`home_node_ping`. Confirm it reports that the node is online and responding.

## Rollback

- Active release: `p7-20260831-0849-fe30d3c-f539332e`.
- Rollback release: `p6-20260831-0745-2afc75a-03ae6b12`.
- Pre-activation database backup remains retained and verified.

Evidence is archived under
`docs/evidence/phase7/p7-20260831-0849-fe30d3c-f539332e`.
