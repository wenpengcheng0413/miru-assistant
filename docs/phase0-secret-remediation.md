# Miru Cloud + Home Node — Phase 0.1A Secret Remediation Planning

**Scope:** Secret Gate only. Phase 1 was not started.  
**Audit date:** 2026-08-28 (Asia/Shanghai)  
**Source files inspected:**

- `products/daily-report/config/settings.yaml`
- `products/mobile-assistant/server/config/settings.yaml`
- Corresponding `settings.example.yaml` files and `products/mobile-assistant/server/.env.example`
- Secret-related loaders, README guidance, bootstrap, notifier, and server configuration code

> This document contains field names and classifications only. It contains no Secret Value, prefix/suffix, hash, Base64 representation, YAML sensitive line, database content, chat content, or provider response.

## 1. Executive Summary

The two active local YAML files were found to contain **four literal credential field instances** at the start of Phase 0.1B. They have now been migrated without emitting their values:

1. Daily Report DeepSeek API credential.
2. Daily Report PushPlus provider token.
3. Mobile Assistant server/application token.
4. Mobile Assistant DeepSeek API credential.

The two DeepSeek fields compared equal in memory during the migration, so they represented one credential duplicated in two configuration locations. No value was retained, emitted, hashed, or copied to a file.

The Mobile Assistant MiniMax API key and MiniMax group ID already use environment-variable references. MiniMax is configured as the TTS primary provider, but the loader and service construction succeed without its variables; normal text chat does not depend on TTS. It is therefore an **OPTIONAL** capability for the Phase 0 Secret Gate, not a required blocker.

**Secret Gate result: PASSED.** The four literal fields were replaced with environment references, three required current-user environment variables are non-empty, and value-free re-audit found zero literal credentials. DeepSeek and PushPlus rotation remains recommended before public cloud exposure; no provider rotation or API call was performed.

## 2. Sensitive Field Inventory

Only the requested inventory fields are shown; no values are shown.

| File | Field name | Classification | Current storage form | Recommended environment variable | Rotation required | Reason |
|---|---|---|---|---|---|---|
| `products/daily-report/config/settings.yaml` | `miru.llm.api_key` | API_CREDENTIAL | env_reference | `MIRU_DEEPSEEK_API_KEY` | RECOMMENDED BEFORE PUBLIC CLOUD EXPOSURE | DeepSeek provider credential is now environment-backed; it was previously duplicated as a literal with Mobile Assistant. |
| `products/daily-report/config/settings.yaml` | `miru.notifiers[0].token` | API_CREDENTIAL | env_reference | `MIRU_PUSHPLUS_TOKEN` | RECOMMENDED BEFORE PUBLIC CLOUD EXPOSURE | PushPlus provider token is now environment-backed; no provider rotation was executed. |
| `products/mobile-assistant/server/config/settings.yaml` | `server.token` | APPLICATION_TOKEN | env_reference | `MIRU_SERVER_TOKEN` | NO — NEW TOKEN GENERATED | New high-entropy application token was generated locally and placed in the current-user environment; it is not a third-party credential. |
| `products/mobile-assistant/server/config/settings.yaml` | `llm.api_key` | API_CREDENTIAL | env_reference | `MIRU_DEEPSEEK_API_KEY` | RECOMMENDED BEFORE PUBLIC CLOUD EXPOSURE | DeepSeek provider credential is now environment-backed and shares one user-level source with Daily Report. |
| `products/mobile-assistant/server/config/settings.yaml` | `tts.minimax.api_key` | API_CREDENTIAL | env_reference | `MINIMAX_API_KEY` | NO — MIGRATE ONLY | Already references the provider credential through the environment resolver; rotate only if the owner believes it was exposed. |
| `products/mobile-assistant/server/config/settings.yaml` | `tts.minimax.group_id` | IDENTIFIER | env_reference | `MINIMAX_GROUP_ID` | NO | MiniMax account/group identifier, not a credential. |

No `DASHSCOPE_API_KEY` field was found in either target YAML. It is present in the Mobile Assistant `.env.example` template only and is not consumed by the inspected target configuration path.

## 3. Environment Variable Mapping

### Loader behavior confirmed from source

#### Mobile Assistant

`products/mobile-assistant/server/miru_server/config.py`:

- Loads YAML with `yaml.safe_load`.
- Recursively substitutes `${ENV_VAR}` in strings using `os.environ`.
- A missing variable becomes an empty string.
- `MIRU_SERVER_CONFIG` selects the YAML file path; it is not a field-level secret override.
- There is no observed `load_dotenv` call in the Mobile Assistant server. `.env.example` is a template; a launcher or user/process environment must actually provide variables.

