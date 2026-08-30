# Miru Assistant Phase 4 — CR-R3 Attempt-02 Failure Review and Driver Hardening

**Review date:** 2026-08-29  
**Role:** Sol review/planning model  
**Execution boundary:** Static local review only. This review did not contact Production, run a
Docker probe, switch `current`, start Compose, access Secret/data paths, or modify the immutable
release.

This review is subordinate to, and must be read after:

1. `docs/phase4-final-execution-runbook.md`
2. `docs/phase4-p4-r7-remediation-runbook.md`
3. `docs/phase4-p4-r7-config-readability-remediation-runbook.md`

## 1. Exact attempt-02 failure

The exact PowerShell command retained in the prior Codex task used a literal single-quoted
PowerShell here-string for the remote Bash program. Extracting that here-string without executing
it gives this line 11:

```sh
MIRU_INV_TMP="$E/10-miru-invocation.txt.tmp.$$
```

The double quote immediately before `$E` is never closed. Bash therefore reached end-of-input
while still seeking `"`, reporting the diagnostic against line 85/EOF and exiting `2` before it
could execute any command in the program.

The defect is an authored outer-Bash assignment typo. It was not introduced by PowerShell
interpolation: `@' ... '@` is literal. It was not introduced by the `.Replace("`r`n","`n")`
normalization, which changes only line endings. OpenSSH forwarded the malformed program; it did not
create the quote. The `PROBE_EOF` heredoc, embedded assertion text, command substitutions and Docker
argv are lexically after the unclosed quote and are not the source of this parse failure.

Consequences:

- Miru Docker invocation reached: **NO**
- Caddy Docker invocation reached: **NO**
- Actual readability failure proven: **NO**
- Driver failure proven: **YES**
- Attempt-02 evidence plus the retained exact command/task transcript is sufficient for failure
  classification and new-attempt review, but not for a readability result.

## 2. Driver decision

`STANDALONE HASHED DRIVER REQUIRED`

Two attempts failed in the outer driver before either probe. A large inline
PowerShell-to-OpenSSH-to-Bash program is no longer an acceptable CR-R3 execution boundary.

The frozen local attempt-03 driver is:

```text
docs/evidence/phase4/p4-20260829-0609-194b844-17b3db59/p4-cr-r3-attempt-03-driver.sh
```

Its local SHA-256 sidecar is adjacent. At this review revision the driver SHA-256 is:

```text
f53da7a38dbb49dcae6ba76c930078f75476d05eb40d0f3b4c1f3767cdb1c25b
```

The frozen remote attempt directory and script path are:

```text
/opt/miru/app/releases/p4-20260829-0609-194b844-17b3db59/evidence/p4-cr-r3-attempt-03/
/opt/miru/app/releases/p4-20260829-0609-194b844-17b3db59/evidence/p4-cr-r3-attempt-03/p4-cr-r3-attempt-03-driver.sh
```

### 2.1 Local generation and validation contract

- Generate the script once as UTF-8 without BOM, LF-only, with a final LF and no NUL.
- The script and sidecar are attempt-specific, value-free artifacts. They contain approved paths,
  refs, IDs and hashes, but no config contents or credential values.
- Recompute the local SHA-256 immediately before transfer. It must equal the reviewed sidecar.
- Require exactly one occurrence of each full approved image ID and the exact `NEW_RELEASE` constant.
- Fail a non-printing credential-signature scan.
- Fail if the executable script contains a Compose-up command, symlink/rename activation command,
  ownership/mode mutation, Secret/data path, port publication, Production-network creation/use,
  image mutation, or more than the two reviewed `docker run` sites.
- A compatible local Bash parser was not available during this review: the Windows `bash.exe` is
  only the WSL shim, WSL enumeration returned `E_ACCESSDENIED`, and Git Bash, ShellCheck and Python
  Bash parsers were absent. Therefore this review does **not** claim a local `bash -n` PASS. The
  remote `bash -n` gate below is mandatory and cannot be waived.

Local byte/static inspection at review time found: UTF-8 without BOM, zero CR bytes, zero NUL bytes,
balanced per-line double quotes, matched named heredoc starts/terminators, no high-confidence
credential signature, exact release/image constants, and none of the forbidden mutations.

### 2.2 Transfer and fail-closed remote static gate

Only after separate explicit attempt-03 authorization:

1. Create only the frozen attempt-03 evidence directory; refuse if it already exists.
2. Transfer the driver and its sidecar as regular non-secret files. Do not stream the program into
   `ssh`, a shell here-string, or `bash -c`.
3. Record local and remote SHA-256 values in `00-driver-static-gate.txt`; require exact equality and
   a successful remote sidecar check.
4. Byte-check the remote file: UTF-8-compatible text, LF-only/no CR, no NUL, non-empty final LF.
5. Repeat non-printing credential-signature and forbidden-operation scans on the exact remote file.
6. Machine-verify the exact approved release, Miru ID and Caddy ID constants.
7. Run `bash -n <exact-remote-driver-path>` and record stdout, stderr and immediate exit in the
   static-gate evidence. Do not execute the driver unless the exit is `0`.
8. Independently syntax-check both embedded POSIX probe assertion strings with `/bin/sh -n` before
   Docker; the standalone driver repeats this in its precheck.

Any missing evidence or failed predicate is attempt-03 FAIL and STOP before Docker mutation.

### 2.3 Execution and evidence contract

- Execute only `bash <exact-remote-driver-path>`; capture the outer SSH/native exit independently.
- The driver has no automatic retry loop and does not use `set -e` to skip exit capture.
- It writes the invocation marker and exact value-free argv before each `docker run`.
- It runs Miru first and records stdout, stderr, the immediate Docker exit and post-check.
- Caddy is reached only if Miru's Docker exit, all assertion markers, container cleanup and network
  post-check pass.
- Both containers retain the exact F.2/F.3 user, bind, read-only, capability and no-network
  semantics. Neither probe mounts or accesses credential/runtime-storage paths, the Docker socket,
  or ports.
- The container output records start, UID, GID, supplementary GID 1001 presence, readable,
  non-writable and complete-read-to-null assertions without printing config contents.
- Preserve the driver, static gate, all stdout/stderr/exit/post-check files and final state on PASS
  or FAIL. Never rewrite attempts 01 or 02.
- After recording the independent outer exit, regenerate and verify the final attempt-03
  `SHA256SUMS`. Failure to record/seal is FAIL, not permission to rerun.
- Docker `--rm` cleanup is required; no other cleanup or repair is authorized. Preserve a failed
  attempt-03 directory byte-for-byte for review.

## 3. Release validity

```text
NEW_RELEASE INVALIDATED = NO
same NEW_BUILD_ID reusable = YES
new BUILD_ID required = NO
config/metadata repair required = NO
image rebuild required = NO
Secret rotation required = NO
```

Attempt 02 failed while Bash parsed an external validation driver. The reported post-state and
sealed evidence show no Docker invocation and no change to release bytes, metadata, image IDs,
Secrets, data, `current`, listeners, networks or containers. Attempt-specific evidence is the
intentionally appendable evidence surface and does not invalidate the immutable payload.

## 4. New-attempt gate

`CR-R3 ATTEMPT 03 ELIGIBLE = YES`

`automatic retry = forbidden`

`new separately human-authorized attempt after review = allowed`

Eligibility is conditional on using the exact standalone hashed driver and passing every static
gate before Docker. Attempt 03 is not authorized by this document.

STOP — READY FOR EXPLICIT CR-R3 ATTEMPT 03 AUTHORIZATION
