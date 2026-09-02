# Phase 10 production activation evidence

Date: 2026-09-03 (Asia/Shanghai)

## Identity and provenance

- Git commit: `92f047fac0bab29580eff0ad296c54bb7f44166d`
- Release: `p10-20260903-0001-92f047f-51aaa8a9`
- Previous/rollback release: `p9tts-20260902-0249-51d51f0`
- Local minimal source archive SHA-256: `DC22F4E31782104206F77B49CC5FF17EC4CA2765737812B3DB665072759555C6`
- GitHub codeload archive SHA-256 observed on the server: `ee49e48b7bc34779cb49c1d5dd4983d84433bf057b8d7c3d599944ea2e4d00f9`
- Candidate image ID: `sha256:4ec9c6a4f24e926c73aae19898048a21b45973767e223c740760038be4a05880`
- Candidate image size: 113,161,441 bytes

No Secret Value, transcript, message content, attachment name, or absolute user-data path is retained in this evidence.

## Pre-activation gates

- Previous API and Caddy containers: running/healthy, zero restarts, no OOM.
- Database pre-activation snapshot: `integrity=ok`, 1,396,736 bytes.
- Snapshot SHA-256: `b143fd12d8326ffc90d0766aff3e240dd8414d36e0830bc987b834091a7b90b5`.
- Disk used: 19% before activation; available memory approximately 1,257 MB; Swap used 0 MB.
- Candidate release files: root-owned, mode 0644.
- Candidate Compose render: passed.
- Atomic `current` switch target verified.

## Post-activation gates

- API image: `miru-cloud:p10-20260903-0001-92f047f-51aaa8a9`.
- API: running/healthy, `OOMKilled=false`, restart count 0.
- Caddy: running/healthy, `OOMKilled=false`, restart count 0.
- `/healthz`: `status=ok`.
- `/readyz`: config, SQLite, and services are all true.
- Database: schema/user version 2; `PRAGMA integrity_check=ok`.
- Backup status: enabled/healthy, no error code.
- Capacity status: normal; disk used 22.1%, free 39,189 MB, process RSS 111.3 MB, memory available 1,276.6 MB, Swap used 0.5 MB.

## Backup and restore drill

- Daily/weekly snapshot verification: passed.
- Database bytes: 1,396,736.
- Attachment manifest: 16 files, 2,924,080 aggregate bytes.
- Backup integrity: `ok`; schema/user version 2.
- Restore destination was a new staging-only directory.
- Post-restore verification: `staged=true`, `integrity=ok`, `ok=true`.
- Production database was not overwritten and the restored staging copy was not promoted.

## Result

`PHASE10_PRODUCTION_ACTIVATION=PASS`

The rollback release remains available. Encrypted off-host backup, systemd scheduling, content-free alerting, and destructive fault drills remain separate follow-up work.
