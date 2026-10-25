# R2 M10 research — quality evidence before product packaging

Date: 2026-09-16

Repository snapshot: `d42e9a49a8f47deee725e7153a74ece1204f3e14`

Role: research input for a future M10 ADR, design specification and execution
plan; not an acceptance record and not implementation authority.

## 1. Question and boundary

M10 must close the production-quality gap without turning a probe, model,
reviewer or export directory into Final Cut authority. This research asks:

1. what a versioned `QualityProfile`, typed multi-assessor `QualityRun` and
   authority-issued `QualityDisposition` must bind;
2. which deterministic local diagnostics can produce evidence, and where their
   validity stops;
3. when full-reference perceptual regression is meaningful;
4. how accessibility, factual, narrative, continuity, perceptual and Human
   review can remain distinct rather than becoming one score;
5. how a later `PackagingCandidate` and deterministic export bundle can reuse
   M8 mechanics without acquiring Production or network-publishing authority;
6. which predecessor evidence must exist before M10 implementation.

The bounded product surface is export-only video packaging. Upload, account
selection, scheduling, moderation, provider processing, public visibility and
all other network effects belong to M11. This document performs no provider
operation and proposes no M10 implementation.

## 2. Evidence method and confidence

Evidence was checked in this order:

- accepted local decisions and current Git/evidence state;
- current host source, including real `ffprobe` callers and the existing
  Production Approval service;
- exact pinned donor revisions and selected executable surfaces;
- primary specifications and first-party tool/platform documentation.

Local code discovery used the indexed `home-anhtuan-content-production-os`
graph at generation `2026-09-16T06:18:20Z`, then exact source reads. Coverage
was clean-best-effort for `lib/audio_utils.py`,
`r2/production/approval_service.py`, ADR-0080 and the north-star research. The
graph's inbound-call result for `_run_ffprobe` was heuristic, so call-site
claims below come from direct source search. This is a task-bounded inspection,
not proof that no quality-related helper exists anywhere outside the inspected
repository and donor surfaces.

The terms used below are deliberate:

- **Fact** — directly supported by an accepted record, inspected source or
  primary external source.
- **Inference** — a design consequence derived from the facts; it still needs
  ADR/design acceptance.
- **Unknown** — evidence or policy that is not fixed by the current checkout.

## 3. Facts — authority and live prerequisite state

### 3.1 Accepted post-M8 ownership

ADR-0080 is accepted. It assigns M10 ownership of a versioned
`QualityProfile`, typed multi-assessor `QualityRun`, authority-issued quality
disposition, immutable `PackagingCandidate` revisions and deterministic export
bundles. It permits reuse of M8 revision/promotion mechanics, M7
execution/receipt mechanics and the host's secure FFmpeg subprocess pattern,
but explicitly withholds external publishing side effects
([ADR-0080:42-47](../adr/0080-post-m8-north-star-closed-loop.md)).

The same accepted record fixes the authority separation:

- probes return typed evidence and do not decide Final Cut;
- existing Production Authority selects the `ApprovedMaster`;
- a Human Final Cut custodian issues `PASS`, `REWORK` or `WAIVE` and binds exact
  user/project, master/artifact, profile, complete run and assessed-subject
  closure;
- `WAIVE` is reasoned and time-bounded;
- changed subject/profile/run, expiry or supersession invalidates readiness;
- packaging selection cannot replace the `ApprovedMaster` or target an M8
  `ARTIFACT_SLOT`.

These are accepted constraints, not options for the M10 ADR
([ADR-0080:80-117](../adr/0080-post-m8-north-star-closed-loop.md)).

### 3.2 M8 mechanics are designed, not available implementation

ADR-0079 is accepted and specifies immutable candidate revisions,
preview-bound promotion, exact payload/parent/scope revalidation and a single
Production Authority path to `ApprovedMaster`
([ADR-0079:7-34](../adr/0079-m8-integrated-exploration-learning-format-kernel.md)).
It also states that the ADR authorizes planning, not implementation
([ADR-0079:84-97](../adr/0079-m8-integrated-exploration-learning-format-kernel.md)).

