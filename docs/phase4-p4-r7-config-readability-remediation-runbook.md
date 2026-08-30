# Miru Assistant Phase 4 — P4-R7 Config Readability Remediation Overlay

**Planning date:** 2026-08-29  
**Document status:** FINAL NARROW REMEDIATION PLAN / NOT EXECUTED  
**Role boundary:** Sol review/planning model  
**Controlling documents, in precedence order outside this narrow defect:**

1. `docs/phase4-final-execution-runbook.md`
2. `docs/phase4-p4-r7-remediation-runbook.md`
3. This overlay, only for the post-RM-R6 runtime-file readability remediation

**Execution boundary:** Preparing this overlay did not change Production, retry RM-R6, start or
create a container, change a Secret, change data, build/save/tag an image, create a release, switch
`current`, install Tailscale, enter RM-R7, or enter P4-R8. Production inspection was read-only.

This document supersedes only the prior overlay's incorrect conclusion that there was no adjacent
runtime-readability blocker. The corrected Compose argv contract and every frozen Phase 4
architecture boundary remain authoritative.

## A. Incident Summary

### A.1 Failed corrected release

| Item | Proven value |
| --- | --- |
| Failed corrected BUILD_ID | `p4-20260829-0249-194b844-b2d6ab6f` |
| Failed corrected release | `/opt/miru/app/releases/p4-20260829-0249-194b844-b2d6ab6f` |
| Corrected Compose SHA-256 | `4d3d0de364480d53e70e9fbea455284aff99f9eb0ef8112e23a8ed310d0355ad` |
| Miru image ID | `sha256:90a1733e760b270a0afa70ed48bb13e366010483f7360e3e156c2044f44139ad` |
| Caddy image ID | `sha256:98eb57d882ccd5213d1688764db10c1ca2c58a1ca3a6717a3411ad798f7a423a` |
| Startup invocation exit | `1` |
| API terminal state | restarting; unhealthy; exit 1; restart count 13; OOMKilled false |
| Caddy state | dependency unsatisfied; process never started (a `Created` object appears in Compose evidence) |
| Database state | no DB, WAL, SHM, attachment, or other data entry created |
| Secret scan | no exact Secret or credential-signature match |
| Containment | `docker compose down` without `-v`; zero containers/network afterward |
| Restored `current` | `/opt/miru/app/releases/p4-20260828-2053-194b844-1446158b` |

The complete preserved evidence is under:

```text
/opt/miru/app/releases/p4-20260829-0249-194b844-b2d6ab6f/evidence/p4-r7-retry
```

Its evidence manifest covers 32 files. `result.txt` records FAIL, complete pre-containment capture,
no automatic retry, and restored `current`. `secret-leak-scan.txt` records both leak predicates
false. The failed release and evidence must remain byte-for-byte incident evidence.

### A.2 Original argv defect is resolved

The actual API process evidence is:

```text
Path = /bin/sh
Args = ["-ec", "<one complete multiline script>"]
```

The one script contains both Secret readability/non-empty gates and the final `exec python -m
miru_server ...`. Python ran and produced its own traceback from `miru_server/config.py`. Therefore
the original tokenized-argv defect is resolved; it is not the cause of this failure.

### A.3 Confirmed new root cause

The repeated terminal exception is:

```text
PermissionError: [Errno 13] Permission denied: '/app/config/settings.production.yaml'
```

The bind source and runtime identity were:

```text
source = <failed-corrected-release>/config/settings.production.yaml
source metadata = regular file, UID 1000, GID 1001, mode 0640
target = /app/config/settings.production.yaml, read-only bind
API runtime = effective UID 10001, effective GID 10001
Compose group_add = absent; runtime has no supplementary GID 1001
```

POSIX DAC evaluation is deterministic: UID 10001 is not owner UID 1000; GID 10001 and its
supplementary set do not match GID 1001; and the `other` read bit in `0640` is clear. The read is
therefore denied. Bind mounts preserve the source inode's UID, GID and permission bits; Docker's
root daemon resolving the host path does not grant the container process read access.

The prior pre-start evidence recorded
`euid10001_egid10001_supplementary1001`. That host-side `sudo` predicate was not representative of
the container: it retained the deployment user's supplementary GID 1001 and passed through the
file's group-read bit. The host has no passwd entry for UID 10001, and the Compose service does not
add GID 1001. That predicate must not be reused.

## B. Adjacent Runtime Readability Audit

### B.1 Runtime regular-file binds

