# Miru Assistant Phase 4 — P4-R7 Remediation Release Runbook

**Planning date:** 2026-08-29  
**Document status:** FINAL REMEDIATION PLAN / NOT EXECUTED  
**Role boundary:** Remediation Planning Model  
**Controlling specification:** `docs/phase4-final-execution-runbook.md`  
**Execution boundary:** Writing this document did not change source/config, build or save an
image, contact or mutate the Production Host, start a container, create a database, change a
Secret, install Tailscale, or enter P4-R8.

This runbook is a narrow corrective overlay. Where it conflicts with the original runbook for
P4-R0 through P4-R7, this document controls only the P4-R7 remediation release. All frozen Phase
4 architecture and every P4-R8+ requirement remain controlled by the original runbook.

## A. Incident Summary

### A.1 Failed immutable release

| Item | Proven value |
| --- | --- |
| Failed BUILD_ID | `p4-20260828-2053-194b844-1446158b` |
| Branch / HEAD | `master` / `194b8442608b3cc516d0a3ddf8118a0695cc0f44` |
| Manifest input SHA-256 | `1446158b0afdeb3967e7db7db160886373dc4967bd4107a288fb01103f1b8a8d` |
| Miru image | `miru-cloud:p4-20260828-2053-194b844-1446158b` |
| Miru image ID | `sha256:90a1733e760b270a0afa70ed48bb13e366010483f7360e3e156c2044f44139ad` |
| Caddy image ID | `sha256:98eb57d882ccd5213d1688764db10c1ca2c58a1ca3a6717a3411ad798f7a423a` |
| Failed release archive SHA-256 | `9fcdbd6fd34a46db96af62acae3962e146cbf36d8e6fe26d20c4768a0bd86a56` |
| First failed stage | `P4-R7` |
| P4-R8 entered | No |

The retained primary evidence is:

`docs/evidence/phase4/p4-20260828-2053-194b844-1446158b/p4-r7-controlled-diagnostic-reproduction.txt`

### A.2 Confirmed root cause

The failed Compose definition combined:

```yaml
entrypoint: ["/bin/sh", "-ec"]
command: |
  export MIRU_SERVER_TOKEN="$$(cat /run/secrets/server_token)"
  export MIRU_DEEPSEEK_API_KEY="$$(cat /run/secrets/deepseek_api_key)"
  exec python -m miru_server --profile cloud --host 0.0.0.0 --port 8765
```

with an actual container process shape of:

```text
Path = /bin/sh
Args = ["-ec", "export", "MIRU_SERVER_TOKEN=$(cat ...)", "export", ...]
```

`sh -c` therefore received only `export` as its command string. The remaining elements became
positional parameters. Python was never executed, the shell exited 0, `unless-stopped` caused a
restart loop, the API never became healthy, Caddy remained `Created`, and SQLite initialization
was never reached. This is a confirmed **runtime command/entrypoint argument-shape defect** and
**production deployment configuration defect**.

The path hypothesis is rejected. The proven Production layout and invocation are:

```text
<release>/config/compose.production.yaml
<release>/config/settings.production.yaml
<release>/config/Caddyfile.production
<release>/.release.env

cd /opt/miru/app/current
docker compose -p miru-prod --env-file .release.env \
  -f config/compose.production.yaml ...
```

Relative bind sources therefore resolve from `<release>/config`, which correctly finds the
settings and Caddy files. The original runbook's root-level `-f compose.production.yaml`
examples are a documentation/layout deviation, not the startup root cause. All commands in this
overlay use the proven `config/` path.

### A.3 Reproduction and containment facts

The controlled reproduction recorded `status=restarting`, restart count 14, exit code 0, empty
`State.Error`, `OOMKilled=false`, no health log opportunity, Caddy `Created`, no DB/WAL/SHM, and
no Secret leakage. Containment used `docker compose down` without `-v`.

The last proven post-containment state is: zero containers; `/opt/miru/data` empty; Production
Secrets, failed release, and exact images retained; UFW permits only SSH 22; no listener on
80/443/8765/18080; Tailscale and host Caddy absent/inactive; no public business exposure; no
Secret leakage; and no data loss. These facts may be inherited as evidence but must be
read-only revalidated before any new mutation.

## B. Frozen Architecture Confirmation

No architecture change is authorized or required. The remediation preserves:

- Tailscale Serve private-only HTTPS/WSS ingress, with Funnel off.
- Host-loopback Caddy at `127.0.0.1:18080` and no host-published API port.
- The two host Secret files bind-mounted read-only, then exported only inside the process.
- SQLite WAL storage at `/opt/miru/data`, fresh database initialization, and no Windows DB import.
- Miru UID/GID `10001:10001`, read-only container roots, tmpfs, capabilities and resource limits.
- Existing Caddy routing, header stripping, later-phase route denial and private Compose network.
- UFW/Security Group public exposure policy and all Phase boundaries.

This overlay does not authorize Tailscale installation, Flutter, Home Node, WeChat, voice,
attachment-worker, Phase 5 work, or any public port.

## C. Corrected Compose Contract

### C.1 Frozen remediation

Replace only the failed `entrypoint`/`command` fragment with these exact LF-terminated bytes:

```yaml
    entrypoint: ["/bin/sh"]
    command:
      - -ec
      - |
        test -r /run/secrets/server_token
        test -r /run/secrets/deepseek_api_key
        MIRU_SERVER_TOKEN="$$(cat /run/secrets/server_token)"
        MIRU_DEEPSEEK_API_KEY="$$(cat /run/secrets/deepseek_api_key)"
        test -n "$$MIRU_SERVER_TOKEN"
        test -n "$$MIRU_DEEPSEEK_API_KEY"
        export MIRU_SERVER_TOKEN MIRU_DEEPSEEK_API_KEY
        exec python -m miru_server --profile cloud --host 0.0.0.0 --port 8765
```

With every other byte in the current production Compose file unchanged, the planned result is:

```text
bytes=2982
sha256=4d3d0de364480d53e70e9fbea455284aff99f9eb0ef8112e23a8ed310d0355ad
```

The execution model must recompute both values. A mismatch means the file is not the frozen
remediation and must STOP for review; it must not silently normalize or format the file.

### C.2 Why this is the unique selected form

