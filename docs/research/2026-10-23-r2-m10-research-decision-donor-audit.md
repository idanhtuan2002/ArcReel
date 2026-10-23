# M10 pre-implementation audit: existing research, decisions and donors

Status: **RESEARCH AUDIT RECORDED; DESIGN NOT RELEASED FOR IMPLEMENTATION**.
Audit base: `28b93411dc908a4616093ee4b8c9276cfeb75e19`, on released V2
`r2-v2.0.5` / `4bd70525dc2a4e5a0e05c57381a90a35301ec169`.

## 1. Scope and conclusion

The user requires all related research, decisions and donors to be reviewed
before further M10 work. No product code, dependency, migration, provider call,
credential operation or production activation was added during this audit.
M9 stays paused and its preserved dirty source remains outside this branch.

**The existing M10 corpus must be reused and rebased, not replaced by the new
exploratory draft.** The root checkout contains five substantial M10 documents
that are absent from the release branch. They include review remediation that
the exploratory draft failed to carry forward. All five match Git objects at
`50f1e9b41b570ae08a4c242fc8905e8eaeb1fbb6`; none is accepted implementation
authority. ADR-0082 is proposed and the original design is proposed for review.

The review used the release checkout, root, `r2-v2-main`, `r2-m9b` and a bound
historical Git object. Its full-text inventory has 1,373 path occurrences,
482 distinct contents, including all 101 research and 101 ADR paths on the
current V2 tree. The broad V2 keyword screen matched 286 documents. These are
**inventory counts**, not claims of 482 semantic reviews or qualified donors.
The substantive sources and dispositions are listed below. The hashed raw
inventory is retained in the local evidence workspace.

## 2. Recovered M10 design corpus and authority status

All paths in this table are original-root paths pinned at `50f1e9b41…`.

| Source | Status / material obligation |
| --- | --- |
| `docs/research/2026-09-16-r2-m10-quality-evidence-packaging.md` | Research input, 704 lines; foundation first, then packaging; exact donor rejection/reuse boundaries (§5–§11) |
| `docs/adr/0082-m10-quality-evidence-and-export-packaging.md` | **Proposed**, 79 lines; Human disposition, separate selection, no master/publication authority; planning only |
| `docs/superpowers/specs/2026-09-16-r2-m10-quality-packaging-design.md` | **Proposed**, 799 lines; typed policies/slots, seven observation families, Human leases, validity and A/B freeze boundaries |
| `docs/superpowers/plans/2026-09-16-r2-m10-quality-packaging.md` | Proposed overall plan; M10-A → M10-B → optional evidence-only C; repository-read-only bootstrap |
| `docs/superpowers/plans/2026-09-16-r2-m10a-quality-evidence-foundation.md` | Proposed foundation plan; no package/export/network behavior in A, Kalinga-only A7 parity |

Commit `50f1e9b41…` is specifically **“remediate m10 contract review”**.
It added typed assessment policy, stable slots and independence counts,
design-owned bootstrap, no-repository-write failure, A-only contract/digest
freeze and Kalinga-only foundation parity. Discarding these would lose prior
review work. A proposed requirement is not falsely relabeled accepted; it still
must be explicitly retained or changed in the rebased candidate.

The missing North Star research was recovered from
`016e094689b5e59666ee879c33bdc194caa415a0:docs/research/2026-09-14-r2-north-star-completion-research.md`.
SHA-256 `b32246a69e50d1ec79562d77b97e8b162b9885b0e94a6bc286da517078cd8912`
matches the accepted architecture record. Its six-family quality model and
donor audit (§5, §8) are substantive inputs, not an unavailable citation.

## 3. Research closure reviewed

Paths below are under `docs/research/` unless marked historical/root.