These are every regular host file bind-mounted by the rendered two-service Compose definition.
There are no other runtime regular-file binds.

| Service | Host source | Container target | Current host UID:GID/mode | Runtime UID:GID | Supplementary groups / DAC capability | Required access | Current result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Miru API | `<release>/config/settings.production.yaml` | `/app/config/settings.production.yaml` | `1000:1001/0640` | `10001:10001` | no `group_add`; no GID 1001; all capabilities dropped | read entire file; never write | **FAIL — observed root cause** |
| Miru API | `/opt/miru/secrets/server_token` | `/run/secrets/server_token` | `10001:10001/0400` | `10001:10001` | no `group_add`; owner match | read entire non-empty file; never write | **PASS — shell advanced past this gate** |
| Miru API | `/opt/miru/secrets/deepseek_api_key` | `/run/secrets/deepseek_api_key` | `10001:10001/0400` | `10001:10001` | no `group_add`; owner match | read entire non-empty file; never write | **PASS — shell advanced past this gate** |
| Caddy | `<release>/config/Caddyfile.production` | `/etc/caddy/Caddyfile` | `1000:1001/0640` | default `0:0` | no `group_add`; no GID 1001; `cap_drop: [ALL]`, including no `CAP_DAC_OVERRIDE` | read entire file; never write | **FAIL — predictable second blocker** |

The Caddy image has no `Config.User`, so Docker defaults it to UID/GID 0:0. UID 0 without
`CAP_DAC_OVERRIDE` is still subject to these DAC bits. It is neither owner UID 1000 nor group GID
1001 and `other` has no read bit. Caddy did not expose this failure because `service_healthy` kept
its process from starting after the API failed.

The Miru image account database defines `miru:x:10001:10001` and no supplementary membership. The
Caddy image has no GID 1001. Neither Compose service declares `group_add`.

### B.2 Runtime directory bind

`/opt/miru/data` is a directory bind, not a regular-file bind, but remains a mandatory adjacent
gate:

| Source -> target | Host UID:GID/mode | Runtime | Required access | Result |
| --- | --- | --- | --- | --- |
| `/opt/miru/data` -> `/app/data` | `10001:10001/0750` | API `10001:10001` | read, write, create and traverse | **PASS; empty after containment** |

Write access is required only for this data bind. The settings, Caddyfile and both Secret binds
must be read-only at the Docker mount and non-writable by their runtime identities.

### B.3 Host-only files

The following files are consumed by host-side Docker Compose or by release verification and are
not mounted into a runtime container:

| File | Consumer | Runtime UID readability required? |
| --- | --- | --- |
| `<release>/config/compose.production.yaml` | deployment user / Docker Compose CLI | No |
| `<release>/.release.env` | deployment user / Docker Compose CLI | No |
| manifests, provenance and `artifacts/reused-images.sha256` | operator/release verification | No |
| image tar/tar.gz archives | Docker load fallback / release provenance | No |

Their inability to be read by UID 10001 is not a defect. Do not grant runtime ownership or world
readability to them merely to satisfy an inapplicable predicate.

### B.4 Audit conclusion

Fixing settings alone would reveal another predictable permission failure at Caddy startup.
Both runtime config files require correction in the next immutable release. The Secret files and
data directory are already correct and must not be changed.

## C. Selected Minimum Remediation

### C.1 Exact install contract

Use the following single strategy: **runtime owner + deployment audit group + no write bits**.
Numeric IDs are authoritative.

| Path in new release | Expected UID:GID | Mode | Purpose |
| --- | --- | --- | --- |
| release root | `0:1001` | `0750` | root-controlled immutable boundary; deployment group can traverse/read |
| `config/` | `0:1001` | `0750` | prevents deployment user from replacing config directory entries |
| `artifacts/` | `0:1001` | `0750` | root-controlled inherited artifact/provenance boundary |
| `evidence/` | `1000:1001` | `0750` | bounded operator evidence remains writable during execution |
| `.release.env` | `0:1001` | `0440` | host-only identifiers; Compose user can read, nobody can write without sudo |
| `config/compose.production.yaml` | `0:1001` | `0440` | host-only Compose definition; frozen corrected bytes |
| `config/settings.production.yaml` | `10001:1001` | `0440` | Miru owner-read plus deployment-group audit read; no write/world access |
| `config/Caddyfile.production` | `0:1001` | `0440` | Caddy owner-read plus deployment-group audit read; no write/world access |
| static manifest/provenance files | `0:1001` | `0440` | file-level read-only release identity evidence |

