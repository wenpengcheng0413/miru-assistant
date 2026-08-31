# Phase 8 — WeChat read-only execution report

Status: **SLICE 1 AUTOMATED PASS — PHYSICAL POSITIVE GATE PENDING**
Updated: 2026-08-31 11:16 CST

The minimum Cloud-to-Node WeChat path is active in production. This first
slice supports only a request-scoped, read-only keyword search against one
exactly named one-to-one contact. It does not upload the raw database, keys,
media, or a persistent chat index.

## Completed

- Added a Windows-only adapter that imports the existing Daily Report offline
  reader only when a WeChat job is invoked.
- Disabled the legacy reader's default Loguru sink before import after a local
  diagnostic showed that it otherwise prints the detected account path. The
  sanitized rerun produced zero unexpected log lines.
- Confirmed the current Windows user can locate the account and read 12,750
  contact rows, all six message shards, and 21 local database keys. No contact
  name or message content was printed during diagnostics.
- Added the fixed `wechat_search_messages` Node capability and Cloud proxy.
  It requires an exact contact and keyword, defaults to 30 days, caps the
  window at 90 days, caps results at 20, and caps each returned content field
  at 300 characters.
- Limited the first slice to one-to-one contacts. Fuzzy matches, groups, media,
  recent-message export, voice transcription, and image analysis remain
  disabled.
- Results replace private sender identifiers with `self` or `contact`, omit
  database/table/source paths, and collapse XML/media payloads to safe labels.
- The Cloud dynamically exposes the tool only when the authenticated node is
  online and both sides accept the explicit capability.
- Full regression passed `112 passed, 1 skipped`; the skip is the sandbox-only
  DPAPI test already passed in the real Windows profile.
- Deployed `p8-20260831-0911-96620b7-20b3f8ae`, then detected that the status
  layer recognized only `wechat.*` names. Release
  `p8r1-20260831-0916-fca4b1a-b19a035e` corrected underscore-form tool names.
- Production now reports Cloud ready, Home Node online, and WeChat available.
- A real synthetic Tailnet/LLM call reached the Windows proxy with a guaranteed
  nonexistent contact and failed safely. The synthetic conversation was
  deleted. Cloud and node log scans found no sensitive path, account, key, or
  token markers.

## Mandatory gate remaining

From the physical iPhone, run one search using a real, exactly named contact
and a keyword known to appear in the selected time window. The user does not
need to disclose the contact or keyword in deployment evidence.

After this positive gate, Phase 8 can extend the same boundary to a bounded
contact lookup, recent messages, statistics, and optionally the explicitly
enabled scheme-B summary synchronization. Media and voice remain outside this
slice.

## Rollback

- Active release: `p8r1-20260831-0916-fca4b1a-b19a035e`.
- Immediate previous release: `p8-20260831-0911-96620b7-20b3f8ae`.
- Last fully accepted release: `p7-20260831-0849-fe30d3c-f539332e`.
- Both Phase 8 activation backups remain retained and integrity checked.

Evidence is archived under
`docs/evidence/phase8/p8r1-20260831-0916-fca4b1a-b19a035e`.