The live M8 execution contract remains
`DESIGN_READY_M7_IMPLEMENTATION_PENDING`, forbids implementation on the design
branch and requires independently accepted M7 evidence before M8-A
([M8 execution contract:1-24](../r2/evidence/R2_M8_EXECUTION_CONTRACT_2026-09-13.json)).
The untracked `R2_M8_STOP.json` records a historical/current-worktree stop, not
accepted M8 implementation evidence. No tracked
`R2_M8_IMPLEMENTATION_ACCEPTANCE.json` exists in the inspected checkout.

**Fact:** M10 may design an additive M8 schema evolution, but must not import or
call a planned M8 Python interface as though it were implemented. Its
implementation preflight must resolve the actual accepted M8 symbols, schemas,
migrations and transaction behavior at that future base HEAD.

### 3.3 M9 is not accepted

ADR-0081 is still `proposed`; the design acceptance contract exists, but the
acceptance record does not. ADR-0080 normatively orders M9 before M10 and says a
later milestone starts only after the preceding milestone's required evidence
and independent review are accepted
([ADR-0080:72-76](../adr/0080-post-m8-north-star-closed-loop.md)).

**Fact:** research, ADR and planning for M10 are allowed by the accepted
post-M8 architecture. M10 implementation is not eligible from this HEAD.

### 3.4 Current host seams are narrower than M10

The current `QualityReport` contains free-form check names, one optional score,
blocking/advisory findings, one `ReviewerType` and a timestamp. It does not bind
a profile revision/digest, exact artifact digest, tool/model/config/reference,
observation closure, assessor independence, freshness or a disposition
([`r2/contracts/results.py:46-68`](../../r2/contracts/results.py)). It can remain
a legacy/generation report, but it is not sufficient as M10 authority evidence.

`ProductionApprovalService.promote()` loads current artifact metadata, checks
candidate state/target/content fingerprint, and records the selected candidate
as `ApprovedMasterMetadata` through the host bridge
([`r2/production/approval_service.py:22-77`](../../r2/production/approval_service.py)).
M10 must consume the exact selected master; it must not add a competing master
selection route.

The host's `_run_ffprobe()` uses `asyncio.create_subprocess_exec` without a
shell, restricts protocols to local `file`, imposes a timeout, kills the child
on timeout and treats non-zero exit as failure
([`lib/audio_utils.py:107-134`](../../lib/audio_utils.py)). Actual callers use
the helper for uploaded or generated audio duration/stream/container checks in
`server/routers/files.py`, `server/services/generation_tasks.py` and
`lib/audio_utils.py`. The current upload helper intentionally returns `None`
when `ffprobe` is unavailable
([`lib/audio_utils.py:137-158`](../../lib/audio_utils.py)); that permissive
fallback is unsuitable when an M10 profile marks a diagnostic required.

## 4. Facts — what the primary tools can and cannot establish

### 4.1 Container and stream conformance

