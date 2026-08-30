# Phase 5 — Flutter to Cloud execution report

Status: **IN PROGRESS**  
Updated: 2026-08-30 21:58 CST

Phase 5 is deliberately not marked PASS until the new iOS build completes the
canonical physical iPhone and PC-off acceptance gates.

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

## Build boundary

Windows can analyze and test this source but cannot produce an iOS artifact:
the final bundle requires Xcode and `xcrun`. `codemagic.yaml` therefore performs
the release compilation on its macOS worker and injects only the non-secret
Tailnet HTTPS endpoint. The App Token is entered on-device after installation.

## Mandatory gates remaining

1. Codemagic produces the unsigned `Miru.ipa` for version `0.3.0+3`.
2. The build is installed on the physical iPhone.
3. On 5G, validate correct and incorrect Token behavior, streaming, history,
   background/reopen, and recovery after a Cloud restart.
4. With the Windows PC fully powered off, validate Chat, Streaming, History,
   Memory, Persona, Cost, and Cloud Tool while Home Node is shown offline.

## Rollback

- Mobile: reinstall the previously accepted build and select the development
  profile only for a local rollback.
- Cloud: production rollback release is
  `p4-20260829-1430-194b844-b9be8488`; production data is not deleted.

Evidence is archived under
`docs/evidence/phase5/p5-20260830-1747-194b844-2a26ad6c`.
