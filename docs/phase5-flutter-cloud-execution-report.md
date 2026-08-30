# Phase 5 — Flutter to Cloud execution report

Status: **PASS**
Completed: 2026-08-31 07:28 CST

The canonical iPhone, Cloud restart, PC-off, and restored-memory continuity
gates are complete.

## Completed

- Added explicit `development`, `tailnet`, and `public` deployment profiles.
- Production profiles require HTTPS/WSS and do not run Bonjour discovery.
- The production endpoint is injected with `--dart-define`; the App Token is
  not a build define and remains in iOS secure storage.
- Added a persistent installation device ID and versioned Cloud/Home Node
  status models.
- The app consumes the authenticated REST status and the post-handshake
  WebSocket `system_status` event, displaying Cloud and Home Node independently.
- Preserved reconnect, background turn recovery, history, attachment, and
  streaming behavior.
- Deployed server release `p5-20260830-1747-194b844-2a26ad6c` atomically. The
  first activation correctly rolled back after a configuration ownership
  preflight failure; ownership was corrected and the second activation passed.
- Verified real private HTTPS, WSS authentication, status, ping/pong, streaming
  chat, and history persistence through Tailscale.
- Regressions passed: server `92 passed`; Flutter `analyze` reported no issues;
  Flutter tests `7 passed`.
- Rechecked the frozen Phase 4 boundary: Funnel off, no public business ports,
  authentication fail-closed, healthy containers, valid database, and no
  credential bytes in the changed source or inspected logs.
- Codemagic build 58 passed every macOS build step and produced the unsigned
  `Miru.ipa` for version `0.3.0+3`.
- Downloaded artifact SHA-256:
  `8805CCBEE0FDDDC52B35F1DE4556926EA5B4A36A8FF8E5EEC230105CB72893F0`.
- The IPA ZIP integrity, bundle identifier/version, executable presence,
  required user-facing permission descriptions, HTTPS endpoint injection, and
  forbidden credential-marker checks passed.
- The active application `Info.plist` contains no local-network permission,
  Bonjour declaration, arbitrary-load allowance, or ATS exception. A raw
  `NSAllowsArbitraryLoads` string exists only inside the stock Flutter runtime
  binary and is not an active application policy.
- Physical iPhone initial acceptance passed on 5G: installation, correct and
  incorrect Token behavior, chat, and background/reopen persistence.
- A controlled production container restart completed. Both containers became
  healthy; `/healthz` and `/readyz` returned 200; SQLite remained schema 2 with
  integrity `ok`.
- A real Windows Tailnet client verified the post-restart boundary: the Cloud
  peer was online, unauthenticated HTTPS returned 401, authenticated HTTPS
  returned 200, and Cloud state was `ready`.
- Physical iPhone post-restart acceptance passed: the pre-restart conversation
  remained available and a new message streamed successfully.
- Physical PC-off Cloud-only acceptance passed on the iPhone.
- A post-acceptance data-continuity review found that the legacy Windows
  long-term-memory rows were not included when the fresh Cloud database was
  initialized. The local database and three consecutive daily backups remain
  healthy and contain 90 memory rows (19 profile, 8 preferences, 20 projects,
  and 43 knowledge). Cloud currently contains two profile rows.
- Privacy-preserving hash comparison found 89 directly additive legacy rows,
  one differing profile-key collision, and one Cloud-only profile row. Both
  conflicting values were auto-generated; the Cloud value is newer and will
  remain authoritative. No memory contents were printed.
- After explicit user authorization, a table-whitelisted memory-only SQLite
  package was generated. It contained exactly the five memory tables and 90
  rows; it contained no conversations, messages, attachments, or cost tables.
- A pre-merge production SQLite backup passed integrity verification. The
  memory import then committed as one transaction: 89 rows were inserted, the
  newer Cloud conflict value and Cloud-only value were preserved, and both
  pre-existing Cloud profile rows were byte-hash invariant.
- Post-merge counts are profile 20, preferences 8, projects 20, knowledge 43,
  and episodes 0. SQLite integrity, API health/readiness, and real Tailnet HTTPS
  reads passed. Local and remote temporary packages were removed; the secured
  pre-merge production backup was retained for rollback.

## Build boundary

Windows can analyze and test this source but cannot produce an iOS artifact:
the final bundle requires Xcode and `xcrun`. `codemagic.yaml` therefore performs
the release compilation on its macOS worker and injects only the non-secret
Tailnet HTTPS endpoint. The App Token is entered on-device after installation.

## Mandatory gates remaining

None. The user confirmed the restored legacy long-term memories are visible on
the physical iPhone. Phase 6 may proceed.

## Rollback

- Mobile: reinstall the previously accepted build and select the development
  profile only for a local rollback.
- Cloud: production rollback release is
  `p4-20260829-1430-194b844-b9be8488`; production data is not deleted.

Evidence is archived under
`docs/evidence/phase5/p5-20260830-1747-194b844-2a26ad6c`.
