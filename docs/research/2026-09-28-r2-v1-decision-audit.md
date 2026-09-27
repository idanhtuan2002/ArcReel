# R2 V1 — audit of recent decisions against existing documents

Date: 2026-09-28. Branch `feat/r2-m7e-v1-lineage` at `258129eb`. The sponsor
asked for the existing documents to be reviewed, and for this session's
decisions and recommendations to be re-checked for accuracy. This note
records each check, what the source says, and the verdict. License is out of
scope.

**Documents reviewed:**

- ADR-0071, ADR-0078, ADR-0089 and ADR-0090;
- `R2_05_FROZEN_HOST_HARDENING_REQUIREMENTS.md` §7–§8;
- `R2_04_OPEN_DECISIONS.md` R2-OPEN-004;
- `R2_V1_PRODUCTION_RELEASE_STRATEGY.md`;
- `R2_V1_DELIVERY_BACKLOG_2026-09-26.md`;
- the M7 host-hardening spec §2, §10–§12 and the M7-E plan;
- `2026-09-17-r2-v1-production-readiness-v2-deferment.md`;
- `2026-09-25-r2-m7-h6-h8-primary-source-notes.md`;
- the E1 schemas and code.

## Summary

| # | Decision or claim | Verdict |
|---|---|---|
| 1 | ADR-0090 O2a: the export is downloaded through `GET /files/{project}/output/<file>` | **Incorrect. Correction proposed.** |
| 2 | ADR-0090 O2a: Gate C approves the composed final; the export is a byte-exact copy in `output/`; Gate D's digest is checked | Correct |
| 3 | V1-05 accepted | Correct, and unaffected by the #1 correction |
| 4 | R3 = T1 (operator attestation plus runner-generated evidence) | Correct |
| 5 | R4 = U3 (pin the base and backport a selected set) | Correct; two details corrected |
| 6 | Severity of the eight upstream-fixed defects | **Overstated. Corrected.** |
| 7 | R2 F1: "one small canary call qualifies a route" | **Incomplete. Corrected.** |
| 8 | R2 F2: enable routes without a canary | **Conflicts with a V1 non-promise.** |
| 9 | "No automatic retry on an ambiguous outcome" as a new invariant | It is already decided (ADR-0078) |
| 10 | F1 stores qualification in deployment state | Allowed only inside the single CapabilityRegistry |

## Details

### 1. The O2a download route is incorrect

- **ADR-0071** (accepted): "静态媒体维持匿名可读，是有意决策" (static media stay
  anonymously readable, by design), and "导出下载维持下载 token，它是自带认证端点如今唯一的凭证形态"
  (export downloads keep the download token, which is now the only
  credential form of the self-authenticated endpoints). An export is
  therefore a download-token route, not the anonymous media route.
- **Upstream `c1cf1c62`** is in the U3 backport set. It restricts
  `/files/{project}/{path}` to `PUBLIC_MEDIA_DIRS`: storyboards, end_frames,
  videos, reference_videos, thumbnails, characters, scenes, props, products,
  grids, audio, plus their `versions/` buckets. **`output/` is not in the
  list.** After the backport, the route O2a names returns 404.
- **Correction.** The operator obtains the export through the existing
  download-token export surface:
  - the project ZIP (`POST /projects/{name}/export/token`, then
    `GET /projects/{name}/export`), which already includes `output/`;
  - or a single-file export endpoint under the same download-token
    mechanism, which is a V1-07 design choice.

  The export digest remains the sha256 of the served bytes. The rest of O2a
  is unchanged.
- **Status.** ADR-0090 records O2a as sponsor-accepted, so the fix awaits
  sponsor confirmation.

### 2. O2a's core is correct

It is consistent with:

- the CONTEXT.md Gate C glossary ("selected master/export candidate");
- ADR-0089 decisions 1, 3, 4 and 5;
- the P1 spec §8 note that Gate D's binding must be revisited when a
  distinct export step exists.

### 3. V1-05 acceptance is unaffected

The V1-05 recovery evidence does not depend on the download route. The drill
read the restored files directly.

### 4. R3 = T1 is correct

- **The spec's failure conditions.** M7 spec §11 says: "A zero-test
  selection, required skip, dirty evidence HEAD or historical green run is a
  failure". ADR-0078 says: "A clean merge or green unit suite alone is not
  compatibility evidence". T1's runner-generated, log-parsed evidence
  implements these conditions directly.
- **The trust model.** ADR-0090 already took the operator-attestation trust
  model. The SLSA v1.0 levels confirm that a workstation signature stays at
  L1.

### 5. R4 = U3 is correct; two details are corrected