Runtime-generated evidence files may be `1000:1001/0640` inside `evidence/`; this exception does
not apply to release identity, config or artifacts.

Retain, without any metadata change:

```text
/opt/miru/secrets                      0:0       0700
/opt/miru/secrets/server_token         10001:10001 0400
/opt/miru/secrets/deepseek_api_key     10001:10001 0400
/opt/miru/data                         10001:10001 0750
```

### C.2 Why this is the minimum safe strategy

- It grants Miru owner-read on settings and Caddy owner-read without depending on a dropped DAC
  capability.
- GID 1001 grants the existing deployment user read-only audit/hash/Compose access to non-secret
  release material; no `sudo cat` workflow is required for routine value-free verification.
- Mode `0440` grants neither owner nor group write and grants no world access. `0644` is broader
  than required and is rejected.
- It does not add host GID 1001 to either container. `group_add: [1001]` would expand container
  access to every object carrying that host GID and would change the Compose runtime contract.
- Root-owned release/config directories prevent UID 1000 from replacing frozen files despite
  file-level mode bits. Only the intentionally appendable evidence directory remains operator-owned.
- Docker read-only binds provide a second write barrier inside each container.
- Numeric metadata and explicit `install` commands are reproducible across archive extraction and
  do not rely on Windows tar ownership behavior or the caller's `umask`.

Do not patch the files with `chmod` or `chown` inside either failed release. Install unchanged file
bytes with the contract above into a new release only.

### C.3 Exact remote install procedure

After the activation envelope is independently hash-verified, safely listed and extracted into an
approved non-secret staging directory, install rather than move its members. Substitute only the
approved derived BUILD_ID:

```sh
set -eu
NEW_BUILD_ID='<approved-derived-id>'
STAGE="/opt/miru/app/incoming/$NEW_BUILD_ID"
NEW_RELEASE="/opt/miru/app/releases/$NEW_BUILD_ID"

case "$STAGE" in /opt/miru/app/incoming/p4-*) ;; *) exit 1 ;; esac
case "$NEW_RELEASE" in /opt/miru/app/releases/p4-*) ;; *) exit 1 ;; esac
test -d "$STAGE"
test ! -e "$NEW_RELEASE"

sudo install -d -o 0 -g 1001 -m 0750 \
  "$NEW_RELEASE" "$NEW_RELEASE/config" "$NEW_RELEASE/artifacts"
sudo install -d -o 1000 -g 1001 -m 0750 "$NEW_RELEASE/evidence"

sudo install -o 0 -g 1001 -m 0440 \
  "$STAGE/.release.env" "$NEW_RELEASE/.release.env"
sudo install -o 0 -g 1001 -m 0440 \
  "$STAGE/config/compose.production.yaml" \
  "$NEW_RELEASE/config/compose.production.yaml"
sudo install -o 10001 -g 1001 -m 0440 \
  "$STAGE/config/settings.production.yaml" \
  "$NEW_RELEASE/config/settings.production.yaml"
sudo install -o 0 -g 1001 -m 0440 \
  "$STAGE/config/Caddyfile.production" \
  "$NEW_RELEASE/config/Caddyfile.production"
sudo install -o 0 -g 1001 -m 0440 \
  "$STAGE/artifacts/reused-images.sha256" \
  "$NEW_RELEASE/artifacts/reused-images.sha256"

for evidence_name in \
  p4-r1-static-validation.txt \
  p4-r2-inherited-image-provenance.txt \
  p4-config-readability-static-validation.txt \
  source-manifest-v3.sha256; do
  sudo install -o 0 -g 1001 -m 0440 \
    "$STAGE/evidence/$evidence_name" "$NEW_RELEASE/evidence/$evidence_name"
done
```

The activation allowlist must contain exactly these required members plus any separately approved,
named value-free provenance member. An absent required member or unexpected member is FAIL. Do not
delete the verified staging material automatically.

Verify without following an unapproved path:

```sh
readlink -f /opt/miru/app/releases
readlink -f "$NEW_RELEASE"
sudo stat -c '%n|%F|%u:%g|%a|%s' \
  "$NEW_RELEASE" "$NEW_RELEASE/config" "$NEW_RELEASE/artifacts" \
  "$NEW_RELEASE/evidence" "$NEW_RELEASE/.release.env" \
  "$NEW_RELEASE/config/compose.production.yaml" \
  "$NEW_RELEASE/config/settings.production.yaml" \
  "$NEW_RELEASE/config/Caddyfile.production" \
  "$NEW_RELEASE/artifacts/reused-images.sha256"
```