| Research group | Material source and consequence |
| --- | --- |
| Original requirements | `r2-origin/00_PRODUCT_VISION.md`, `01_RESEARCH_SYNTHESIS.md`, `02_SYSTEM_REQUIREMENTS.md:58–79`, `03_ARCHITECTURE.md`: six QA layers; fail-gate stops; independent assessment; metadata/cut generation is a separate packaging capability |
| Reuse and completion | `2026-09-07-r2-reuse-map-and-completion-gates.md` and its source manifest: exact donor pins and executable proof; no whole donor runtime transplant |
| M3 real media | `2026-09-21-r2-m3-real-media-closure-research.md:65–105`: synthetic labels are not rendered media; Remotion/FFmpeg source and fixtures must be distinguished from host acceptance |
| Human gates/export | `2026-09-22-r2-p1-gate-receipt-surface-research.md`; `2026-09-28-r2-v1-export-definition.md`; `2026-09-28-r2-v1-decision-audit.md:27–65`: exact approved deliverable and protected export route; anonymous static media is not an export download mechanism |
| Audio/script correctness | `2026-09-28-r2-v1-08-release-gate-gaps.md` and ADR-0092: explicit verified AUDIO/MUTE, factual script lock without forged screenplay admission |
| M6/cohorts | `2026-09-12-r2-m6-dual-profile-adaptation-research.md:469–619,642–865`: versioned sibling profiles, language/corpus applicability, currentness under the authoritative transaction |
| M7 execution/recovery | `2026-09-12-r2-m7-host-production-hardening-research.md`; M7C liveness study; H6 custody/backup/restore and H7 log studies: one host execution substrate, immutable media, fenced writes, redacted evidence, restore identity |
| M8 direct reuse | `2026-09-12-r2-m8-canvas-learning-multiformat-research.md`; `2026-09-13-r2-m8-reuse-first-comprehensive-research.md:51–67,135–166`; architecture-options study: quality report is insufficient alone; source-projection review and donor checks remain separate |
| M8 V2 integration | `2026-09-29-r2-m8a-master-authority-seam.md`, M8 lineage/scale/rebase studies; M8C custody/consumer/source/promotion studies: historical “not wired” findings must be refreshed against released V2 rather than repeated as current facts |
| V2 release boundary | `2026-09-17-r2-v1-production-readiness-v2-deferment.md`; `2026-09-29-r2-v2-start-research.md`; `2026-10-18-r2-v2-story-release-research.md`; `R2_V2_CAPABILITY_AND_V3_BOUNDARY.md`: V2 base identity is distinct from authority expansion and release labeling |
| Original M10 | Five original documents above plus recovered North Star research: current primary design basis, subject to explicit V2 revalidation |
| M9/M11/M12 adjacency | Root M9 design validation and proposed M11/M12 research/ADRs: source truth is not quality approval; future publication must bind exact package/manifest/disposition; learning cannot mutate profiles or authority |
| New M10 observations | The three 2026-10-23 start/reuse/seam studies are preliminary V2 refresh evidence; they do not supersede the original design or acceptance rules |

The other research topics were screened as dependency context or unrelated
host/provider/agent behavior. Their presence does not authorize importing a
new provider, model, scheduler, factual store or packaging authority.

## 4. Decisions and precedence

| Decision source | Required disposition |
| --- | --- |
| R2.4 registry, 30 entries | Human authority; one writer per state family; PostgreSQL; host owns runtime/export; no second queue/manifest; explicit ApprovedMaster selection; composition choice and recommendation-only learning remain applicable |
| ADR-0062 | Artifact currency and task result are different axes. Package-readiness rules must not globally redefine the host's stale-but-usable artifact behavior |
| ADR-0071 | Export uses its download-token surface; no long-lived session JWT in URLs and no new anonymous package directory |
| ADR-0075/0076/0077 | Canon/narrative/adaptation owners and cohort evidence remain distinct; a QA observation cannot commit those authorities |
| ADR-0078 | M7 execution/receipts/recovery substrate, short authoritative transactions, prepared immutable media and no XA/second runtime |
| ADR-0079 | Shared M8 candidate kernel, explicit preview binding, separated technical/semantic evidence and sibling cohorts |
| ADR-0080 + accepted architecture contract | M10 authority separation; ordered prerequisites; two independent normative reviews; typed domains and exact design/evidence freeze |
| ADR-0082 | Proposed original M10 specialization; retain its remediated design input without falsely claiming acceptance |
| ADR-0089/0090/0091/0092 | Human gates, controlled manual external publication, restore/log/paid-route constraints and measured audio. Earlier sponsor exceptions apply to their named packets only |
| ADR-0094 | Pipeline view is host runtime projection; no new M10 workflow engine |
| ADR-0095/0096/0097 | Deferred target is not an available implementation; M7 DB head is sole master authority; existing M8 promotion changes a master and cannot select a package unchanged |
| ADR-0098/0105/0107 | Server-resolved lineage, admitted screenplay profile and currentness checks cannot be replaced by client-supplied profile labels |
| ADR-0103 | Explicit Governance grant/custody and revocation seams exist for their scope. Host admin/API authentication is not automatically a qualified Human Showrunner grant. M10 custodian composition needs its own verified scope |
| ADR-0104/0106 | Gate C episode-video target and user/project-scoped candidate identity remain authoritative |
| ADR-0108 | Model-reviewer exception and blind protocol apply to M8; they do not waive M10 independent-review or runtime Human authority requirements |
| ADR-0109 | Story-model route qualification is role-specific; it does not qualify a new semantic quality assessor |
| Current V2 capability boundary | Independent M10 quality is listed as deferred expansion. User authorization switches active work to M10 on a V2 base, but does not fabricate M9 acceptance, grant code freeze or automatically choose the next release version |