The retained Miru image has no image `ENTRYPOINT`; its image `Cmd` is the exec-form Python argv.
Compose's non-null `entrypoint` overrides the executable and suppresses the image default command;
the explicit two-item command list supplies exactly the shell option and one complete script
argument. The required final container shape is:

```text
Entrypoint = ["/bin/sh"]
Cmd[0] = "-ec"
Cmd[1] = "test -r ...\n...\nexec python ...\n"
Path = /bin/sh
Args = ["-ec", "<the complete multiline script as one element>"]
```

This conclusion was independently checked against the proven Production Compose 5.5.0 process
evidence, the current production YAML, the retained OCI image config/layers, and Docker's current
official Compose/Dockerfile semantics. The planning sandbox had no callable Docker CLI, so it did
not create or start a validation container; RM-R1 therefore makes JSON rendering under both the
available local validator and Production Compose 5.5.0 a mandatory machine assertion before the
release is frozen.

The form is chosen because it makes the argv boundary structural. It does not depend on Compose
interpreting a block scalar as one shell command, does not add a script to the image, and does not
require an image rebuild.

Candidate disposition:

| Candidate | Decision | Reason |
| --- | --- | --- |
| `entrypoint: ["/bin/sh"]` + two-item command list | **SELECTED** | Minimal config-only change; executable, option and one script argument are unambiguous. |
| Entrypoint list containing shell, flags and script | Rejected | Can work, but hides the whole runtime command in `Entrypoint` and is less clear to inspect/override. |
| Command array with Python only | Rejected | Cannot read and export the mounted Secret files without a shell or code change. |
| Dedicated entrypoint script | Rejected | Adds image/source infrastructure and forces an unnecessary image rebuild. |
| Original entrypoint plus block-scalar command | Rejected | Already proven to render to the wrong argv on the Production Compose version. |

### C.3 Shell, interpolation, Secret and signal semantics

- Compose processes YAML values before container creation. Each `$$` becomes one literal `$` in
  the container command and prevents host-side Compose interpolation. Rendered config must contain
  `$(cat ...)` and `$MIRU_...`, never a credential value.
- `/bin/sh -ec <script>` uses `-c` to execute exactly `Cmd[1]`; `-e` exits on failed readability,
  failed file read/assignment, or empty-value checks.
- Assignment and export are deliberately separate. `export VAR="$(cat ...)"` can mask a failed
  substitution behind the `export` built-in's success status on POSIX shells.
- Command substitution strips trailing newlines from the files. Quoting preserves every other
  character without word splitting or globbing.
- The non-empty tests fail closed for both credentials before application startup. The application
  independently fails closed when the Cloud server token is empty, and `/readyz` requires both
  token and provider key.
- Secret values are process environment only after the shell reads the mounted files. They are not
  in Compose `environment`, `.release.env`, image metadata, Docker Config.Env, Git, or host-visible
  argv. Root/Docker administrators can still inspect process environments; that inherited trust
  boundary is unchanged.
- `exec` replaces shell PID 1 with Python. Docker's `SIGTERM` reaches Python/Uvicorn directly and
  does not leave a shell parent that could break graceful shutdown.

