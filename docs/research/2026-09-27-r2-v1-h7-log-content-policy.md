# R2 V1 H7 — non-credential content in application logs

Date: 2026-09-27. Base: `feat/r2-m7e-v1-lineage` at `1f287029`. This is research
only; no decision has been taken. License analysis is out of scope.

Question: after central credential redaction (`RedactingFormatter`, `5b99f85d`),
should routine application logs still carry prompt excerpts, raw model output and
local file paths?

## 1. Internal sources

| Source | What it requires |
|---|---|
| Frozen H7 (`docs/r2/R2_05_FROZEN_HOST_HARDENING_REQUIREMENTS.md`, H7) | "Secrets must be redacted." Nothing on non-secret content. |
| Threat model, invariant 9 (`docs/security/threat-model.md`) | Secrets must not be "included in routine logs". Server logs and exception traces are listed as protected assets (4.3). |
| ADR-0052 (accepted) | Failure observations mask only values usable to impersonate or charge (API key, token, cookie, password, signed-URL parameters). They keep paths, exception type, cause chain and stack untruncated, and do not proactively copy prompts or normal output. |
| M7 spec §9 | The allowlist excludes raw content, credentials, auth headers, signed URLs, provider bodies, absolute local paths, email and user ID. Canary tests "scan application logs, exported spans and durable public event payloads". |
| M7-D plan D2 (written before ADR-0089/0090) | Put canaries in credentials, prompt, URL, headers, provider body and filesystem path; "assert absence from logs, in-memory OTLP export, baggage and public event rows". |
| ADR-0090 | Silent on log content. |

The sources disagree. The frozen requirement, the threat model and ADR-0052 draw
the line at **secrets**. The M7 spec and plan D2 also put **prompt and path**
out of logs.

## 2. External primary sources

- **OWASP Logging Cheat Sheet.** The "Data to exclude" list covers access
  tokens, passwords, connection strings, encryption keys, sensitive PII,
  commercially-sensitive information, and data above the log store's
  classification. It says such data should be removed, masked, sanitized,
  hashed or encrypted. File paths are named among data that "may require
  special manner" because they are useful for investigation.
- **OpenTelemetry GenAI semantic conventions** (repo `semantic-conventions-genai`
  @ `e57c543b`).
  - `gen_ai.input.messages` / `gen_ai.output.messages` are **Opt-In**; they
    are "likely to contain sensitive information including user/PII data".
  - For comparable content attributes, instrumentations "SHOULD NOT capture
    this attribute by default. Capture SHOULD be gated by an explicit user
    opt-in, for example `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`".
  - `exception.message` "may contain sensitive information".

## 3. Current state (facts, counted in the source at `1f287029`)

- **Prompt excerpts.** Request-body logs in about 13 provider modules use
  `safe_body_for_log`-style views, and these views keep prompt excerpts (up to
  120 characters).
- **Raw model output.** 8 call sites log truncated raw model output via
  `truncate_for_log` in structured-output fallback warnings.
- **Paths.** About 66 log calls mention paths or files; many are absolute
  local paths.
- **Terminal task failure.** Logs now carry frames and exception type without
  messages (`0e37b517`). The full reason is still stored durably in
  `tasks.error_message`, which is shown to the operator.
- **Credentials.** Every handler masks them (`RedactingFormatter`).
- **Spans.** Allowlist-enforced; they carry no content.

## 4. Inferences

- Prompts and model output are user or commercial content. Neither OWASP nor
  OTel treats them as secrets; both treat them as sensitive and default-off or
  special-handling.
- Paths are operationally valuable. OWASP asks for "special manner", not
  exclusion. Paths under the data root reveal the project and resource names
  that the operator already controls.
- Removing messages from terminal-failure logs does not lose evidence, because
  `tasks.error_message` keeps the detail. It does make the logs alone less
  useful, which cuts against ADR-0052's evidence-preservation spirit.

## 5. Unknowns

- Who reads the logs in the target deployment, and whether logs are shipped
  off-host. Log retention.
- Whether the sponsor treats scripts/prompts as confidential for this product.

## 6. Options

| Option | Prompts / model output in logs | Paths | Terminal-failure messages | Fit |
|---|---|---|---|---|
| A. Secrets-only | Kept (excerpt) | Kept | Restore messages (credentials masked centrally) | Frozen H7, threat model, ADR-0052. Supersedes the D2 prompt/path log canary. |
| B. Content opt-in | Default off: replace with length + digest; env opt-in (e.g. `ARCREEL_LOG_CONTENT=1`) restores excerpts | Kept | Stay message-free (detail in `tasks.error_message`) | OTel GenAI opt-in pattern. D2 prompt canary passes by default; path canary is dropped. |
| C. Full D2 | Removed | Relativized to the data root or removed | Message-free | Strictest; the most edits across about 90 sites; the most debugging cost. |

## 7. Decision (from precedent)

No entry in `R2_04_DECISION_REGISTRY.json`, the consolidated decision log or
the open decisions touches log content. The most specific accepted authority
is ADR-0052. It masks only values usable to impersonate or charge; it keeps
received failure objects (paths, exception type, cause chain, stack); and it
does not proactively copy prompts or normal output. OTel GenAI (content is
opt-in) and OWASP (sensitive data is masked; paths get special handling)
agree with it. The open question therefore resolves to option B, aligned with
ADR-0052:

1. **Proactive content copies are off by default.** These are prompt excerpts
   in provider request-body logs and raw model output in structured-output
   fallback warnings. Each is replaced by its length and a short SHA-256
   digest. An explicit operator opt-in (`ARCREEL_LOG_GENERATION_CONTENT=1`,
   modelled on `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`) restores
   the excerpts for debugging.
2. **Paths stay in logs.** They are operator-controlled locations and are
   never exported.
3. **Received failure objects stay in logs with credentials masked.** This
   covers exception messages and tracebacks. `RedactingFormatter` masks the
   credentials, and the message-free terminal-failure formatting from
   `0e37b517` is reverted to match ADR-0052.
4. **Spans are unchanged.** The strict allowlist stays; no content, paths or
   exception messages go on spans.
5. **Plan D2's prompt/path log canary is superseded for V1.** The end-to-end
   test keeps credential, URL-signature, header and provider-job-ID canaries
   out of logs, keeps every canary out of spans and public events, and keeps
   prompt canaries out of the default-off request-body logs.