Machine-compare the result to C.1; visual inspection is insufficient. Rehash file bytes after
installation. `current`, containers, networks, Secrets and data remain untouched in this stage.

## D. Immutable Release Strategy

### D.1 A new release is mandatory

The failed corrected release is immutable incident evidence. Ownership and mode are release
semantics even when content bytes are unchanged. A corrected install cannot reuse
`p4-20260829-0249-194b844-b2d6ab6f`, its archive, or its remote directory.

Create manifest format version 3 and derive:

```text
manifest_input_sha256 = SHA-256(canonical UTF-8/LF manifest-v3 payload,
                                excluding generated hash and BUILD_ID result lines)
NEW_BUILD_ID = p4-<UTC-YYYYMMDD-HHMM>-194b844-<first8(manifest_input_sha256)>
```

The freeze minute is the actual new freeze minute. HEAD must remain exactly
`194b8442608b3cc516d0a3ddf8118a0695cc0f44`; otherwise STOP for a separate source release review.

### D.2 Manifest v3 inputs

Record in canonical ordinal order:

1. The complete v2 source/build-input identity and an execution-day rehash of every Miru image
   build input, branch, HEAD, filtered status, binary diff and `miru_server` tree.
2. All three controlling runbooks, including this overlay.
3. The unchanged production file bytes and hashes: Compose
   `4d3d0de364480d53e70e9fbea455284aff99f9eb0ef8112e23a8ed310d0355ad`, settings
   `bbd935d44dc6b3a4a3f9e061a2ff6a85e46946cb8d7f6e9d65cf0850abe421b4`, and Caddyfile
   `05fc5356eae11e7b0431b85dfd86f8489092203629ed63bfb888f059dfbefe2d`.
4. A canonical `install_contract` row for every path in C.1, including type, numeric UID, numeric
   GID and octal mode.
5. Exact inherited Miru/Caddy image IDs, config digest, tar/tar.gz hashes and tag mappings.
6. The v2 manifest/archive hashes and a sealed hash inventory of the failed corrected release's
   complete `p4-r7-retry` evidence.
7. Explicit exclusions: Secret values and hashes, `.release.env` generated BUILD_ID value, runtime
   data, generated manifest hash result and generated BUILD_ID result are not inputs.

### D.3 Package, image and remote strategy

- Create a new local release root, full wrapper archive, activation envelope and archive hashes.
- Include unchanged config bytes, the new identifiers-only `.release.env`, manifest v3, new static
  validation/provenance, and the exact inherited image byte artifacts/map as defined by the prior
  overlay. The wrapper archives are new because identity and install provenance changed.
- Archive owner/mode fields are evidence but not authority. The remote installer must normalize
  every path with explicit numeric `install -o -g -m`, then machine-compare `stat` output to C.1.
- Reuse the exact Miru Image ID under a new `miru-cloud:<NEW_BUILD_ID>` membership tag. A different
  image ID is FAIL.
- Reuse `miru-caddy:98eb57d882cc` and its exact Image ID.
- Do not rebuild Miru or Caddy; do not pull; do not push; do not run `docker save`.
- Reuse exact, rehashed prior image tar/tar.gz bytes. Transfer/load only if the remote exact image
  is absent, following the prior overlay.
- Create `/opt/miru/app/releases/<NEW_BUILD_ID>` as a new directory. Never overlay either failed
  release.
- Preserve all previous archives, releases, tags, image IDs, Secrets, logs, evidence and
  `/opt/miru/data`.

## E. Re-entry Matrix

