# Ledger upload and app resume repair — 2026-10-21

Cashew 420 compresses full ledger uploads when the server advertises gzip support. This reduces repeated full-ledger transfer cost and increases the upload deadline from 25 to 90 seconds. It retains local data, existing pairing, automatic retries, and plain JSON compatibility with older servers. No dependency or database schema changes are included.

Miru 0.3.6 (9) keeps the current conversation and scroll position when returning from the background. A cold launch still opens a new conversation. The bootstrap retains one controller across widget rebuilds. The ledger view checks immediately on resume and every three seconds while visible.

The server validates compressed and decoded size limits, the original JSON checksum, and snapshot consistency before atomically publishing. Incomplete or corrupt uploads keep the previous ledger. The deployment changes only the finance API module and has a verified backup and rollback image.

Both iOS builds succeeded. Downloaded IPA files passed ZIP integrity and bundle/version checks.

## Downloads

- Miru 0.3.6 (9), build 73: https://codemagic.io/app/6a7d2b2285432d3d8f060eea/build/6ad8454c064e933257c84d88
- Cashew 5.4.3 (420), build 24: https://codemagic.io/app/6a106336e948beff964378b5/build/6ad84573064e933257c84eb0

Use the existing installation/container to preserve the ledger and pairing. After updating Cashew, open it and allow pending records to upload automatically. Check its success state, then verify the latest records and last-sync time in Miru. No new test transaction or repeat pairing is needed. Ordinary app backgrounding should retain the conversation; fully terminating and restarting the process starts a new one.

## Validation

- Miru: 19 Flutter tests pass, including background/resume scroll retention and cold-launch behavior.
- Cashew: 5 sync tests and protocol checks pass, including gzip/checksum roundtrip, a slow HTTP response, older-server compatibility, and automatic recovery.
- Server: 21 ledger tests pass, including bounded decompression, invalid uploads, idempotence, and preservation of the previous snapshot.
- Static analysis: no new errors. Cashew retains its existing warning/info baseline.

Successful builds and automated tests do not establish real-device synchronization. Phone installation and confirmation that new records arrive remain separate acceptance steps.