**Precedence:** YAML is loaded first, then environment references inside YAML are substituted. A YAML literal therefore remains authoritative for that field; setting an environment variable does not override an unrelated literal field.

#### Daily Report

`products/daily-report/src/miru/utils/config.py`:

- Loads YAML with `yaml.safe_load`.
- Recursively substitutes `${ENV_VAR}` and `${ENV_VAR:default}`.
- A missing variable without a default becomes an empty string.
- Sensitive models use `SecretStr` after substitution.
- No automatic `.env` loading was observed.

**Precedence:** YAML is loaded first, then `${...}` references are replaced. A literal YAML credential is not overridden by an environment variable with the same conceptual name.

### Mapping confirmation

| Environment variable | Current source support | Current target usage | Notes |
|---|---|---|---|
| `MIRU_DEEPSEEK_API_KEY` | Yes, through generic `${...}` substitution in both loaders | Both active DeepSeek fields now reference it | Migration complete; provider rotation remains recommended before public exposure. |
| `MINIMAX_API_KEY` | Yes, through Mobile generic substitution | Active Mobile TTS field already references it | No field-level YAML override exists after substitution. |
| `MINIMAX_GROUP_ID` | Yes, through Mobile generic substitution | Active Mobile TTS group ID already references it | Identifier only; no rotation. |
| `MIRU_SERVER_TOKEN` | Yes, through Mobile generic substitution; startup reads the resolved server token | Active Mobile server token now references it | New token generated and stored at current-user scope; value-free loader resolution passed. |
| `DASHSCOPE_API_KEY` | Not observed in target YAML or Python provider path; only template presence | Not currently consumed by these target files | Do not treat template presence as proof of an active credential. Wire intentionally in a later change or remove from the active profile. |
| `MIRU_PUSHPLUS_TOKEN` | Yes, through Daily generic substitution; example and notifier path support it | Active notifier field now references it | Migration complete; provider rotation remains recommended before public exposure. |

`DASHSCOPE_API_KEY` remains template-only in the inspected scope and is not an active dependency of either target configuration.

## 4. Rotation Matrix

| Component | Field | Type | Current Form | Future Source | Rotate? | Manual Action |
|---|---|---|---|---|---|---|
| Daily Report LLM | `miru.llm.api_key` | API_CREDENTIAL | env_reference | `MIRU_DEEPSEEK_API_KEY` | RECOMMENDED BEFORE PUBLIC CLOUD EXPOSURE | If desired, create a replacement credential in the DeepSeek console and revoke the old one; migration itself is complete. |
| Mobile Assistant LLM | `llm.api_key` | API_CREDENTIAL | env_reference | `MIRU_DEEPSEEK_API_KEY` | RECOMMENDED BEFORE PUBLIC CLOUD EXPOSURE | Uses the same user-level source; no second literal copy remains. |
| Daily Report notifier | `miru.notifiers[0].token` | API_CREDENTIAL | env_reference | `MIRU_PUSHPLUS_TOKEN` | RECOMMENDED BEFORE PUBLIC CLOUD EXPOSURE | If desired, create a replacement PushPlus token and revoke the old one; migration itself is complete. |
| Mobile Assistant server auth | `server.token` | APPLICATION_TOKEN | env_reference | `MIRU_SERVER_TOKEN` | NO — NEW TOKEN GENERATED | A new high-entropy application token was generated locally without printing or persisting it to a file. |
| Mobile Assistant MiniMax TTS | `tts.minimax.api_key` | API_CREDENTIAL | env_reference | `MINIMAX_API_KEY` | NO — MIGRATE ONLY | Keep the environment reference; rotate in the MiniMax console only if exposure is confirmed or required by provider policy. |
| Mobile Assistant MiniMax account | `tts.minimax.group_id` | IDENTIFIER | env_reference | `MINIMAX_GROUP_ID` | NO | Keep as an environment-backed identifier; changing it is an account/configuration action, not Secret rotation. |

The matrix treats literal API keys, provider access tokens, and application bearer tokens as `ROTATE` by default. Identifiers, endpoints, and model names are not rotated merely because their key names look sensitive.

## 5. Duplicate Secret Storage

- **DeepSeek:** one credential was duplicated before migration. Both fields now use `MIRU_DEEPSEEK_API_KEY`; no literal copy remains. Rotation is recommended before public cloud exposure.
- **PushPlus:** one provider token was present before migration and now uses `MIRU_PUSHPLUS_TOKEN`. Rotation is recommended before public cloud exposure.
- **Miru server token:** the former literal was replaced by a newly generated high-entropy token in `MIRU_SERVER_TOKEN`.
- **MiniMax:** the active Mobile Assistant TTS API key and group ID are environment references. No second literal copy was found in the target files.
- **DashScope:** only a template variable name was found in the inspected target scope; no active target field was found.