| Prior stage | Disposition | Required treatment |
| --- | --- | --- |
| RM-R0 identity/containment | **RERUN narrow identity and containment subset** | New overlay/manifest/BUILD_ID require a new freeze. Inherit tests only if HEAD, diff and every image build input are byte-identical. Revalidate current, containers, network, data, listeners, UFW, Tailscale and releases read-only. |
| RM-R1 corrected Compose | **INHERIT bytes; REVALIDATE** | Do not reapply the argv patch. Rehash exact corrected Compose and rerun local/remote JSON render assertions and Caddy validation. |
| RM-R2 identity/archive | **MUST RERUN package/identity subset** | Generate manifest v3, new BUILD_ID/tag, full archive and activation envelope. No build, pull or `docker save`. |
| RM-R3 remote release | **MUST RERUN** | Create a distinct immutable directory and install explicit metadata. |
| RM-R4 Secret/data gate | **INHERIT + REVALIDATE** | Do not recreate, chmod, chown, hash or rotate Secrets. Recheck type, UID/GID/mode/non-empty predicate only; recheck empty writable data. |
| RM-R5 render/current | **MUST RERUN for new release** | Render from the installed path, assert binds/argv/IDs/metadata, then atomically switch only after approval. |
| Failed RM-R6 | **REMAINS FAIL; NEVER RETRY THAT RELEASE** | Preserve it. A single startup of the newly derived release is a new overlay gate after both readability assertions pass. |
| RM-R7 | **BLOCKED** | Enter only after the new startup gate passes and this overlay result is sealed. |
| P4-R8 | **BLOCKED** | Never auto-enter; requires explicit acceptance in a later turn. |

## F. New Startup Gate

### F.1 Metadata and rendered-contract assertion

Before any application startup or `current` switch, machine-assert:

1. Every directory/file in C.1 has the exact type, numeric UID:GID and mode.
2. Settings and Caddyfile content hashes equal the unchanged approved hashes.
3. Rendered API user is exactly `10001:10001`, `group_add` is absent, capabilities are all dropped,
   and the settings bind source/target is exact and read-only.
4. Rendered Caddy has no `user` or `group_add` override, capabilities are all dropped, and its file
   bind source/target is exact and read-only.
5. Image refs resolve to the approved exact IDs; data remains empty; Secret metadata remains
   unchanged; there are zero production containers/network/listeners.

Reject a host-only `sudo -u '#10001' -g '#10001' test -r <host-path>` as proof unless all
supplementary groups are explicitly cleared; even with groups cleared, release-parent traversal
differs from Docker bind-source resolution and is not the final gate.

### F.2 Exact Miru readability assertion

After the new inactive release is installed, run one explicitly approved ephemeral validation
container. It mounts no Secret, data, Docker socket or network and starts no application:

```sh
set -eu
NEW_RELEASE='/opt/miru/app/releases/<NEW_BUILD_ID>'
MIRU_REF='miru-cloud:<NEW_BUILD_ID>'

docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges=true \
  --user 10001:10001 \
  --entrypoint /bin/sh \
  --mount "type=bind,src=$NEW_RELEASE/config/settings.production.yaml,dst=/app/config/settings.production.yaml,readonly" \
  "$MIRU_REF" -ec '
    test "$(id -u)" = 10001
    test "$(id -g)" = 10001
    ! id -G | tr " " "\n" | grep -qx 1001
    test -r /app/config/settings.production.yaml
    test ! -w /app/config/settings.production.yaml
    dd if=/app/config/settings.production.yaml of=/dev/null bs=4096 status=none
  '
```

PASS proves the exact image user can open and read the complete bind-mounted settings file under
the production capability/read-only constraints. No config content is printed.

### F.3 Exact Caddy readability assertion

Run a second explicitly approved ephemeral validation container with the exact Caddy image and no
network or application dependency:

```sh
set -eu
NEW_RELEASE='/opt/miru/app/releases/<NEW_BUILD_ID>'
CADDY_REF='miru-caddy:98eb57d882cc'

docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges=true \
  --entrypoint /bin/sh \
  --mount "type=bind,src=$NEW_RELEASE/config/Caddyfile.production,dst=/etc/caddy/Caddyfile,readonly" \
  "$CADDY_REF" -ec '
    test "$(id -u)" = 0
    test "$(id -g)" = 0
    ! id -G | tr " " "\n" | grep -qx 1001
    test -r /etc/caddy/Caddyfile
    test ! -w /etc/caddy/Caddyfile
    dd if=/etc/caddy/Caddyfile of=/dev/null bs=4096 status=none
  '
```

These two commands are bounded Docker-host mutations because they create auto-removed validation
containers. They are not a Production Compose startup: they use no `miru-prod` project, port,
network, Secret, data or provider call. Require human approval before them. Afterward assert both
containers are gone, `miru-prod-network` is absent, data is still empty, and no listener appeared.

Only both PASS results authorize the later atomic `current` switch and one startup of the new
release. A failure is STOP, not permission to chmod/chown in place or retry with `0644`.

## G. Failure Evidence and Rollback

### G.1 Before startup

If identity, installation, render or either readability probe fails:

1. Do not switch `current` and do not start the stack.
2. Capture value-free command exit, exact path, expected/actual metadata, image ID and rendered
   bind/user/capability facts.