Old “M8 implementation pending” research is dated evidence; V2 now has actual
M8 code. Conversely, a working M8 import is not whole-predecessor acceptance.
The effective implementation prerequisite and the user-requested M9 pause must
be reconciled in an explicit bounded sequencing record, not silently ignored.

## 5. Donor and host reuse matrix

| Source / pin | Audit result and permitted next use |
| --- | --- |
| ArcReel/R2 released V2 `4bd70525…` | Direct source/fixture baseline: verified bytes, candidate revisions, master locks, receipts. Add `lib/audio_utils._run_ffprobe` and existing Jianying export to the reuse search; do not create a parallel queue/export truth |
| OpenMontage `08e2151fa02de28a5d6a312b3d575692bf147ad7` | Inspected exporter, CompositionValidator, VisualQA, VideoCompose, Remotion Root, bench and direct fixtures. Export layout/pure rules and negative fixtures are candidates; no donor success or final-review score grants authority |
| Kalinga `e4b5a2173ca03d365aad565a89fcc43159b44f9b` | Complete local checkout recovered; inspected validator, SEO, evaluator, make_video, script checks, smoke test and pinned Pompeii media. Foundation A7 selects quality/lint behavior; packaging variants belong to B |
| FFmpeg/ffprobe installed `8.0.1-3ubuntu2+esm5` | Direct local probe tools, version-bound. Current build lists black/freeze/silence/EBU/loudness filters; filter presence is not measurement/profile qualification |
| Netflix VMAF | Conditional reference-comparison source only. No `libvmaf` appeared in the current filter listing, and no exact model/tool parity is qualified. Do not require or replace it with an arbitrary no-reference score |
| DramaClaw `b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83` | Existing pinned manifest and M8 port are historical/reference inputs. Reuse the accepted host kernel first; no new donor filesystem/promotion runtime is selected |
| Huohuo `f104b853b3563e124d9cde25f9331d323fb483b9` | Profile/rubric fixture only, preserving chapter applicability. No universal short-duration taxonomy or technical export authority |
| Novel Studio AI `9b690ae2e2f6921f9bd2782b42cef53c1662ad3b`; Shenbi `65ddfc261f4e491b07c36e548f78de36109be218`; StoryBox `ba24ff64e6023e8d071af4adb7e64b03bd9b08b1` | Narrative/continuity/epistemic pattern inputs from the existing manifest. Inspect host M5/M6 findings first; no newly qualified media-quality or Human-disposition adapter is claimed |
| take `47c17216b5ad74ee7dd376e8508266e29aefae2c`; Jellyfish `a9678194ddf2d9be3ccbe78d4287d87d5089e123`; ai-short-film `3dc93a62bf472e46cb5edf2999971769a4989cab`; Butterfly `04e694ce4ceecb4ea651724e8be3199bd1959edd` | Indirect shot/readiness/identity/prompt dependencies already assigned to host owners. They do not become a second M10 generator, acceptance writer or repair runtime |
| Remotion / specialized HyperFrames | Existing composition route and output fixtures are evidence producers; registration and smoke output do not prove an M10 quality gate. Preserve R2-DEC-028's division of work |
| Legacy uploader / VieNeu | Deferred M11/provider references. No upload, credential, TTS runtime or guessed abbreviated commit is admitted into M10 |
| ComfyUI / xyflow / RealFlow | Rendering/graph context, not package quality authority; no new integration selected |
| Other Tier-C profile projects named in origin synthesis | Toonflow, Pixelle-Video, NarratoAI, Code2MP4, youtube-autopilot, waoowaoo, LumenX, Huobao and VideoClaw remain profile/pattern candidates. No concrete M10 surface or exact same-fixture qualification is recorded here; their names are not executable reuse evidence |
| Host/PIOS backup donors | Recovery patterns only; a deployment backup/WAL archive is not an approved content package and supplies no quality disposition |

### Direct donor defects reproduced or source-confirmed

OpenMontage pinned offline experiments observed:

- CompositionValidator accepts overlapping cuts and an existing `../outside`
  asset; it rejects an individual reversed interval.
- VisualQA probe returns `success=true` alongside `validation_passed=false`
  when expected width is wrong.