Official `ffprobe` documentation says the tool reports container and stream
information in human- or machine-readable form, provides selectable output
writers including JSON, and returns a positive exit code when an input cannot
be opened or recognized. It can therefore support bounded conformance evidence
such as stream presence, codec, dimensions, duration and frame/sample
properties. It does not establish factual, narrative or aesthetic quality.
[[FFmpeg `ffprobe`](https://ffmpeg.org/ffprobe.html)]

**Inference:** every M10 technical probe observation should preserve the exact
tool binary identity/build configuration, normalized arguments, profile rule
identity, input artifact digest, exit status, bounded stdout/stderr evidence,
parser version and parsed result. A zero exit code is execution evidence, not a
`PASS` disposition.

### 4.2 Black, freeze, silence and loudness detection

FFmpeg's first-party filter documentation exposes parameterized detectors:

- `blackdetect` emits `lavfi.black_start` / `lavfi.black_end` frame metadata and
  has a configurable minimum duration;
- `freezedetect` emits start, duration and end metadata based on configurable
  noise and duration;
- `silencedetect` emits channel-aware silence metadata after a configured
  threshold/duration;
- `ebur128` analyzes momentary, short-term and integrated loudness plus loudness
  range, with optional sample/true-peak measurement.

[[FFmpeg filters: `blackdetect`](https://ffmpeg.org/ffmpeg-filters.html#blackdetect),
[`freezedetect`](https://ffmpeg.org/ffmpeg-filters.html#freezedetect),
[`silencedetect`](https://ffmpeg.org/ffmpeg-filters.html#silencedetect),
[`ebur128`](https://ffmpeg.org/ffmpeg-filters.html#ebur128)]

**Inference:** an interval is not intrinsically a defect. A deliberate fade to
black, held frame, dramatic silence or music-only section can be valid. Detector
parameters and the rule translating observations to blocking/advisory findings
must live in a named `QualityProfile` revision. Raw intervals remain available
for Human/semantic adjudication.

### 4.3 VMAF is conditional full-reference evidence

Netflix's official VMAF implementation computes features from both a distorted
video and its full-quality reference, then applies a named trained model. Its
documentation provides different models for different display/viewing
conditions and requires explicit alignment/preprocessing choices in FFmpeg
examples. Model selection and preprocessing therefore affect the meaning of a
score.
[[Netflix VMAF README](https://github.com/Netflix/vmaf),
[VMAF Python documentation](https://github.com/Netflix/vmaf/blob/master/resource/doc/python.md),
[VMAF with FFmpeg](https://github.com/Netflix/vmaf/blob/master/resource/doc/ffmpeg.md),
[VMAF models](https://github.com/Netflix/vmaf/blob/master/resource/doc/models.md)]

**Fact:** VMAF is applicable when R2 has a semantically equivalent named
reference and is measuring render/transcode degradation. It is not a
no-reference measure of whether a new generated scene is attractive, faithful,
factually correct or narratively effective.

**Inference:** a `PerceptualRegressionObservation` is valid only when it binds:

- reference artifact digest and distorted artifact digest;
- a declared relationship such as same-master transcode or deterministic
  projection, never merely “similar content”;
- time/frame alignment and any trim, scale, colorspace, pixel format, bit depth
  and frame-rate normalization;
- exact VMAF implementation/model digest and viewing-condition profile;
- aggregate and tail/segment evidence, not only one global number.

If any binding is absent, the result is `NOT_APPLICABLE` or `INVALID`, not a
zero score and not a waived requirement.

### 4.4 Accessibility needs content evidence, not file presence

WCAG 2.2 requires captions for prerecorded audio in synchronized media (Level
A), and the W3C explanation says captions include dialogue, speaker identity
and meaningful non-speech sound. WCAG also defines audio-description/media-
alternative requirements at Level A and audio description at Level AA.
[[WCAG 2.2 SC 1.2.2](https://www.w3.org/TR/WCAG22/#captions-prerecorded),
[W3C explanation of captions](https://www.w3.org/WAI/WCAG22/Understanding/captions-prerecorded),
[WCAG 2.2 SC 1.2.3 and 1.2.5](https://www.w3.org/TR/WCAG22/#audio-description-or-media-alternative-prerecorded)]

**Inference:** “subtitle file exists” and “ASR produced text” are only technical
observations. Accessibility review must separately bind synchronization,
language, speech coverage, speaker/non-speech information, collision/occlusion,
legibility and the profile's audio-description/media-alternative policy. A
Human-accessibility observation may consume automated lint, but automation
cannot self-attest semantic completeness.

### 4.5 Platform packaging fields change independently of M10 authority

The current YouTube video resource separates title, description, tags,
localized metadata, caption availability, privacy state and synthetic-media
disclosure; its first-party documentation currently states title/description
limits and chapter timestamps in description. Thumbnail and caption uploads are
separate API surfaces.
[[YouTube video resource](https://developers.google.com/youtube/v3/docs/videos),
[thumbnail resource](https://developers.google.com/youtube/v3/docs/thumbnails),
[caption resource](https://developers.google.com/youtube/v3/docs/captions)]

**Inference:** a `PackagingCandidate` needs typed platform-profile fields and a
versioned constraint snapshot, not one universal metadata blob. M10 may lint and
export these values offline. It must not call the documented network methods;
M11 later translates an approved package into provider commands.

## 5. Facts — donor reuse and rejection boundary

### 5.1 OpenMontage

The inspected OpenMontage checkout exactly matches
`08e2151fa02de28a5d6a312b3d575692bf147ad7`.
`tools/publishers/export_bundle.py` is a deterministic local filesystem
packager: it copies a render and optional subtitles/thumbnail, writes metadata,
description/tags/chapters and returns an `exported` log. Its declared capability
says `uploads: false`, and the module explicitly reserves a future network
publisher as a separate provider.

Reuse classification:

- **Port as fixtures/pure behavior:** relative bundle layout, chapter-time
  formatting, required optional-asset failure, title/description/tags/hashtags/
  chapters/subtitle/thumbnail vocabulary.
- **Reject as authority:** mutable path/timestamp identity, filesystem presence,
  coarse `publish_log` state and creator visual inspection as proof of package
  readiness.

### 5.2 Kalinga Shorts Factory

The inspected Kalinga checkout exactly matches
`e4b5a2173ca03d365aad565a89fcc43159b44f9b`.
Its selected source provides useful vertical-Short behavior:

- `pipeline/src/validate.py` orders cheap technical checks before virality and
  SEO checks and includes pure metadata lint;
- `pipeline/src/seo.py` grounds metadata generation in the actual hook,
  headline and research facts;
- `pipeline/src/evaluator.py` routes proposed fixes back to concrete artifact
  classes/segments;
- `pipeline/src/make_video.py` exports no-music/music variants, thumbnail and a
  paste-ready metadata sheet.

Reuse classification:

- **Port as profile corpus/differential fixtures:** cheap-first ordering,
  vertical constraints, grounded metadata lint, repair routing and export
  variants.
- **Reject as authority:** filesystem/cached-file success, advisory validation
  that keeps failed output, self-scored virality, uncalibrated sampled-frame
  model review, automatic repair as approval and manual-only delivery.

No donor output, attractive sample or smoke test constitutes R2 quality
acceptance. Any selected behavior still requires an exact-pin
`DonorParityContract`, same-fixture differential tests, defect fixtures and
independent review under the accepted R2-DEC-031 rule.

## 6. Inference — recommended M10 quality-evidence model

### 6.1 `QualityProfile` is published policy, not mutable configuration

A profile should have an immutable revision and canonical digest over at least:

```text
QualityProfile
  identity: profile_id, revision, profile_digest, schema_version
  scope: product_surface, output_format, cohort, locale, platform_profile?
  subject_rules: allowed master/projection/package subject kinds
  required_dimensions: technical, factual, narrative, continuity,
                       perceptual, accessibility, packaging?
  probe_rules[]: probe kind, tool/config identity, applicability,
                 threshold/finding mapping, resource/timeout/output limits
  rubric_rules[]: rubric/version, reviewer qualification,
                  independence and disagreement/escalation policy
  completeness_rules: required/optional/not-applicable semantics
  freshness_rules: evidence lifetime and supersession behavior
  disposition_rules: permitted results, waiver eligibility/max TTL,
                     readiness TTL and re-evaluation triggers
  export_rules?: bundle layout/manifest and platform constraint snapshot
  provenance: author/custodian, issued_at, supersedes?
```

Thresholds are per profile and product surface. A Western explainer, vertical
factual Short and `zh-shuang` short-drama profile may share mechanics while
retaining separate thresholds, rubrics, locale and cohort identity. Publishing
a profile revision must use a Human custodian and append-only/CAS semantics;
editing a row in place would make old evidence uninterpretable.

Profile digest domains must exclude database IDs and mutable timestamps where
they do not alter policy, but include every field that can change probe meaning,
applicability, completeness or disposition. The future design must freeze the
canonical serialization and exact domain; this research does not guess it.

### 6.2 `QualityRun` is a closed evidence set

Recommended shape:

```text
QualityRun
  run identity + schema version
  exact user/project scope
  exact ApprovedMaster identity + immutable artifact/content digest
  exact QualityProfile identity/revision/digest
  assessed-subject closure[]
  observation refs + digests by required dimension
  execution/receipt refs for automated assessors
  assessor identities, kind, qualification and independence group
  applicability/completeness result per required rule
  started_at/completed_at + run digest
  status: IN_PROGRESS | COMPLETE | INVALID | SUPERSEDED
```

Only `COMPLETE` can be presented to the custodian. `COMPLETE` means every
profile-required rule has exactly one valid outcome or an explicitly permitted
`NOT_APPLICABLE` with evidence. Missing, timed-out, unsupported, malformed or
unknown probe results remain distinct and fail closed; they cannot be converted
to `PASS` or zero findings.

Observations should be a closed discriminated union for the accepted schema
version:

- `TechnicalObservation`: stream/container/conformance, black/freeze/silence,
  loudness and deterministic packaging lint;
- `FactualObservation`: exact ClaimLedger/ResearchPack verification refs and
  coverage, without duplicating factual authority;
- `NarrativeObservation`: rubric item, segment/time range, finding and reviewer;
- `ContinuityObservation`: Canon/epistemic/visual identity refs plus exact
  violated invariant;
- `PerceptualRegressionObservation`: only the full-reference case in §4.3;
- `PerceptualReviewObservation`: calibrated model or Human cohort result kept
  separate from full-reference regression;
- `AccessibilityObservation`: caption/audio-description/media-alternative and
  visual-legibility evidence;
- later `PackagingObservation`: metadata/thumbnail/chapter/caption/export
  checks over an exact package revision.

Every observation binds the exact assessed subject, assessor implementation
and version/config, evidence payload digest, observation time, result state and
structured findings. Model output should additionally bind model identity,
prompt/rubric digest, sampling policy and calibration cohort. Human observations
bind reviewer qualification, independence group and rubric revision. Free-form
notes may explain evidence but cannot replace typed fields.

### 6.3 Multi-assessor does not mean score fusion

Technical probes, factual authority, semantic models and Human reviewers answer
different questions. The run may expose per-rule results and disagreement, but
must not collapse them into a weighted “quality score” that authorizes Final
Cut. In particular:

- deterministic failure can create a profile-defined blocking finding;
- model judgment can route or prioritize Human review;
- required Human rubrics cannot be self-satisfied by the model that produced
  the artifact;
- disagreement remains evidence and follows a profile-defined escalation rule;
- only the Final Cut custodian issues a disposition.

### 6.4 `QualityDisposition` is append-only authority

ADR-0080 already fixes `PASS | REWORK | WAIVE`. The future contract should bind:

```text
QualityDisposition
  disposition_id, command_id, schema_version
  user_id, project scope
  ApprovedMaster identity + artifact/content digest
  QualityProfile identity/revision/digest
  complete QualityRun identity/digest
  assessed-subject closure digest
  optional PackagingCandidate identity/revision/payload digest
  result, reason, issuer, issued_at, expires_at
  supersedes?, authority receipt/lease identity
```

Recommended operational rules:

- authorize outside the database transaction through a short-lived,
  subject-bound Human custodian lease; admit it using database time;
- serialize by command identity, make the receipt authoritative for exact
  retries, then lock current disposition/head rows in one documented order;
- re-read exact master/profile/run/package bindings in the same short
  transaction that appends the disposition and advances its CAS head;
- changed-subject replay, stale CAS, expired lease, incomplete run or mismatched
  digest fails without partial authority writes;
- `WAIVE` must name the waived findings/rules, justification and a stricter
  profile-bounded expiry; it never edits or deletes findings;
- `REWORK` is an authority result but never mutates production artifacts; repair
  re-enters the existing candidate/Production Authority flow.

Readiness is a projection, not a mutable boolean. It is true only when the
current exact subject has an unexpired, unsuperseded disposition whose bound
master, artifact, profile, run and optional package all still match.

### 6.5 Invalidation and expiry

The following invalidate current readiness without rewriting history:

- a different ApprovedMaster or artifact/content digest;
- a different profile revision/digest where the active readiness policy
  requires that revision;
- a new, invalid or superseded run;
- any assessed-subject closure change, including caption, thumbnail or metadata
  when included;
- a different packaging revision/payload digest;
- explicit disposition supersession or expiry.

Probe-tool updates do not silently rewrite old observations. Their exact tool
and model identities remain valid historical facts; profile publication decides
whether a new version requires re-evaluation for current readiness. This
preserves auditability while allowing critical detector/calibration changes to
force a new run.

## 7. Inference — packaging only after the foundation

### 7.1 `PackagingCandidate` is an M8 schema evolution

After M8 implementation is accepted and its real extension seam is verified,
M10 should add an immutable `PackagingCandidate` payload and a closed
`PACKAGING_SLOT` target through an accepted additive schema/migration. Candidate
content should bind:

- exact ApprovedMaster and deliverable artifact digests;
- profile/platform-profile identity and constraint-snapshot digest;
- title, description, tags/hashtags, chapters and localization variants;
- thumbnail/caption/audio-description/media-alternative artifact digests;
- disclosure and audience-classification fields applicable to the profile;
- optional cut/format variant refs, each already governed by Production
  Authority rather than embedded mutable media;
- complete payload digest and parent revision.

Selection should reuse actual accepted M8 revision/head/preview/idempotency/CAS
behavior. It additionally binds the current applicable `QualityDisposition`.
Packaging Authority selects metadata/assets for export; it cannot select an
`ApprovedMaster`, promote to `ARTIFACT_SLOT`, invoke Production Authority or
authorize M11 publication.

### 7.2 Deterministic export bundle

An export bundle should be a materialization of an already selected immutable
package, not the authoritative package itself. Recommended output:

```text
bundle/
  manifest.json       # schema/version, source refs and sorted relative files
  media/...           # exact approved deliverables
  captions/...
  thumbnails/...
  metadata/...        # platform-profile projections, chapters/localizations
```

The manifest binds each relative path, byte length and content digest, the
selected package payload digest, exact master/artifact digests, profile and
quality-disposition digests, exporter implementation/config and creation
receipt. Path traversal, symlinks, absolute paths, duplicate/case-colliding
names, unexpected files, missing required assets and aggregate/file byte limits
must fail closed. The reproducibility contract should specify whether archive
metadata/timestamps are normalized; wall-clock timestamps must not enter the
content digest.

Creating a directory or archive does not prove success. Acceptance requires a
fresh verifier to re-read bytes, recompute the manifest closure and confirm the
selected package/readiness bindings. Status is `EXPORTED`, never `UPLOADED`,
`PUBLISHED` or `PUBLIC`.

### 7.3 Explicit no-network boundary

M10 code and tests must have no provider credential port and no HTTP/browser/
provider SDK dependency in the quality or packaging module. Platform
documentation supplies offline validation profiles only. M10 may emit an export
bundle and M11-compatible future input reference; it may not:

- choose account/channel or visibility/schedule authority;
- call upload, thumbnail, caption, scheduling or publication endpoints;
- infer successful delivery from export completion;
- create `PublishApproval`, `DistributionCommand`, provider-session identity,
  `DeliveryAttempt` or `DistributionReceipt`.

Any need for those capabilities stops as an M11 scope request rather than being
hidden in an exporter.

## 8. Options

| Option | Shape | Strength | Material risk | Result |
|---|---|---|---|---|
| **A. Quality foundation, then packaging** | First freeze profile/run/observations/disposition and local probe evidence; only then evolve M8 packaging and export | Smallest authority surface, evidence can stabilize before package currentness depends on it, aligns with ADR-0080 | Two design/acceptance packets instead of one | **Recommend** |
| B. One combined quality-and-packaging packet | Freeze all contracts, migrations and exporters together | Fewer documents and one integration pass | Couples probe validity, Human authority, M8 evolution and filesystem materialization; larger blind-review surface and rollback | Reject |
| C. Vertical-Short product slice first | Copy Kalinga profile/fixtures and build one export path | Fast visible artifact | Lets a donor profile define the kernel, risks filesystem success becoming authority, and cannot use unaccepted M8/M9 behavior | Reject as architecture; retain as later pilot fixture |
| D. Extend current `QualityReport` with more fields | Add thresholds/findings to the existing generation report | Superficially small change | Preserves one-reviewer/optional-score semantics and conflates evidence with disposition | Reject |

## 9. Recommended milestone decomposition

### M10-A — Quality-evidence foundation

Own and accept before packaging:

- versioned/published `QualityProfile` revisions and CAS heads;
- closed typed observation union and canonical digest domains;
- `QualityRun` completeness/validity/supersession state;
- secure bounded local Quality Probe seam, initially `ffprobe` plus profile-
  selected black/freeze/silence/loudness adapters;
- reference-valid VMAF adapter with explicit `NOT_APPLICABLE`/`INVALID` states;
- factual/narrative/continuity/perceptual/accessibility reviewer ports and
  independence semantics;
- append-only Human `QualityDisposition`, receipt/idempotency/lease/CAS,
  invalidation, expiry and waiver behavior;
- exact current-readiness projection over ApprovedMaster only;
- schemas, migrations, adversarial tests, resource bounds and machine-readable
  acceptance evidence.

M10-A does not create `PackagingCandidate`, `PACKAGING_SLOT`, export directories
or network interfaces. A master-only disposition proves the foundation without
prematurely binding an unavailable packaging seam.

### M10-B — Packaging candidate and deterministic export

Start only after M10-A is independently accepted and actual M8 extension seams
are reverified:

- additive `PackagingCandidate`/`PACKAGING_SLOT` schema evolution;
- immutable revisions, preview-bound selection and packaging CAS;
- package-scoped quality observations/disposition closure;
- platform-profile metadata/caption/thumbnail/disclosure validation;
- deterministic export materializer and independent bundle verifier;
- OpenMontage/Kalinga same-fixture differential tests;
- Western explainer export-only pilot, then vertical factual Short, then
  `zh-shuang` export-only after cohort-specific rubrics are accepted.

M10-B exit is an independently verified local bundle. It creates no M11
authority or network state.

### M10-C — Integrated evidence and milestone acceptance

If project convention requires a separate integration packet, it should bind
the accepted M10-A and M10-B candidate HEADs, migrations, donor parity,
resource evidence and pilot fixtures at one clean integrated HEAD. It remains
export-only and should not broaden the domain model.

## 10. Prerequisites and fail-closed stop conditions

Design work may continue from the accepted ADR-0080 architecture, but no M10
implementation packet is eligible until a machine-verifiable prerequisite
record proves all of the following on the executor's exact clean base:

1. M8 implementation is independently accepted, including the real candidate
   revision/preview/promotion/CAS and M7 execution/receipt seams;
2. M9 implementation and its required acceptance evidence are independently
   accepted, because ADR-0080 makes milestone order normative;
3. the existing Factual Authority implementation used by factual observations
   is accepted at the base lineage;
4. the M10 ADR/design, schemas, migration chain, acceptance rubric and execution
   contract are accepted and hash-bound;
5. required FFmpeg/ffprobe/VMAF capabilities are measured on the declared host
   environment; unavailable required probes do not downgrade to skips;
6. one M10 packet is active at a time and its owned paths are clean/allowlisted.

Recommended stop taxonomy for the future design (names are provisional until
accepted):

| Condition | Stop code |
|---|---|
| M8/M9/Factual Authority acceptance absent, malformed or wrong lineage | `M10_PREREQUISITE_NOT_ACCEPTED` |
| M10 design/contract/schema acceptance absent or hash drifted | `M10_DESIGN_NOT_ACCEPTED` |
| accepted M8 extension/transaction seam differs from the designed base | `M10_BASE_SEAM_CHANGED` |
| required probe binary/filter/model absent or identity mismatched | `M10_PROBE_CAPABILITY_UNAVAILABLE` |
| artifact/profile/reference/config closure incomplete | `M10_EVIDENCE_BINDING_INCOMPLETE` |
| required assessor result missing, invalid, timed out or unqualified | `M10_REQUIRED_EVIDENCE_MISSING` |
| disposition authorization/lease/subject binding invalid | `M10_DISPOSITION_UNAUTHORIZED` |
| disposition or packaging head CAS/currentness fails | `M10_CURRENTNESS_CONFLICT` |
| packaging requests network/provider/credential authority | `M10_M11_BOUNDARY_VIOLATION` |
| donor pin/surface/fixture or differential parity drifts | `M10_DONOR_BASELINE_DRIFT` |

Stop receipts are diagnostic evidence, never acceptance, and must not be
committed from a failed read-only preflight unless the later execution contract
explicitly names a separate recovery workflow.

## 11. Acceptance unknowns that the ADR/design must close

1. **Profile publication authority:** exact custodian port, lease TTL/admission
   rule, command-replay identity and CAS lock order.
2. **Digest domains:** canonical bytes for profile, every observation variant,
   run closure, disposition, readiness and package payload.
3. **Subject closure:** whether master-only M10-A includes derived captions and
   semantic reports by value digest or by immutable artifact ref plus digest.
4. **Completeness algebra:** exact required/optional/not-applicable/unsupported/
   invalid states and which combinations permit a complete run.
5. **Assessor independence:** qualification records, model-producer conflict,
   Human reviewer independence groups and disagreement escalation.
6. **Factual bridge:** exact accepted ClaimLedger/ResearchPack read interface and
   rules for stale, withdrawn or correction-linked claims.
7. **VMAF applicability:** permitted reference relationships, alignment
   tolerances, model pins, segment/tail thresholds and resource ceilings.
8. **Accessibility profiles:** conformance target per product/profile, language-
   specific caption rubric and when audio description or a media alternative is
   required.
9. **Tool/calibration supersession:** which security/validity changes make a
   newer profile mandatory for current readiness without rewriting history.
10. **Disposition expiry:** maximum readiness and waiver TTLs, renewal semantics
    and whether `PASS` can ever omit an expiry (ADR-0080 currently requires one
    in every disposition binding).
11. **M8 additive evolution:** exact accepted extension mechanism for payload
    union, target enum, repository tables, preview and promotion routing after
    M8 implementation exists.
12. **Package currentness:** atomic read/CAS relationship among selected package,
    current disposition and exact ApprovedMaster.
13. **Export reproducibility:** archive format, normalized metadata, filename
    portability/collision policy, aggregate/file limits and verifier location.
14. **Platform constraint snapshots:** owner, update cadence and how changed
    first-party constraints supersede a profile without granting M11 authority.
15. **Acceptance envelope:** exact reviewers, independence rubric, evidence
    schemas, accepted HEAD lineage, migration proof, resource ceilings, required
    skips/unknowns policy and status-only ADR transition verifier.

## 12. Recommendation

Proceed with **Option A**. The next ADR/spec should make M10-A a complete,
independently acceptable quality-evidence and Final Cut authority module over an
exact `ApprovedMaster`, with no packaging or network side effect. Only after
M10-A acceptance should M10-B add the M8 schema evolution for immutable
`PackagingCandidate` revisions and deterministic local export bundles.

This order yields useful, auditable evidence before any package readiness state
depends on it; keeps Production, Final Cut, Packaging and Publish authorities
separate; and makes missing prerequisites or invalid measurements explicit
rather than converting them into permissive skips. It also preserves the donor
value that was actually verified—fixtures, pure lint and offline layout—without
inheriting donor authority.

## 13. Inspected sources

### Local repository and pinned donor evidence

- `docs/adr/0080-post-m8-north-star-closed-loop.md`
- `docs/research/2026-09-14-r2-north-star-completion-research.md`
- `docs/adr/0079-m8-integrated-exploration-learning-format-kernel.md`
- `docs/superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md`
- `docs/r2/evidence/R2_M8_DESIGN_HANDOFF_2026-09-13.md`
- `docs/r2/evidence/R2_M8_EXECUTION_CONTRACT_2026-09-13.json`
- `docs/adr/0081-m9-evidence-first-opportunity-intelligence.md`
- `docs/r2/evidence/R2_M9_EXECUTION_CONTRACT_2026-09-14.json`
- `lib/audio_utils.py`; real call sites in `server/routers/files.py` and
  `server/services/generation_tasks.py`
- `r2/contracts/results.py`, `r2/production/approval_service.py` and
  `r2/production/artifact_metadata.py`
- OpenMontage `08e2151fa02de28a5d6a312b3d575692bf147ad7`:
  `tools/publishers/export_bundle.py`, publish schemas/director and exporter
  tests already catalogued in the north-star research
- Kalinga Shorts Factory
  `e4b5a2173ca03d365aad565a89fcc43159b44f9b`:
  `pipeline/src/{validate,evaluator,seo,make_video}.py` and
  `channels/history-shorts/channel.yaml`

### Primary external sources

- FFmpeg, [`ffprobe` documentation](https://ffmpeg.org/ffprobe.html)
- FFmpeg, [filter documentation](https://ffmpeg.org/ffmpeg-filters.html)
- Netflix, [VMAF official repository and documentation](https://github.com/Netflix/vmaf)
- W3C, [Web Content Accessibility Guidelines 2.2](https://www.w3.org/TR/WCAG22/)
- W3C WAI, [Understanding Captions (Prerecorded)](https://www.w3.org/WAI/WCAG22/Understanding/captions-prerecorded)
- Google, [YouTube Data API video resource](https://developers.google.com/youtube/v3/docs/videos),
  [thumbnail resource](https://developers.google.com/youtube/v3/docs/thumbnails)
  and [caption resource](https://developers.google.com/youtube/v3/docs/captions)