3. Preserve the inactive new release and failed-gate evidence for review.
4. Do not auto-repair metadata, loosen to world-readable, add `group_add`, or rerun the failed gate.

### G.2 After startup authorization

The prior RM-R6 evidence procedure remains mandatory. Whether startup succeeds or fails, capture
invocation/cwd, Compose version, exact config/hash/IDs, Compose stdout/stderr, all service/container
states, actual Path/Args, exit/Error/OOM/restarts/health, bounded logs, data/DB/WAL/SHM state,
listeners/UFW and non-printing exact-Secret/signature scans before containment.

The single authorized startup invocation is unchanged and must run only after CR-R5 PASS:

```sh
set -eu
cd /opt/miru/app/current
docker compose -p miru-prod --env-file .release.env \
  -f config/compose.production.yaml up -d
```

Capture its nonzero exit without allowing `set -e` to skip evidence collection, exactly as defined
by the prior RM-R6 procedure. Do not run this command a second time.

On any FAIL:

```sh
docker compose -p miru-prod --env-file .release.env \
  -f config/compose.production.yaml down
```

- Never add `-v`.
- Never retry automatically.
- Verify zero containers and `miru-prod-network` absent, no business listener and UFW unchanged.
- Atomically restore the recorded prior `current`; do not start that known-defective release.
- Preserve every failed release, complete evidence set, log, image tag/ID, archive and provenance.
- Preserve all DB/WAL/SHM/attachments/data even if first-start or empty of business rows. Never
  delete, overwrite, downgrade, raw-copy live data or reuse it without a new plan.
- Preserve both Secrets unchanged unless a leak is positively detected. A detected leak requires
  containment and a separate human rotation gate; never print or copy matching bytes.

## H. Luna Handoff

### H.1 Required reading

Read in order:

1. `docs/phase4-final-execution-runbook.md`
2. `docs/phase4-p4-r7-remediation-runbook.md`
3. This overlay
4. Original failed P4-R7 evidence
5. RM-R0, RM-R1 and RM-R2 evidence
6. The complete remote failed-corrected-release `evidence/p4-r7-retry` set

### H.2 Stage boundaries

Execute exactly one stage per authorization using `CHECK -> EXECUTE -> VERIFY -> PASS/FAIL ->
STOP`:

| New overlay stage | Boundary | Approval / stop rule |
| --- | --- | --- |
| CR-R0 — reconciliation | Read-only local/remote identity, complete failed-evidence hashes, containment and bind audit | Report and STOP for manifest/remediation approval |
| CR-R1 — local identity/package | Generate manifest v3, NEW_BUILD_ID, exact same-ID Miru tag, new local archives; no build/save | Report hashes/IDs and STOP for remote-release approval |
| CR-R2 — remote immutable install | Create only the approved new directory; install C.1 metadata; no `current`, containers or data | Human approval before sudo mutation; report and STOP |
| CR-R3 — readability gates | Re-render and run only F.2/F.3 ephemeral non-secret containers | Human approval before Docker mutation; any failure STOP; report and STOP |
| CR-R4 — inherited Secret/data gate | Metadata/non-empty Secret predicates only; empty/writable data; never reveal or alter values | Any mismatch STOP; report and STOP |
| CR-R5 — activation selection | Final installed render/ID/metadata checks and atomic `current` switch; no startup | Human approval before switch; report and STOP |
| CR-R6 — one new-release startup | Execute the full preserved pre-capture/start/capture/verify gate once | Separate explicit startup approval; failure capture before containment; no retry; STOP |
| CR-R7 — seal/handoff | Write value-free PASS/FAIL report and evidence hashes | Always STOP. RM-R7/P4-R8 remain blocked pending explicit later acceptance |

Luna must not modify source, Dockerfiles, Compose, settings bytes, Caddyfile bytes, Secrets, frozen
architecture, either failed release, or `/opt/miru/data`. Only new identity/package/release metadata
and the exact activation/evidence actions above are authorized by this overlay after their human
gates.

## Final Decision

```text
original argv defect resolved = YES
new root cause confirmed = YES
second adjacent permission blocker found = YES
architecture change required = NO
source code change required = NO
Miru image rebuild required = NO
Caddy image rebuild required = NO
docker save required = NO
Secrets rotation required = NO
new immutable release required = YES
failed RM-R6 release preserved = YES
new remediation ready for execution = YES
```

STOP