## 6. Windows Secret Storage Recommendation

### A. User-level environment variables

**Fit:** best Phase 0/1 minimum-change option.

- Works with the current loaders because both call `os.environ` during `${...}` resolution.
- Keeps values out of YAML and Git.
- Does not require a dependency upgrade or source change.
- Values remain accessible to processes running as the same Windows user; protect the account and avoid printing the environment.

### B. Git-ignored `.env`

**Fit:** only if the launcher explicitly loads it.

- The inspected Python code does not call `load_dotenv`; `.env.example` alone does not make `.env` effective.
- A future launcher may load an ignored `.env`, but that adds process/launcher behavior to verify.
- It is easier to accidentally copy, archive, or expose than a user-level secret store.

### C. Windows Credential Manager / DPAPI

**Fit:** preferred Home Node formal solution.

- Provides OS-protected storage and avoids long-lived plaintext configuration files.
- Requires a small launcher/secret-provider adapter and an explicit fallback/error policy.
- Appropriate for Home Node RPC credentials, node identity, WeChat integration secrets, and local provider credentials that must remain on Windows.

### Recommendation

**Phase 0/1 minimum:** user-level environment migration is complete. Keep using the existing `${ENV_VAR}` references and do not assume `.env` is loaded automatically. Provider rotation remains a pre-public-exposure security task.  
**Home Node formal:** use Windows Credential Manager/DPAPI for node-local secrets, inject only the needed values into the running process, and keep WeChat keys/raw data local. The cloud should receive only bounded RPC results and status.

## 7. Manual User Actions

The following are planning instructions only; none was executed:

1. Before public cloud exposure, optionally rotate the DeepSeek API credential and revoke the old credential.
2. Before public cloud exposure, optionally rotate the PushPlus provider token and revoke the old token.
3. The new Miru Server Token has already been generated locally and stored only as `MIRU_SERVER_TOKEN` at current-user scope.
4. Keep the four migrated YAML fields as `${ENV_VAR}` references; do not paste values into this document or Git.
5. Keep ignored local configuration files out of commits, archives, screenshots, and support bundles.

## 8. Re-audit Procedure

Run only after the owner completes the manual actions:

1. Stop local Miru/Daily Report processes before checking configuration.
2. Run a value-free scanner over the two target YAML files. It must emit field name, classification, and form only; never emit a value, prefix/suffix, hash, or encoded representation.
3. Confirm all credential fields are `env_reference` (or `empty` when intentionally disabled), and that no `literal` credential remains.
4. Confirm the expected environment-variable names are present in the process/user environment without printing their values.
5. Confirm `git ls-files` contains only example/template files for these settings and that `git grep`/reachable-history scans contain no provider-token signatures.
6. Confirm the DeepSeek field is represented once as a shared environment source rather than two literal copies.
7. Confirm no provider login, API call, key validation, or external upload is needed for this audit.
8. Update the Phase 0 report Secret Gate after all checks pass. If any literal credential or unknown sensitive value reappears, keep the gate `BLOCKED`.

## 9. Phase 0 Secret Gate Acceptance Criteria

- [x] No literal API credential remains in either target `settings.yaml`.
- [x] No literal application token remains in either target `settings.yaml`.
- [x] Daily Report DeepSeek field maps to `MIRU_DEEPSEEK_API_KEY`.
- [x] Mobile Assistant DeepSeek field maps to `MIRU_DEEPSEEK_API_KEY`.
- [x] Daily Report PushPlus field maps to `MIRU_PUSHPLUS_TOKEN`.
- [x] Mobile Assistant server token maps to `MIRU_SERVER_TOKEN`.
- [x] Mobile MiniMax API key and group ID are already environment references.
- [x] Group ID is classified as an identifier, not a credential.
- [x] Loader precedence and `${ENV_VAR}` support are documented.
- [x] No provider validation, key creation, revocation, or source/config mutation was performed in this subphase.
- [x] No Secret Value, hash, Base64 form, or sensitive YAML line is present in this document.
- [x] Value-free re-audit passes after migration; provider rotation remains optional until public cloud exposure.

### Current gate state

```text
PASSED
```

Migration result: zero literal credential fields remain. Three required current-user environment variables are non-empty; MiniMax remains an optional TTS provider and is not a Secret Gate blocker. DeepSeek and PushPlus rotation are recorded as `RECOMMENDED BEFORE PUBLIC CLOUD EXPOSURE`.