- Its exporter accepts non-decodable bytes and changed unapproved input; fixed
  members repeat but this does not establish immutable package identity.
- Source inspection found file-size black-frame heuristics, sampled review and
  noncritical findings that can coexist with a “pass”; its bench is synthetic.

Kalinga pinned offline experiments/source checks observed:

- Required/missing/duplicate script-label rules are usable negative fixtures;
  word caps are soft findings and visual fields are not validated there.
- Missing virality returns UNKNOWN; validator `ok` only excludes WEAK, so that
  missing gate does not block the combined boolean.
- `_safe_validate` returns true when the validation callback raises.
- SEO context uses the actual script hook/headline. The template fallback and
  its description-length lint still need matched fixtures before a port.
- Automatic repair can keep best effort; queue DONE and MP4 existence are not
  quality decisions; failed music mixing can restore the clean variant.

The earlier partial **bare cache** lacked several Kalinga blobs. The complete
checkout at `/home/anhtuan/Kalinga-Shorts-Factory` contains them at the exact
pin, so “source unavailable” is no longer the audit result. Existing donor
working output/queue changes were preserved; all inspected bytes came from Git.

The exact shipped Pompeii MP4 is 19,822,632 bytes, SHA-256
`34504025cc26351c286a2ddfa520e80e2c4aa037c356f73002944b34e416dfc5`.
It decoded without diagnostics: H.264 1080×1920, 58.443991 s, one audio stream.
Three decoded pixel samples were nonuniform; the first three seconds yielded
48,000 decoded mono PCM samples with RMS about 0.1023. This establishes bounded
media evidence only, not factual accuracy, caption accessibility, perceptual
quality, complete clip coverage or M10 acceptance.

## 6. Findings against the exploratory draft

The 2026-10-23 draft is held and is not an implementation basis.

1. **Prior work omitted.** Rebase the original five-document M10 corpus and its
   review remediation; do not invent a competing contract/packet sequence.
2. **Foundation/package conflation.** Original A freezes profile/run/disposition
   only. Package subjects, shared M8 schema evolution and export are B work.
3. **Incomplete evidence model.** Preserve seven typed observation families and
   requirement/slot/N-of-M/independence/escalation semantics, mapping all six
   original QA layers. A generic technical + human rubric is insufficient.
4. **Waiver regression.** Original dispositions may be bounded up to seven days,
   but WAIVE has a stricter 24-hour maximum. Keep that distinction explicit.
5. **Custodian not authentication.** Profile publication and disposition have
   separate action/subject-bound Human authorization leases, maximum 30 seconds,
   revalidated at DB time. Do not silently convert CurrentUser/admin into them.
6. **Runtime duplication risk.** New probe/export work uses M7 receipts and host
   capacity. An independent M10 lease/job state machine needs explicit evidence
   of a host gap before being introduced.
7. **Bootstrap omitted.** Design-owned, hash-bound, repository-read-only bootstrap
   precedes A0. Failure must not dirty the repo by creating scope/stop artifacts.
8. **Predecessor conflict.** The switch to M10 is authorized; M9 acceptance is
   not. Document an explicit scoped sequencing treatment before releasing code.
9. **Shared-kernel and currentness details.** Resolve candidate receipt ownership,
   run/assessment state transitions, profile-vs-package identity, slot cardinality
   and the exact transitive master closure/lock seam before schema freeze.
10. **Product scope drift.** Three pilot surfaces and generated packaging metadata
    are existing requirements. Any first-packet deferral must remain explicit,
    not be reported as whole-M10 completion.

## 7. Next permitted work and limits

Next is a source-grounded V2 rebase/delta of the original M10 design, closing
these findings and attaching a precise prerequisite/authority treatment. Then
obtain the required design/independent-review freeze and release a bounded
M10-A plan. No implementation packet is released by this audit.

Evidence: [machine-readable audit](../r2/evidence/R2_M10_RESEARCH_AUDIT_2026-10-23.json).
The source inventory, pinned original corpus, scripts, JUnit and probe outputs
are retained in `.superpowers/sdd/2026-10-23-r2-m10-v2/` with a checksummed
archive. Existing 28 baseline tests and the fresh separate 65-test seam run are
not combined into a claimed new 93-test suite. Offline donor characterization
is not host/donor differential parity.

Graph coverage is incomplete by design for documents and external donors; the
older `r2-v2-main` index supplied provisional structural discovery only. Material
host claims were read on V2. Direct and historical/proposed sources are separated;
no unavailable external runtime, missing acceptance record or prior green log
is silently promoted into current production evidence.