Official semantic references: [Compose services `command` and `entrypoint`](https://docs.docker.com/reference/compose-file/services/),
[Compose `$$` interpolation](https://docs.docker.com/reference/compose-file/interpolation/), and
[Docker exec-form/PID 1 behavior](https://docs.docker.com/reference/dockerfile/).

## D. Adjacent Static Validation

The following review is limited to blockers that could prevent the corrected P4-R7 startup.
Every item is a hard pre-start assertion for the new release.

| Item | Static conclusion | Execution gate |
| --- | --- | --- |
| Secret permissions | Proven files are UID/GID 10001, mode 0400; compatible with service user after Docker bind-mounts each file. Host-parent traversal is performed by the root Docker daemon and is not an equivalent UID-read test. | Recheck regular file, owner/group, mode, non-zero size and exact read-only target binds; the script's first in-container `test -r` predicates are the final proof. Never print/hash contents. |
| Data bind ownership | `/opt/miru/data` is 10001:10001 mode 0750 and empty. | Recheck real path, owner/mode, emptiness and UID 10001 write+execute access without creating a probe file. |
| Settings path | `-f config/compose.production.yaml` makes `./settings.production.yaml` resolve under release `config/`. | Render mounts and compare the resolved host source to the new release's exact file. |
| Persona path | WorkingDir `/app`; image contains `/app/config/persona/miru.yaml`. | Inspect retained image/layer evidence; require path present and readable. |
| Pricing path | Config directory is `/app/config`; image contains `/app/config/pricing.yaml`. | Inspect retained image/layer evidence; require path present and readable. |
| API healthcheck | Exec-form `python -c urllib.request.../healthz`; Python and urllib are in the retained image; `/healthz` is public liveness. | Render as a five-element command; no shell splitting or token required. |
| Read-only root + tmpfs | Runtime logs/DB resolve under bind-mounted `/app/data`; Python bytecode is disabled; `/tmp` is tmpfs. | Render `read_only=true`, `/tmp` tmpfs and `/opt/miru/data:/app/data`; reject any other write target needed at startup. |
| Caddy dependency | `condition: service_healthy` correctly prevents Caddy startup until API health passes. | Render exact condition; do not weaken to `service_started`. |
| Caddy root/tmpfs | Official Caddy uses `/config` and `/data`; both are writable tmpfs under read-only root. | Revalidate exact image config and Caddyfile; verify `wget` exists for healthcheck. |
| SQLite path | `./data/miru_server.db` resolves from project `/app` to `/app/data/miru_server.db`. | Require host bind is empty and writable by 10001 before first start. |
| Cloud fail-closed | App rejects empty Cloud server token before creating services/DB. `/readyz` also requires API key. | Preserve profile and env references; synthetic static test must prove missing/empty token fails. |
| DeepSeek interpolation | Settings retains `${MIRU_DEEPSEEK_API_KEY}`; application resolves it from process environment. | Require Compose-rendered command has literal shell expansion and rendered service environment has no value. |
| Rendered argv | Selected list form must produce two command elements. | Machine-assert `Entrypoint=[/bin/sh]`, command count 2, `command[0]=-ec`, and full script only in `command[1]`. |
| Miru user/image | Image config says user `miru` (UID 10001), WorkingDir `/app`, no EntryPoint, exact exec-form Python Cmd. Compose pins `10001:10001`. | Reinspect exact image ID/config; fail on tag-to-ID drift. |
| Runtime files | Retained OCI artifact contains `/bin/sh` (dash), Python, `miru_server/__main__.py`, persona and pricing. | Revalidate retained tar hashes and member evidence; no rebuild needed. |
| API publication | API uses only `expose: 8765`; no host `ports`. | Rendered API `ports` must be absent. |
| Caddy publication | Only `127.0.0.1:18080:8080`. | Rendered host IP must equal `127.0.0.1`; reject `0.0.0.0`, `::`, 80 or 443. |

Current read-only planning review found no second statically visible P4-R7 startup blocker. This is
not permission to skip the execution-day assertions.

## E. New Release Identity

### E.1 Identity rule

A new immutable release is mandatory. Never edit, repack under, or retag changed content as
`p4-20260828-2053-194b844-1446158b`.

Use manifest format version 2 and derive:

```text
manifest_input_sha256 = SHA-256(canonical UTF-8 manifest payload, excluding the
                               manifest_input_sha256 and BUILD_ID result lines)
NEW_BUILD_ID = p4-<UTC-YYYYMMDD-HHMM>-194b844-<first8(manifest_input_sha256)>
```

The timestamp is the actual freeze minute, not the old release time. If HEAD is not exactly the
recorded 40-character value, STOP; this remediation does not authorize incorporating new source.
If a new approved source release is desired, it requires a separate build/review path.

### E.2 Manifest v2 inputs

Hash and record, in stable ordinal path order:

1. Branch, full HEAD, filtered `git status`, and binary diff identity using the same exclusions as
   the old manifest, plus the canonicalization command/version.
2. Every prior image build input: `deploy/Dockerfile`, `deploy/requirements-cloud.txt`,
   `deploy/settings.cloud.example.yaml`, pricing, persona, `.dockerignore`, and the complete
   `miru_server` tree.
3. Both controlling documents: the original Phase 4 runbook and this remediation runbook.
4. All three production files, now as real inputs rather than `NOT_PRESENT_PLANNED`: corrected
   Compose, unchanged settings and unchanged Caddyfile.
5. Inherited image/artifact identities and hashes: Miru Image ID/config digest/tar hashes, Caddy
   digest/tar hashes, and old provenance evidence hashes.
6. An explicit statement that no Secret, `.release.env` value, runtime data, or generated BUILD_ID
   line is a manifest input.

The Compose hash must be the frozen value in C.1. Settings must remain
`bbd935d44dc6b3a4a3f9e061a2ff6a85e46946cb8d7f6e9d65cf0850abe421b4`; Caddyfile must remain
`05fc5356eae11e7b0431b85dfd86f8489092203629ed63bfb888f059dfbefe2d`.

### E.3 Image and artifact strategy

- **Miru rebuild:** not required and forbidden for this remediation. First prove all Miru build
  inputs equal the old manifest and the retained image equals Image ID
  `sha256:90a1733e760b270a0afa70ed48bb13e366010483f7360e3e156c2044f44139ad`.
- **Miru tag:** create `miru-cloud:<NEW_BUILD_ID>` as a new release-membership tag pointing to that
  same exact Image ID. Record both old and new tag-to-ID mappings. A different ID is FAIL.
- **Caddy:** reuse `miru-caddy:98eb57d882cc` and exact ID/digest
  `sha256:98eb57d882ccd5213d1688764db10c1ca2c58a1ca3a6717a3411ad798f7a423a`;
  no pull, rebuild, or new tag is needed.
- **Image tar files:** reuse the already verified tar bytes and hashes. Do not run `docker save`.
  Recompute their SHA-256 before inclusion/reference.
- **Release archive:** rebuild a new wrapper archive because config, manifest, `.release.env`,
  BUILD_ID and archive membership metadata changed. The canonical local full archive includes the
  unchanged verified Miru/Caddy tar and tar.gz bytes; record new wrapper SHA-256 and byte size
  twice.
- **Remote activation envelope:** also build and double-hash a small archive containing only root
  `.release.env`, `config/`, new `evidence/`, and `artifacts/reused-images.sha256`. Transfer this
  envelope by default. The artifact map records the exact global image IDs, inherited tar hashes
  and retained old-release artifact paths; it contains no image bytes or Secret.
- **Archive layout:** the installed release root uses `config/` (singular) and root
  `.release.env`. Record this as the correction of the original documentation/package deviation.
- **Remote directory:** create `/opt/miru/app/releases/<NEW_BUILD_ID>`; never overlay the failed
  directory.
- **Remote image loading:** may be skipped only after remote exact-ID inspection passes. If either
  image is absent, first verify and load the inherited tar already retained under the failed
  release. Only if that retained tar is absent/corrupt may the same verified local tar be
  transferred separately. Re-inspect, then tag. Never pull a substitute.
- **`current`:** switch atomically only at the remediation R6 gate after the new directory,
  configs, `.release.env`, images, Secrets and empty storage all pass.
- **Failed release:** retain it, its archive, hashes, evidence, old image tag and remote directory
  byte-for-byte as rollback/incident evidence.

## F. Stage Re-entry Matrix

| Original stage | Disposition | Required treatment and reason |
| --- | --- | --- |
| P4-R0 | **RERUN identity subset; INHERIT tests conditionally** | New config and manifest require a new freeze/BUILD_ID. Full tests and source provenance may be inherited only if every image build input, HEAD and filtered tree identity exactly match the failed release; otherwise STOP. |
| P4-R1 | **MUST RERUN** | Corrected Compose is the changed defect surface. Rendered argv, interpolation, mounts, ports, Caddy validation and forbidden scans must all be regenerated under the current Compose binary. |
| P4-R2 | **PARTIAL RERUN** | Rebuild/save are not required. Revalidate exact image/tar provenance, add the new tag to the same Miru Image ID, rebuild manifest/bundle/archive and hash them. |
| P4-R3 | **MUST RERUN** | Immutable-release policy requires a new remote versioned directory. |
| P4-R4 | **PARTIAL RERUN** | Transfer and verify new config/manifest/release material. Image transfer/load may be skipped when exact retained remote IDs pass; otherwise use inherited verified tars. |
| P4-R5 | **INHERIT + MUST REVALIDATE** | Existing Secrets are neither leaked nor invalid. Do not recreate or rotate. Recheck only path/type/owner/mode/non-zero length and UID 10001 readability. |
| P4-R6 | **MUST RERUN** | New `.release.env`, image ref, release path, Compose render and atomic `current` switch are release-specific. Reconfirm data is empty. |
| P4-R7 | **MUST RERUN** | This is the corrected startup gate and requires improved pre-containment evidence. |
| P4-R8 | **NOT REQUIRED / BLOCKED** | It was never entered. It remains forbidden until the new P4-R7 is formally PASS. |

Inherited but execution-day revalidated facts include the Phase 3B host baseline, Secrets,
Caddy/Miru image provenance, absent Tailscale, SSH-only UFW, no business listeners and empty data.
Inheritance means “do not repeat the mutation,” never “skip the drift check.”

## G. Exact Execution Stages

Use one stage at a time: `CHECK -> EXECUTE -> VERIFY -> PASS -> NEXT`. Commands below are templates
for LUNA; substitute only derived non-secret identifiers. Never place a credential in a command,
chat, `.release.env`, evidence filename or shell history.

### RM-R0 — Reconcile containment and freeze remediation inputs

**Objective:** prove the failed release remains contained and freeze a config-only remediation
against the exact retained source/image input.

**Preconditions:** original and remediation runbooks plus old evidence available; no new Production
mutation; known-host SSH key/fingerprint unchanged.

**Read-only Checks:** local branch/HEAD/status/diff; old manifest and production hashes; remote
containers, `current`, release files, data names, image IDs, Secret metadata, disk, UFW, listeners,
Tailscale and host Caddy.

**Commands:**

```powershell
git -c safe.directory='E:/vibe coding/miru-assistant' status --short --branch
git -c safe.directory='E:/vibe coding/miru-assistant' rev-parse HEAD
git -c safe.directory='E:/vibe coding/miru-assistant' diff --check
Get-FileHash -Algorithm SHA256 -LiteralPath 'deploy/production/compose.production.yaml','deploy/production/settings.production.yaml','deploy/production/Caddyfile.production'
```

```sh
set -eu
docker compose version
docker ps -a --format '{{.ID}} {{.Names}} {{.Status}}'
readlink -f /opt/miru/app/current
sudo find /opt/miru/data -mindepth 1 -maxdepth 2 -printf '%P\n'
docker image inspect --format '{{.Id}} {{json .Config.User}} {{json .Config.Entrypoint}} {{json .Config.Cmd}}' \
  miru-cloud:p4-20260828-2053-194b844-1446158b
docker image inspect --format '{{.Id}}' miru-caddy:98eb57d882cc
sudo stat -c '%n %F %u:%g %a %s' /opt/miru/secrets/server_token \
  /opt/miru/secrets/deepseek_api_key /opt/miru/data
sudo ufw status verbose
ss -lntup
command -v tailscale || true
systemctl is-active tailscaled caddy || true
```

**Mutations:** a new local evidence directory only after reconciliation; no source/config or remote
mutation.

**Verification:** HEAD exact; all image build inputs match old manifest; old release hashes and
image IDs match; zero containers; data empty; no business listener; UFW SSH-only; Tailscale/host
Caddy absent; Secrets metadata unchanged.

**PASS:** exact source/image inheritance and contained host are proven. Old test evidence is
accepted without rerun only under complete byte identity.

**FAIL:** any source build-input drift, tag-to-ID drift, container/listener/data appearance,
Secret metadata change, or host baseline drift.

**Rollback:** none; checks are read-only. Remove only the newly created empty evidence directory
if desired.

**Secret Risk:** do not run `env`, print Secret contents, hash a Secret, or save full container
inspect output.

**User Action Required:** approve the exact config-only inheritance boundary and source manifest
inputs.

**STOP Conditions:** any mismatch or inability to identify the host/release unambiguously.

### RM-R1 — Apply the one-file correction and statically prove argv

**Objective:** create the corrected Compose definition and prove it renders the exact two-element
command without changing settings, Caddyfile or business source.

**Preconditions:** RM-R0 PASS; original Compose hash equals
`1b889baede4de51a21e59aeb03f74a49fd42257064e5badea65da2332f9f1718`.

**Read-only Checks:** reconfirm current file bytes and inspect Compose version/help for JSON config
output; record the production version (previously 5.5.0) and local validation version separately.

**Commands:** use a byte-exact patch for C.1, then:

```powershell
Get-FileHash -Algorithm SHA256 deploy/production/compose.production.yaml
$env:MIRU_BUILD_ID='p4-synthetic-static-only'
$env:MIRU_IMAGE_REF='miru-cloud:synthetic-static-only'
$env:CADDY_IMAGE_REF='miru-caddy:98eb57d882cc'
docker compose --project-directory deploy/production -f deploy/production/compose.production.yaml config --format json
```

Run a parser assertion over the JSON rather than visually accepting it. It must verify entrypoint,
command length/content, Secret path mounts, API no-ports, Caddy loopback port, user, healthchecks,
read-only/tmpfs, dependency condition and resource constraints. Also run YAML parsing, Caddy
validation with the exact retained image, and Secret/forbidden-string scans with synthetic values.

**Mutations:** exactly `deploy/production/compose.production.yaml` and new value-free evidence.

**Verification:** file is 2982 bytes with C.1 hash; settings/Caddy hashes unchanged; rendered
command has exactly `[-ec, complete_script]`; literal `$` reaches the script; no Secret value,
phase2/mock/WeChat/public API bind or unapproved path appears.

**PASS:** every C and D contract assertion passes under both local validation Compose and remote
Production Compose 5.5.0 read-only rendering.

**FAIL:** any tokenized script, hash mismatch, extra changed file, Compose warning/error, Secret
expansion, Caddy validation failure or adjacent gate failure.

**Rollback:** before release freeze, restore only this newly applied fragment from the recorded old
bytes if abandoning remediation; never edit the retained remote release.

**Secret Risk:** synthetic identifiers only. The rendered document may contain Secret paths/names,
never values.

**User Action Required:** review the one-file diff and exact rendered argv assertion.

**STOP Conditions:** a business-code/image change appears necessary, or exact argv cannot be
machine-proven.

### RM-R2 — Generate manifest v2, identity and immutable local release archive

**Objective:** derive a new identity and package the corrected release without rebuilding/saving
images.

**Preconditions:** RM-R1 PASS; inherited image/tar bytes and hashes match old evidence.

**Read-only Checks:** rehash every E.2 input and old image tar; inspect OCI image config/layers for
user, no EntryPoint, Python Cmd, `/bin/sh`, Python, module, persona and pricing; inspect Caddy
version/config and `wget`.

**Commands:** generate canonical `source-manifest-v2.sha256`, compute its input SHA-256 and
`NEW_BUILD_ID`, create the new Miru tag against the exact existing ID, generate a non-secret
`.release.env`, assemble a new release root/archive, then hash archive by two implementations.

```dotenv
MIRU_BUILD_ID=<NEW_BUILD_ID>
MIRU_IMAGE_REF=miru-cloud:<NEW_BUILD_ID>
CADDY_IMAGE_REF=miru-caddy:98eb57d882cc
```

The canonical full archive contains root `.release.env`, `config/` with the three production
files, `evidence/` with manifest/static/provenance records, and the unchanged verified Miru/Caddy
tar and tar.gz bytes. The separate activation envelope contains the same release metadata/config
plus `artifacts/reused-images.sha256`, but no image bytes. Neither archive contains source, Secret,
data, a Windows path or later-phase material.

**Mutations:** new local image tag, manifest, bundle and archive only. No build, pull, push,
`docker save`, global prune or source change.

**Verification:** new tag and old tag both resolve to exact Miru Image ID; Caddy exact ID; both
archive member allowlists pass; each archive's two independently calculated hashes agree; the
full archive carries the unchanged image bytes; the activation envelope carries only their exact
map; config/manifest carries C.1 hash and new BUILD_ID; no circular derived field entered manifest
input.

**PASS:** immutable new identity and reproducible value-free archive exist with inherited exact
image bytes.

**FAIL:** any image/tar/input mismatch, a new image ID, old BUILD_ID reuse, hash disagreement,
archive path escape or forbidden material.

**Rollback:** remove only the new tag and newly created bundle/archive after verifying they are the
new targets and are unreferenced. Never remove inherited images/tars or old evidence.

**Secret Risk:** scan archive names and text; never include or scan by printing real values.

**User Action Required:** approve the final manifest input hash, NEW_BUILD_ID, archive SHA-256 and
reuse of the exact Miru/Caddy image IDs.

**STOP Conditions:** source inputs no longer match the retained image or any artifact identity is
ambiguous.

### RM-R3 — Create and populate the new remote immutable release

**Objective:** create a separate remote release, transfer only verified non-secret materials, and
reuse exact retained images when safe.

**Preconditions:** RM-R2 PASS; at least 5 GB free; containment still clean; exact target path does
not exist.

**Read-only Checks:** resolve parent/target; disk; Docker storage; listeners/UFW; old release and
artifact hashes; remote old tag-to-ID mappings.

**Commands:**

```sh
set -eu
NEW_BUILD_ID='<approved-derived-id>'
NEW_RELEASE="/opt/miru/app/releases/$NEW_BUILD_ID"
test ! -e "$NEW_RELEASE"
case "$NEW_RELEASE" in /opt/miru/app/releases/p4-*) ;; *) exit 1 ;; esac
sudo install -d -o ubuntu -g ubuntu -m 0750 "$NEW_RELEASE" \
  "$NEW_RELEASE/config" "$NEW_RELEASE/artifacts" "$NEW_RELEASE/evidence"
```

SCP the new activation envelope to that exact target, compare its approved local SHA-256, list
members before extraction, reject absolute/`..` paths, and install configs mode 0640. If remote
image IDs match, skip transfer/load of duplicate image bytes and record `REUSED_EXACT_ID`. Create
the new Miru tag from the old exact image ID and verify it. If an image is absent, hash and load its
tar from the retained failed release; transfer the exact inherited tar separately only when the
retained remote copy is unavailable.

**Mutations:** the one new release directory, transferred files, and new Miru tag; no `current`
switch and no containers.

**Verification:** remote config hashes/BUILD_ID/archive match local; image refs resolve to exact
approved IDs; release contains no Secret/source/data; `/opt/miru/data` stays empty.

**PASS:** isolated, complete, immutable remote release is ready but inactive.

**FAIL:** target preexists, path escapes, hash mismatch, unexpected archive member, image-ID drift,
load/tag collision, listener/container or data drift.

**Rollback:** remove only the verified inactive new directory and new unreferenced tag after
preserving failure evidence. Never prune or touch the failed release.

**Secret Risk:** payload is value-free. Do not transfer `.env` other than the approved identifier-
only `.release.env`.

**User Action Required:** approve exact `sudo install` target and any fallback image load.

**STOP Conditions:** any hash/path/image mismatch.

### RM-R4 — Revalidate inherited Secrets and empty writable storage

**Objective:** inherit existing credentials without disclosure/rotation and prove UID 10001 can
read/write required paths before startup.

**Preconditions:** RM-R3 PASS; no credential leakage evidence; containers remain zero.

**Read-only Checks:** confirm containers remain zero, the exact four paths resolve under
`/opt/miru`, and no unexpected data entry exists. Do not inspect file contents.

**Commands:**

```sh
set -eu
sudo stat -c '%n %F %u:%g %a %s' \
  /opt/miru/secrets /opt/miru/secrets/server_token \
  /opt/miru/secrets/deepseek_api_key /opt/miru/data
sudo test -f /opt/miru/secrets/server_token
sudo test -f /opt/miru/secrets/deepseek_api_key
sudo test -s /opt/miru/secrets/server_token
sudo test -s /opt/miru/secrets/deepseek_api_key
sudo -u '#10001' -g '#10001' test -w /opt/miru/data
sudo -u '#10001' -g '#10001' test -x /opt/miru/data
test -z "$(sudo find /opt/miru/data -mindepth 1 -maxdepth 1 -print -quit)"
```

Assert Secret directory `0700`, files `10001:10001 0400`, data `10001:10001 0750`, and non-zero
file sizes without recording exact sizes in broadly shared reports. Do not treat inability of host
UID 10001 to traverse a root-owned 0700 Secret parent as a container-read failure: Docker resolves
the source as root and bind-mounts each file at `/run/secrets/*`. The exact read-only mount target,
file UID/mode and the in-container `test -r` in C.1 jointly form the gate.

**Mutations:** none. Do not recreate, chmod, chown, rotate or read content into a shell variable.

**Verification:** all host metadata/data-access predicates and rendered read-only bind predicates
pass; data remains empty. Final UID 10001 Secret readability is fail-closed by the first commands
of RM-R6 and is captured before containment if it unexpectedly fails.

**PASS:** Secrets safely inherited and storage ready.

**FAIL:** wrong type/owner/mode, empty/unreadable file, unexpected data or UID 10001 access failure.

**Rollback:** none; checks are read-only. A needed credential repair/rotation is a separate human
gate and invalidates automatic continuation.

**Secret Risk:** critical. Never `cat`, hash, echo, compare prefix/suffix, or copy either value.

**User Action Required:** none if all inherited checks pass; user action is mandatory if a
credential is invalid or suspected exposed.

**STOP Conditions:** any failed predicate or leakage suspicion.

### RM-R5 — Release-local render and atomic `current` gate

**Objective:** prove the exact installed release renders correctly under Production Compose and
atomically select it without starting anything.

**Preconditions:** RM-R4 PASS; new `.release.env` is identifiers-only mode 0640; old `current`
target recorded as `PREVIOUS_CURRENT`.

**Read-only Checks:** from the new release root, render config with the exact proven invocation;
machine-assert argv, mounts, image IDs, ports, user and dependency; confirm zero containers and
empty data.

**Commands:**

```sh
set -eu
NEW_RELEASE='/opt/miru/app/releases/<NEW_BUILD_ID>'
cd "$NEW_RELEASE"
docker compose -p miru-prod --env-file .release.env \
  -f config/compose.production.yaml config --format json > evidence/compose.rendered.json
```

The evidence file is permitted only after a scan proves it contains identifiers/paths and no
credential-like value. Then atomically switch:

```sh
PREVIOUS_CURRENT="$(readlink -f /opt/miru/app/current)"
sudo ln -s "$NEW_RELEASE" /opt/miru/app/current.remediation-new
sudo mv -Tf /opt/miru/app/current.remediation-new /opt/miru/app/current
readlink -f /opt/miru/app/current
```

**Mutations:** new `.release.env` if not already installed, value-free rendered evidence and the
atomic `current` symlink switch. No container/network/DB.

**Verification:** `current` resolves exactly to new release; Compose file/mount sources resolve
under its `config/`; rendered entrypoint/command have the C.2 shape; image refs resolve exact IDs;
data remains empty.

**PASS:** new inactive release is the selected `current` and ready for one authorized startup.

**FAIL:** render/argv/path/image mismatch, unexpected Secret expansion, symlink mismatch, any
container/data/listener appears.

**Rollback:** atomically restore `PREVIOUS_CURRENT`; remove only a leftover temporary symlink after
verifying it is the exact link. Do not start the previous failed release.

**Secret Risk:** `.release.env` must contain only three identifiers. Never source the Secret files.

**User Action Required:** approve the exact new and previous symlink targets.

**STOP Conditions:** the path-based invocation differs from this runbook or `current` cannot be
switched atomically and verified.

### RM-R6 — New P4-R7 corrected private-loopback startup gate

**Objective:** start the corrected API/Caddy once, capture a complete failure scene before any
containment, and prove healthy schema-2 private-loopback operation.

**Preconditions:** RM-R5 PASS; Tailscale/Serve absent; UFW SSH-only; 18080 free; public recovery
SSH available; user authorizes first startup; evidence directory exists mode 0750.

**Read-only Checks:** repeat `current`, config/env hashes, exact image IDs, Secret metadata, empty
data, zero containers, listeners/UFW/Tailscale and rendered argv. Record UTC time, `pwd -P`, exact
Compose version and exact invocation before starting.

**Commands:** from `/opt/miru/app/current` only:

```sh
set -eu
cd /opt/miru/app/current
EVIDENCE_DIR="$(pwd -P)/evidence/p4-r7-retry"
install -d -m 0750 "$EVIDENCE_DIR"
umask 077
pwd -P > "$EVIDENCE_DIR/cwd.txt"
docker compose version > "$EVIDENCE_DIR/compose-version.txt"
printf '%s\n' \
  'docker compose -p miru-prod --env-file .release.env -f config/compose.production.yaml up -d' \
  > "$EVIDENCE_DIR/invocation.txt"
cp config/compose.production.yaml "$EVIDENCE_DIR/compose.production.yaml"

set +e
docker compose -p miru-prod --env-file .release.env \
  -f config/compose.production.yaml up -d \
  > "$EVIDENCE_DIR/compose-up.stdout-stderr.candidate.txt" 2>&1
UP_EXIT=$?
set -e
printf 'compose_up_exit=%s\n' "$UP_EXIT" > "$EVIDENCE_DIR/compose-up-exit.txt"

for attempt in $(seq 1 24); do
  API_ID="$(docker compose -p miru-prod --env-file .release.env \
    -f config/compose.production.yaml ps -q miru-api 2>/dev/null || true)"
  CADDY_ID="$(docker compose -p miru-prod --env-file .release.env \
    -f config/compose.production.yaml ps -q caddy 2>/dev/null || true)"
  API_HEALTH="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' \
    "$API_ID" 2>/dev/null || true)"
  CADDY_HEALTH="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' \
    "$CADDY_ID" 2>/dev/null || true)"
  [ "$API_HEALTH" = healthy ] && [ "$CADDY_HEALTH" = healthy ] && break
  sleep 5
done
```

Poll for at most 120 seconds without mutating the stack. Whether it succeeds or fails, capture
the following **before any `compose down`**:

```sh
set +e
docker compose -p miru-prod --env-file .release.env \
  -f config/compose.production.yaml ps -a --format json \
  > "$EVIDENCE_DIR/compose-ps.json"
PS_EXIT=$?
docker compose -p miru-prod --env-file .release.env \
  -f config/compose.production.yaml logs --no-color --timestamps --tail 200 \
  > "$EVIDENCE_DIR/startup-logs.candidate.txt" 2>&1
LOGS_EXIT=$?

for cid in $(docker compose -p miru-prod --env-file .release.env \
  -f config/compose.production.yaml ps -aq); do
  docker inspect --format \
    '{{json .Name}} {{json .Path}} {{json .Args}} {{json .State.Status}} {{json .State.ExitCode}} {{json .State.Error}} {{json .State.OOMKilled}} {{json .RestartCount}} {{json .State.Health.Status}}' \
    "$cid"
  docker inspect --format '{{json .State.Health.Log}}' "$cid"
done > "$EVIDENCE_DIR/container-state-health.txt"
INSPECT_EXIT=$?

sudo find /opt/miru/data -maxdepth 2 -printf '%P %y %u:%g %m %s\n' \
  > "$EVIDENCE_DIR/data-db-wal-shm-state.txt"
DATA_EXIT=$?
ss -lntup > "$EVIDENCE_DIR/listeners.txt"
LISTENER_EXIT=$?
set -e
printf 'ps_exit=%s\nlogs_exit=%s\ninspect_exit=%s\ndata_exit=%s\nlistener_exit=%s\n' \
  "$PS_EXIT" "$LOGS_EXIT" "$INSPECT_EXIT" "$DATA_EXIT" "$LISTENER_EXIT" \
  > "$EVIDENCE_DIR/capture-command-exits.txt"
```

Before promoting either candidate log to ordinary evidence, run a non-printing exact-value scan
using each Secret file as a fixed-string pattern source plus a credential-signature scan. Do not
use a command that prints a matching line:

```sh
LEAK=0
for candidate in \
  "$EVIDENCE_DIR/compose-up.stdout-stderr.candidate.txt" \
  "$EVIDENCE_DIR/startup-logs.candidate.txt"; do
  sudo grep -Fq -f /opt/miru/secrets/server_token "$candidate" && LEAK=1
  sudo grep -Fq -f /opt/miru/secrets/deepseek_api_key "$candidate" && LEAK=1
  grep -Eqi '(sk-[[:alnum:]_-]{16,}|Bearer[[:space:]]+[[:alnum:]._-]{16,})' "$candidate" && LEAK=1
done

if [ "$LEAK" -eq 0 ]; then
  mv "$EVIDENCE_DIR/compose-up.stdout-stderr.candidate.txt" \
    "$EVIDENCE_DIR/compose-up.stdout-stderr.txt"
  mv "$EVIDENCE_DIR/startup-logs.candidate.txt" \
    "$EVIDENCE_DIR/startup-logs.txt"
  printf 'secret_leak_detected=false\n' > "$EVIDENCE_DIR/secret-leak-scan.txt"
else
  NEW_BUILD_ID="$(basename "$(pwd -P)")"
  QUARANTINE="/opt/miru/logs/quarantine/$NEW_BUILD_ID-p4-r7"
  sudo install -d -o root -g root -m 0700 "$QUARANTINE"
  sudo mv "$EVIDENCE_DIR/compose-up.stdout-stderr.candidate.txt" \
    "$EVIDENCE_DIR/startup-logs.candidate.txt" "$QUARANTINE/"
  sudo chown root:root "$QUARANTINE"/*
  sudo chmod 0600 "$QUARANTINE"/*
  printf 'secret_leak_detected=true\n' > "$EVIDENCE_DIR/secret-leak-scan.txt"
fi
```

If a match is detected, the candidates remain root-only in quarantine and evidence records only
the boolean. Immediately follow the security containment path and require rotation; never copy
the matching bytes into tracked evidence or chat. Before sealing evidence, apply the same
non-printing exact-value and signature scans to every other textual evidence file.

On a healthy stack, additionally verify:

```sh
curl --fail --silent --show-error http://127.0.0.1:18080/healthz
curl --fail --silent --show-error http://127.0.0.1:18080/readyz
docker compose -p miru-prod --env-file .release.env \
  -f config/compose.production.yaml exec -T miru-api python -c \
  "import sqlite3; c=sqlite3.connect('/app/data/miru_server.db'); print('schema='+str(c.execute('pragma user_version').fetchone()[0])); print('integrity='+c.execute('pragma integrity_check').fetchone()[0])"
```

The schema check prints only version/integrity, never rows or environment. Re-run listener, UFW,
restart, OOM, health and ownership checks after health succeeds.

**Mutations:** Compose network and two containers; fresh DB/WAL, data log/attachment directories;
bounded value-free evidence. No Tailscale/public firewall/provider call.

**Verification:** actual API Path/Args show `/bin/sh` with `[-ec, one complete script]` during the
shell window or Python exec argv after replacement; API and Caddy healthy; zero restarts and no
OOM; `/healthz` and `/readyz` 200 through loopback Caddy; schema 2/integrity ok; owner 10001; API
has no host port; Caddy only `127.0.0.1:18080`; no Secret in log/evidence; no listener on public
80/443/8765/18080.

**PASS:** all verification items pass and the complete evidence set is sealed with hashes. Only
then may control return to the original runbook at P4-R8.

**FAIL:** nonzero/restart loop, unhealthy service, wrong argv, DB/migration/permission error,
missing health evidence, public bind, unexpected route/service, Secret leak, or incomplete
pre-containment capture.

**Rollback:** first capture all required evidence. Then run from the new release:

```sh
docker compose -p miru-prod --env-file .release.env \
  -f config/compose.production.yaml down
```

Never add `-v`. Verify zero containers/network, listeners and UFW. Atomically restore the recorded
`PREVIOUS_CURRENT`, but do not start that known-defective release. Preserve the new release,
images, evidence and all `/opt/miru/data` files offline and unchanged for diagnosis.

**Secret Risk:** critical. Never capture Config.Env/process environment, use verbose shell tracing,
print a leak match, or include values in curl/argv. Any detected leak requires containment and
rotation before another attempt.

**User Action Required:** approve the one startup. On failure, approve containment after evidence
capture; on Secret leak, rotate credentials through the separate human gate.

**STOP Conditions:** every FAIL condition; incomplete evidence is itself STOP. Do not “retry once”
and do not enter P4-R8.

### RM-R7 — Seal remediation result and hand back to the controlling runbook

**Objective:** record the immutable remediation outcome and either authorize P4-R8 or remain
contained.

**Preconditions:** RM-R6 reached a terminal PASS or completed failure containment.

**Read-only Checks:** hash evidence; verify no candidate/raw log containing a Secret is in tracked
evidence; repeat current/container/data/listener/UFW/Tailscale/image/release inventory.

**Commands:** write a value-free execution report with the old/new BUILD_ID relationship, manifest,
config/archive hashes, exact reused image IDs, stage matrix, deviations and rollback state.

**Mutations:** documentation/evidence only.

**Verification:** PASS report proves all RM stages; FAIL report proves containment and complete
pre-down evidence. No credential or private content is present.

**PASS:** `P4-R7 remediation release = PASS`; explicitly set `NEXT = original P4-R8`,
`AUTO-ENTER = NO`.

**FAIL:** evidence gap, state ambiguity, residual exposure or uncontained process.

**Rollback:** documentation has no runtime rollback; use RM-R6 rollback if runtime remains active.

**Secret Risk:** scan before saving/committing; remove or quarantine unsafe candidate files without
printing them.

**User Action Required:** review and accept the P4-R7 remediation execution report before P4-R8.

**STOP Conditions:** always STOP at the end of this stage. A later turn may begin P4-R8 only after
explicit acceptance of PASS.

## H. New P4-R7 Gate

The corrected Production startup is PASS only when every line below is proven:

```text
New immutable BUILD_ID and release directory = PASS
Corrected Compose SHA-256/bytes = PASS
Rendered Entrypoint = ["/bin/sh"]
Rendered Cmd = ["-ec", "<one complete script>"]
Actual Python process argv contains no Secret = PASS
Both Secret files readable/non-empty without disclosure = PASS
Miru image ID reused exactly = PASS
Caddy image ID reused exactly = PASS
Miru API healthy, restart count 0, OOMKilled false = PASS
Caddy healthy, dependency satisfied = PASS
Loopback /healthz = 200
Loopback /readyz = 200
SQLite schema = 2
SQLite integrity = ok
DB/WAL ownership = UID/GID 10001
API host-published port = NONE
Caddy host bind = 127.0.0.1:18080 only
UFW public business rule = NONE
Tailscale/Serve/Funnel = ABSENT/OFF
Secret in Compose/env_file/image/argv/Git/log/evidence = NO
Complete pre-containment evidence procedure = READY/PROVEN
P4-R7 remediation release = PASS
NEXT = original P4-R8
AUTO-ENTER = NO
```

Health alone is insufficient. A wrong public bind, missing evidence, nonzero restart count, Secret
leak or unexpected data state fails the gate even if `/healthz` returns 200.

## I. Rollback and Preservation Rules

If the new release fails:

1. Capture invocation, cwd, Compose file, container state, exit/Error/OOM/restart, health/logs,
   bounded stdout/stderr, DB/WAL/SHM, listeners and non-printing leak scan before containment.
2. Run `compose down` from the new release without `-v`; verify zero containers and no listener.
3. Atomically restore `current` to its recorded previous target for state rollback, while marking in
   the report that the previous target is the known-defective failed release and must not be
   started.
4. Preserve the new release directory and exact configs/evidence for diagnosis.
5. Preserve any newly created database, WAL, SHM, attachments and logs offline and unchanged.
   Do not delete, overwrite, migrate backward, copy a raw live DB, or reuse it for another attempt
   without a new plan. A first-start DB is evidence even if it contains no user conversation.
6. Preserve both old and new image tags, exact image IDs, all verified image tars and archives.
7. Preserve both Secret files unless leakage is detected. On leakage, contain first, then rotate
   server and provider credentials through a human gate; never delete evidence needed to establish
   scope, and never retain leaked bytes in tracked evidence.
8. Preserve the old failed release byte-for-byte. Never edit it to “make rollback work.”

Never delete or prune `/opt/miru/data`, `/opt/miru/secrets`, either release directory, Docker images,
image tars, evidence, backups, or unrelated host files during automatic rollback. Because the old
release is itself known defective, rollback restores containment and administrative identity, not
service availability.

## J. HANDOFF TO EXECUTION MODEL

### HANDOFF TO LUNA EXECUTION MODEL

Read, in order:

1. `docs/phase4-final-execution-runbook.md`
2. `docs/phase4-p4-r7-remediation-runbook.md`
3. `docs/evidence/phase4/p4-20260828-2053-194b844-1446158b/p4-r7-controlled-diagnostic-reproduction.txt`
4. The old source manifest, production hashes, image provenance, artifact manifest and release
   archive hash in the same evidence directory.

Then obey these rules:

1. You are an Execution Model for this overlay, not an architecture redesign model.
2. Execute only RM-R0 through RM-R7, exactly one stage at a time. Report `CHECK`, `EXECUTE`,
   `VERIFY`, `PASS/FAIL`, then STOP on every gate requiring approval.
3. The only authorized repository configuration change is the exact C.1 fragment in
   `deploy/production/compose.production.yaml`. Do not modify source, settings or Caddyfile.
4. Do not rebuild Miru and do not run `docker save`. Reuse only the exact proven Image ID; a byte
   drift is STOP, not permission to rebuild automatically.
5. Derive a new manifest v2 and BUILD_ID. Never reuse the failed BUILD_ID for changed content and
   never mutate the failed release directory/archive.
6. Use the actual release invocation with `-f config/compose.production.yaml`. Record the original
   root-level invocation discrepancy as documentation deviation, never as root cause.
7. Inherit the existing Secrets. Do not display, hash, recreate or rotate them unless leakage or
   invalidity is proven. Never request a Secret in chat.
8. Before the new P4-R7, prove rendered argv structurally. A human visual reading of YAML is not
   sufficient.
9. If startup fails, capture the complete H/RM-R6 evidence set before `compose down`. Never use
   `-v`, never retry automatically and never delete DB/WAL/SHM.
10. Keep Tailscale absent and public business ports closed throughout this overlay.
11. On RM-R6 PASS, write the report and STOP. Do not start P4-R8 automatically.

### Final planning decision

```text
root cause confirmed = YES
architecture change required = NO
remediation ready for execution = YES
new release required = YES
source code change required = NO
Miru image rebuild required = NO
Secrets rotation required = NO
Phase 4 frozen architecture preserved = YES

STOP
```