- **No E1 schema change is needed.** Addendum 2 said a selective backport
  needs one. It does not.
  - The current schema already takes a full ordered `old_sha..new_sha`
    inventory in which each commit carries `UNCHANGED | ADAPTED | DEFERRED |
    REJECTED`.
  - A U3 report inventories the whole upstream range: selected commits are
    `UNCHANGED` (clean pick) or `ADAPTED`, and all others are `DEFERRED`.
  - The real E1 gap stays S1: the verifier must prove that each `UNCHANGED`
    or `ADAPTED` commit is actually present in the host range.
- **The candidate report's gate set is large, and V1-08 needs it anyway.**
  Spec §10 requires a migration rehearsal on a restored snapshot, full
  gates, H1–H8, a Golden no-provider restore smoke and browser evidence.
  The backport candidate therefore passes the same gates as the release
  candidate.
- **U2's cost stands.** The data-root relocation and the Vertex credential
  move would break ADR-0090's credential exclusion. There would be two
  Alembic heads, which is a §12 stop condition. The `cancelling` status
  would be retired against M7-C.

### 6. Defect severities, corrected

- **Context.** ADR-0071 states the threat model: one self-hosted
  administrator, with no attacker reading media without authorization.
- **Downgraded: the anonymous `/files` read.** Its scope violation remains:
  `project.json` and source/script text are not "static media", so they fall
  outside ADR-0071's anonymous scope. It is **medium**, not high.
- **Downgraded: `GET /custom-providers/{id}/credentials`.** It requires a
  session (`CurrentUser`). The risk is key exposure to the browser, not
  anonymous access, so it is **medium**.
- **Medium:**
  - the download token accepted as a session token (5-minute window, but
    the token appears in URLs);
  - the outbound destination and byte-cap gaps (provider-controlled URLs
    can reach link-local and metadata addresses);
  - body forwarding on cross-origin 307/308 redirects.
- **Low for a single operator:**
  - the cancel/retry scope-query gaps (a multi-user concern);
  - snapshot-path validation (it needs a tampered `versions.json`).
- **Effect on U3.** None: all remain real defects with upstream fixes.

### 7. F1 needs more than one canary call

The frozen requirements §7 profile covers submit, status/poll, restart
resume, cancellation, rate limiting, cost capture, reference semantics,
first/last frame support, error redaction, timeout/retry and capability
metadata. A single live call cannot show restart, cancel or timeout
behaviour. Corrected F1 has two parts:

- **Adapter-level offline qualification, shipped with the release.** It
  runs per adapter version with controllable fakes, as M7 H1–H5 already do,
  and covers restart, cancel, timeout/ambiguity and redaction. At most it
  yields `OFFLINE_VERIFIED`.
- **A route-level live canary at runtime.** It is per exact
  provider/endpoint/model/account and is run by the operator. It shows
  exact-version submit, poll, result retrieval and cost capture, and
  promotes the route to `QUALIFIED` with an expiry.

A route is `QUALIFIED` only when both hold for the running adapter version.

### 8. F2 conflicts with a V1 non-promise

The V1 readiness research §4 lists "provider-agnostic production claims" as a
V1 non-promise. Strategy §4 lists "provider-agnostic execution". Enabling
routes that are not qualified would amount to that claim.

F1 keeps the non-promise. Any provider *can* be qualified, but V1 claims only
the routes that are qualified. F2 would need the non-promise itself amended,
not only strategy §5/§6.

### 9. At most once on ambiguous outcomes is an existing decision

ADR-0078:

- "Adapters without a proved idempotency or lookup capability may not
  automatically resubmit an ambiguous attempt";
- "Automatic retry for providers without proved native idempotency or
  lookup was rejected because it can create duplicate remote work and
  duplicate charges".

The synchronous timeout retries in `lib/retry.py` on paid image and text
calls are therefore a **conformance gap against an accepted ADR**, not a new
policy choice.

### 10. F1 storage

- R2-OPEN-004 says that "CapabilityRegistry is sole business-facing
  catalog". Runtime qualification records must be part of that one
  registry. Static adapter profiles in the repository and runtime route
  qualifications should be read through one registry API, not a parallel
  store.
- The V1 readiness research §5 P1.8 says the V1 tag carries "qualified
  provider configuration references (not secrets)". Under F1, the tag
  records the routes qualified at tagging time. Later runtime
  qualifications are operational records, not part of the tagged release.

## Actions

**Corrections applied without a sponsor decision.** In the V1-06 research
note:

- Addendum 2: severity grading, and no schema change needed;
- Addendum 3: F1's two-level qualification;
- F2's conflict with the non-promise;
- the ADR-0078 conformance framing;
- the registry constraint.

**Awaiting the sponsor:**

- the ADR-0090 O2a download-route correction (#1);
- the R2 choice, now presented with the corrected F1 and F2.
