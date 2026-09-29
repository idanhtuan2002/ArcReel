# R2 M8 — Reuse-first capability research

**Status:** `RESEARCH COMPLETE / DECISION INPUT` — not an ADR, specification, plan, or implementation approval.
**R2 design lineage:** M7 handoff `5d81d833` on `design/r2-m5b-narrative-context`; M8 research checkpoints begin at `619d8678`.
**Research policy:** research precedes proposal and decision; inventory existing capability before adding a component. Per sponsor direction, licensing is outside this research and is not a selection, rejection, or sequencing criterion.

## 1. Research question and decision gates

M8 must determine the smallest coherent architecture that delivers:

1. a non-authoritative Creative Canvas with explicit promotion;
2. spatial experiments without confusing inference with production truth;
3. lineage-bound analytics and non-authoritative learning recommendations;
4. semantic and technical multi-format projections from approved masters; and
5. independently measurable utility for generic Western drama and Chinese short-drama / `爽文` cohorts.

No architecture is selected until the research closes these gates:

- **Existing-capability gate:** every proposed new service, store, contract, queue, or renderer has an explicit comparison with the ArcReel/R2 capability already present.
- **Donor-depth gate:** the relevant donor behavior is read at an immutable revision and mapped behavior-by-behavior, not accepted by repository description.
- **Quality gate:** success and failure oracles exist for canvas durability, promotion races, spatial gaps, recommendations, and every export profile.
- **Profile-isolation gate:** Western-generic and `zh-shuang` observations, policies, recommendations, and evaluations cannot contaminate each other.
- **Authority gate:** canvas history, model inference, analytics, and recommendations cannot silently mutate Canon, NarrativePlan, CreativePolicy, Claim truth, or ApprovedMaster.
- **Operational gate:** M8 reuses M7 execution identity, idempotency, receipts, restart, resource ceilings, and recovery instead of introducing a second uncontrolled runtime.

## 2. Evidence rounds

### Round A — frozen R2 and prior accepted research

The frozen M8 scope is Canvas, explicit `PROMOTE`, spatial experiments, analytics, Learning Engine recommendations, and extra formats. The frozen boundary also states that Canvas State is not Production Truth and learning cannot mutate authority. The accepted M6 direction already supplies sibling profile lineages and typed, immutable, non-authoritative profile-analysis sidecars. M8 should consume those identities and evidence rather than inventing another genre/profile system.

Primary internal sources:

- [`R2_01_FROZEN_ARCHITECTURE.md`](../r2/R2_01_FROZEN_ARCHITECTURE.md)
- [`R2_02_FROZEN_RESPONSIBILITY_MATRIX.md`](../r2/R2_02_FROZEN_RESPONSIBILITY_MATRIX.md)
- [`R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md`](../r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md)
- [`R2_04_CONSOLIDATED_DECISION_LOG.md`](../r2/R2_04_CONSOLIDATED_DECISION_LOG.md)
- [`R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md`](../r2/R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md)
- [`2026-09-12-r2-m6-dual-profile-adaptation-research.md`](2026-09-12-r2-m6-dual-profile-adaptation-research.md)
- [`2026-09-12-r2-m8-canvas-learning-multiformat-research.md`](2026-09-12-r2-m8-canvas-learning-multiformat-research.md)

### Round B — ArcReel/R2 capability inventory

The current host already contains important M8 primitives:

| M8 need | Existing seam | Reuse consequence |
|---|---|---|
| UI workspace | Current React SPA, `StudioCanvasRouter`, and the existing frontend component/store conventions | Extend the host UI and distinguish the existing **Studio Workspace** from the new **Creative Canvas** domain. Do not add a second frontend shell. `StudioCanvasRouter` is a production workspace router/controller, not a node-graph canvas. |
| Graph interaction substrate | Zustand `5.0.15` is a direct host dependency. No direct `@xyflow/react`/React Flow dependency or graph-canvas implementation was found in `frontend/package.json` and the bounded non-test frontend search. DramaClaw uses React Flow + Zustand. | Reuse Zustand and host UI conventions. Treat React Flow and the graph interaction model as a new dependency/behavior surface; adopt or port it only after bundle, accessibility, persistence, performance, and parity evaluation. |
| Production promotion | `r2.production.approval_service.ProductionApprovalService.promote` and ApprovedMaster semantics | Canvas promotion must adapt into the existing authority service; it must not own a parallel promotion authority. |
| Candidate/master quality | `QualityReport`, candidate status, content/execution fingerprints, artifact currency | Reuse quality planes and artifact lineage. Add canvas/spatial/format findings as typed scopes instead of a second generic QA result. |
| Cost and usage observation | `lib.db.repositories.usage_repo.UsageRepository` plus provider usage extraction | Learning ingestion should extend normalized observations from this repository instead of creating a second cost ledger. |
| Aspect ratio and media mechanics | `lib.aspect_size`, aspect-ratio resolution, video provenance, media backends, FFmpeg composition | Technical format planning should reuse these utilities and add deterministic output-profile contracts around them. |
| Profile identity and policy evidence | M6 sibling `generic-western` and `zh-shuang` lineages, exact policy-pack identity, typed sidecars | Every observation/recommendation/evaluation binds profile id, policy version/digest, and lineage. No implicit pooled cohort. |
| Durable execution | M7 ExecutionAttempt, receipts, fencing, restart/recovery, resource and operator outcomes | Spatial analysis, evaluation jobs, and Remotion/FFmpeg exports become bounded M7 executions, not a new queue or job authority. |

This changes the default question from “which donor should become M8?” to “which missing behaviors can be added through existing seams?” It also prevents a naming collision: the current `StudioCanvasRouter` is the host production workspace, whereas M8 Creative Canvas is a new exploration graph.

#### B.1 Exact reuse limits found in source

“Reuse” does not mean stretching an existing type beyond its proven semantics:

- `ApiCall` and `UsageRepository` already capture provider, model, call type, project, segment, resolution/aspect, timing, status, retries, tokens, cost, currency, output, and a bounded provider response. They do **not** identify an R2 approved master, candidate, content/execution fingerprint, creative profile/policy, publication id, metric window, cohort, or experiment exposure. They are a high-value observation source, but not the LearningObservation store.
- `QualityReport` supplies a bounded score plus blocking/advisory planes and reviewer type. It does **not** bind check versions, evidence spans, profile policy, format projection, confidence, or waiver/disposition. Reuse the finding-plane convention and reference quality reports from observations; do not silently redefine old reports as learning evidence.
- `ProductionApprovalService.promote()` proves candidate lifecycle/selection checks, target and content-fingerprint matching, idempotent same-candidate promotion, and an atomic host bridge. Its `approval_record` is opaque and it has no preview digest/expiry, candidate revision, expected current master, or authorization-scope verification. M8 should reuse/generalize the host promotion pattern only after adding those fail-closed preconditions; direct canvas calls to the current method are insufficient.
- `visual_artifact_provenance` already content-addresses actual references, separates logical identity from transport paths, snapshots reference bytes across awaits, and includes the project aspect ratio in visual bases. This is directly reusable lineage machinery. A format derivative still needs its own basis because output profile, reframe decisions, safe areas, and source-master identity are not represented by the current single-project aspect field.
- `aspect_size` is a strong pure mechanics seam for exact ratio reduction, divisible dimensions, tier-to-short-edge mapping, and backend ceilings. It intentionally falls back malformed ratios to `9:16`; an M8 governed `OutputProfile` validator should fail closed instead of inheriting that convenience fallback at its contract boundary.

### Round C — Creative Canvas and spatial donor behavior

At DramaClaw revision `b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83`, the useful canvas behavior includes graph nodes/edges, grouping, storyboard ordering, multi-generation siblings, bounded undo/redo, hydrate/reset, clear intent, viewport bookmarks, impact preview, and named promotion. Its `promoteToAsset()` does not prove approval custody, preview binding, optimistic concurrency, idempotency, or audit durability. Therefore the reusable surface is interaction behavior and vocabulary; the write boundary remains R2.

Director World contributes a useful topology vocabulary: source views, visible/inferred regions, gaps, seam locks, anchor de-duplication, direction locks, and conservative uncertainty. Its model-produced JSON remains evidence-bearing `SpatialCandidate`; it cannot be treated as a fact or ProductionBinding merely because generation used a zero temperature.

Questions carried into the donor-depth round were:

- parity inventory of all DramaClaw node kinds versus ArcReel data already available;
- persistence schema size, migration behavior, large-graph performance, and reload/offline behavior;
- whether every destructive graph action participates correctly in history;
- whether spatial fixtures expose stable seam/gap/duplicate metrics without a live model call.

The full-tree inspection closed the persistence, history, destructive-action, and test-inventory questions at source level as recorded below. Large-graph runtime performance and deterministic spatial fixture parity remain implementation-entry probes because neither dependency-integrated ArcReel canvas code nor an agreed production graph-size envelope exists yet. They are not silently treated as passed.

The graph and direct dependency inspection corrected an earlier assumption: ArcReel has Zustand but no direct React Flow package or graph canvas. Adding React Flow can still maximize reuse of DramaClaw interaction patterns, but it is an evaluated dependency addition, not reuse of an installed host primitive.

#### C.1 Full-tree parity correction and port strata

A sparse checkout of the exact DramaClaw revision changed the reuse estimate materially. The complete Git tree contains **199** Canvas/Freezone/Director-World-related test files: 154 frontend and 45 backend by bounded path/name classification. The prior count in the partial M8 note was not a complete capability count and must not be used for planning.

The donor persistence protocol is substantially stronger than its promotion boundary:

- server revision/OCC through `base_revision`, plus `client_save_id` replay/conflict handling;
- single in-flight save per canvas session, edit coalescing into one follow-up, version-aware waiters, and canvas-switch isolation;
- recoverable local drafts scoped by project/canvas, stable content signatures, 1.5 MB cap, history-first shedding, seven-day pruning, and corrupt-entry rejection;
- dangerous empty-autosave rejection with explicit `manual_clear` / `allow_empty_overwrite` intent;
- node/edge/body caps, server conflict classification, bounded undo/redo, grouping, viewport bookmarks, and restore/history tests;
- atomic JSON replacement, retained history, file-lock behavior, injectable mutex seam, and a fence between fsync and replace.

Because R2 uses PostgreSQL authority and M7 durable execution, donor filesystem persistence should not be transplanted as storage. However, the protocol state machine, pure TypeScript modules, user-recovery behavior, failure taxonomy, and adversarial tests are high-value port candidates. The tentative port strata are:

| Stratum | Treatment before design | Reason |
|---|---|---|
| Pure graph domain, selection, layout, history, bookmark, save-decision and payload-limit functions | Port with donor parity tests, then add R2 tests | High behavioral value and low runtime coupling. |
| Zustand canvas store and React Flow interaction layer | Port selectively behind ArcReel types and routes | Stack versions are close, but this introduces `@xyflow/react` and must meet bundle/accessibility/performance gates. |
| Draft recovery and save coordinator | Port behavior and tests; adapt storage/envelope | Strong race/data-loss handling; browser localStorage remains recovery cache, never authority. |
| API clients, generation gateways, provider/model pickers, billing UI and project-specific aliases | Replace with ArcReel ports/adapters | Heavy donor coupling duplicates ArcReel provider, queue, cost, i18n, and project APIs. |
| Backend JSON store, file locks and filesystem history | Do not use as production storage; translate tests to PostgreSQL repository/OCC | R2 already has the stronger shared authority/durability direction. |
| Director World normalizers and topology vocabulary | Port bounded pure functions with fixtures | Useful spatial semantics; model calls and direct files remain M7 executions/candidate evidence. |
| `promoteToAsset`, `pushToPipeline`, and auto-commit-on-generate behavior | Do not port as authority | Tests confirm UI wiring/targets, but do not bind preview to promotion or prove R2 approval/OCC. A donor test explicitly expects an `autoCommitOnGenerate` path; M8 must prohibit that behavior for Production Truth. |

The main stack versions are close enough to make selective porting plausible: ArcReel/DramaClaw use React 19, Zustand 5 and Vitest 4. DramaClaw adds React Flow 12.10; ArcReel is already on newer React, Vite, Vitest, and TypeScript major/minor versions, so compilation and interaction parity must be proven rather than assumed.

The scale argues against wholesale UI import even when licensing is ignored. The two donor feature trees contain 298 source files and about 101,812 TypeScript/TSX lines in the sparse checkout; 86 files directly match heavy donor API/query/viewer/billing/media dependencies. A narrower state/protocol sample is still about 6,691 source lines plus 1,208 lines in four core test files, with the monolithic store alone at 4,020 lines. Maximum reuse therefore means preserving proven behavior and tests while choosing deliberate extraction seams—not copying an entire second application into ArcReel.

### Round D — Learning foundations and distribution observations

Google's first-party Rules of ML recommends instrumenting metrics before formalizing ML, keeping the first model simple, testing infrastructure independently, checking held-out data before export, using post-training time periods for evaluation, and reusing transformation code between training and serving.^1 These recommendations fit R2 particularly well: M8 v1 should be an evidence and recommendation system first, not a self-modifying model platform.

YouTube's official Analytics API exposes video/content dimensions, time windows, traffic/device/cohort dimensions, and retention using `elapsedVideoTimeRatio`; retention reports provide 100 normalized positions per video. Metrics include views, engaged views, average view duration, estimated minutes watched, likes, comments, shares, subscribers, and retention measures.^2 This means a durable observation must retain the upstream metric name and semantics, retrieval window, platform artifact id, timezone/aggregation, format, profile, and exact approved lineage. A flattened “engagement score” would destroy source meaning and comparability.

The initial learning ladder should therefore be:

1. **Instrument:** immutable internal observations for QA, rejection, regeneration, cost, latency, approval, and export outcome.
2. **Ingest:** externally sourced platform observations with source-specific identity and retrieval windows.
3. **Normalize without erasing:** derived comparable features remain linked to raw observations and transformation version.
4. **Recommend:** evidence bundle, hypothesis, confidence, applicability scope, exclusions, expiry, and expected guardrails.
5. **Evaluate offline:** project/time/profile/format-aware train and holdout partitions; compare against a simple baseline.
6. **Human disposition:** accept, reject, defer, or request experiment; acceptance creates a separate governed proposal, never an authority mutation.
7. **Experiment later:** only after instrumentation and sufficient samples; record assignment/exposure to avoid feedback-loop attribution errors.

TikTok's current first-party APIs illustrate why metrics remain source-specific. The authorized-user video query exposes counts such as views, likes, comments, and shares; the Research API adds favorites, duration, region and content labels under a different scope and query model.^6 YouTube exposes normalized retention curves and broader watch-time semantics. These are not interchangeable measures. Each adapter must preserve API family, credentials/scope class, retrieval time, query window, raw payload digest, metric definition/version, missing/deleted/private outcome, and whether a value is cumulative or windowed.

YouTube's native title/thumbnail experiment is concurrent A/B/C, may keep a control group, reports inconclusive/equal outcomes, and chooses by watch-time share rather than click-through rate; Shorts are currently ineligible.^7 M8 must not treat sequential before/after publishing as equivalent causal evidence. An `ExperimentObservation` needs assignment/exposure identity and an explicit design class (`concurrent_randomized`, `platform_managed`, `sequential_observational`, or `offline_replay`). Only the first two may support causal language, and only within their measured surface.

#### D.1 Cohort and creative-quality isolation

M6 research already establishes that profile policy is sibling evidence over shared authority, not a universal genre truth. M8 should reuse that split:

| Evidence family | Shared mechanics | Generic Western cohort | Chinese short-drama / `zh-shuang` cohort |
|---|---|---|---|
| Hard validation | lineage/currentness, contract schema, continuity/knowledge constraints, approval, technical output | same | same |
| Profile identity | exact profile id, policy version/digest, source-map and content basis | `generic-western` | `zh-shuang` |
| Craft evidence | human rubric version, finding spans, reviewer identity, confidence/disagreement | goal/choice/change, scene causality, distinct voice, emotional coherence and applicable screenplay-format guidance remain advisory unless a named policy says otherwise | bounded Huohuo-derived `恨/爽/急/盼`, six `爽型`, conflict/payoff fields and applicable chapter scope; no universal seconds-to-chapter rule |
| Learning comparison | only like-for-like channel/format/window/content classes | never pooled silently with `zh-shuang` | never pooled silently with Western |
| Holdout | project-disjoint first, then future-time evaluation; no sibling revision leakage | Western corpus and reviewers | native-language short-drama corpus and reviewers |

Automated technical and lineage checks can produce hard outcomes. Creative craft learning must retain reviewer disagreement and report calibration; a single averaged score must not erase minority findings or become automatic approval. Until corpus size and agreement justify something more complex, recommendations should use transparent cohort summaries and rule-based evidence thresholds rather than a trained ranking model.

### Round E — multi-format mechanics versus semantic projection

Technical conformance and creative parity are different problems.

Remotion's official renderer accepts a composition with explicit width, height, fps, duration, input props, codec, concurrency, cancellation, progress, scale, cache controls, and overwrite behavior.^3 TikTok's official posting documentation publishes container, codec, frame-rate, dimension, duration, and file-size restrictions.^4 These sources support versioned technical `OutputProfile` validation, not automatic evidence that a crop preserves narrative intent.

The pinned OpenMontage profile table is useful code structure but not authoritative platform data. For example, it fixes `youtube_shorts.max_duration_seconds=60`, while YouTube's current first-party help says square or vertical uploads up to three minutes can be classified as Shorts.^5 Platform profiles therefore need `profile_version`, source references, retrieval/effective dates, and explicit validation policy. They cannot be timeless constants copied from any donor.

Bounded local probes at OpenMontage `08e2151fa02de28a5d6a312b3d575692bf147ad7` produced:

- `python -m tests.eval.bench_runner --verbose`: 13/13 declared scenarios passed. This validates its current synthetic validator expectations, not R2 creative quality or genre parity.
- a direct profile/crop-math probe passed for TikTok `1080x1920` and a `1920x1080 -> 606x1080` portrait crop window;
- a real one-second FFmpeg composition using `profile="tiktok"` produced `1080x1920`;
- the system Python has no `pytest`, so the pytest suite was not run and receives no pass/fail claim.

`auto_reframe.py` is explicitly experimental and has no direct `AutoReframe`/`auto_reframe` reference in the bounded test tree. It declares deterministic execution, but behavior can depend on optional MediaPipe/OpenCV face detection, a supplied tracking JSON, exception-driven center-crop fallback, and smoothing inputs. Its idempotency key omits at least input content identity, tracking JSON identity, sample fps, codec, and CRF. R2 can reuse crop calculations and FFmpeg mechanics after tests, but must not inherit its determinism or idempotency claims.

OpenMontage's replay harness is also a useful scaffold rather than a Learning Engine: it loads golden JSON, supports exact/tolerance comparison and custom artifact comparators, but carries no project/time/profile split, observation lineage, metric-source semantics, exposure assignment, drift, recommendation lifecycle, or authority bridge.

The minimum decomposition is:

```text
ApprovedMaster lineage
  -> FormatProjectionPlan
       technical OutputProfile
       semantic ReframePlan
       safe-area/caption/layout constraints
       preserved shot/audio/text intent
  -> bounded RenderExecution
  -> TechnicalValidationReport
  -> SemanticParityReport
  -> FormatCandidate
  -> explicit approval/promotion
```

Pure resize/pad/cover can remain deterministic. A crop, shot replacement, text rewrite, caption relocation, timing change, or subject-tracking decision that can alter meaning must be represented in `ReframePlan` and reviewed against the source lineage. Independent regeneration per aspect ratio is not a projection and must create new candidate lineage.

Safe areas cannot be one universal percentage rectangle. TikTok's first-party guidance says the safe zone changes with orientation, caption length, and additional formats and can differ between preview and live devices.^11 YouTube's Shorts editor similarly shows UI-aware guides for overlays that may be hidden by likes, comments, or descriptions.^12 M8 should model a versioned `OverlayConstraintSet` per platform/surface/locale/UI variant, render its overlay during review, and record which constraint version the candidate passed. The technical validator can detect bounding-box collisions; a human/semantic validator still decides whether moving or shrinking a focal subject or caption damages meaning.

### Round F — measurement protocol and evidence saturation

The frozen M8 exit requires measurable workflow/quality utility, but the frozen documents do not supply a production graph-size envelope, minimum effect size, corpus inventory, or platform-data availability. Inventing fixed pass numbers in research would create false precision. The design must therefore carry a versioned `EvaluationProtocol` and require each execution packet to lock its cohort, fixture hashes, measurement window, baseline, minimum detectable effect or confidence interval, and exclusion policy before results are seen.

The minimum evidence families are:

| Surface | Pre-registered fixture/cohort | Required observations | Failure oracle |
|---|---|---|---|
| Canvas durability | empty/non-empty graphs, corrupt and oversized drafts, concurrent saves, reload/switch, undo/redo/group/restore; graph-size ladder through the agreed production envelope | save latency, interaction latency, peak browser memory, payload bytes, conflict/replay outcome, recovered revision | lost acknowledged edit, stale overwrite, unauthorized empty clear, cross-canvas recovery, unbounded history, or missed payload limit |
| Promotion | two actors, stale preview, changed candidate/target/master, retry after unknown outcome | preview digest/expiry, expected and returned revision/master, authorization scope, audit receipt and idempotency identity | any write without exact current preview/authorization/parent, duplicate effect, or ambiguous success without durable recovery |
| Spatial | pinned visible/inferred/gap/seam/duplicate/direction fixtures plus malformed and partial model output | normalized topology, confidence/source classification, warnings, fixture digest and execution fingerprint | inference labeled fact, lost gap, duplicate anchor, broken lock, non-repeatable normalization, or direct production mutation |
| Learning | immutable internal observations, source-specific platform fixtures, late corrections/deletes, duplicate ingestion, project-disjoint and future-time replay | raw and normalized identities, transformation version, cohort/profile, missingness, recommendation evidence/disposition and baseline delta | semantic metric flattening, sibling/profile leakage, train/holdout leakage, causal language for observational data, or authority mutation |
| Multi-format | source masters stressing face/action/text/caption edges across at least `16:9`, `9:16`, and `1:1`, with pinned profile and overlay versions | technical probe output, visual diff/perceptual measures, caption/overlay collision, semantic rubric, render receipt/resources | wrong dimensions/codec/duration, hidden critical content, changed narrative meaning, untracked reframe, or promotion without both reports |

Creative-quality evaluation is profile-isolated and blind to treatment. Each artifact receives independent review from at least two qualified raters in the artifact's language/cultural cohort; rubric version, item-level evidence, confidence, and disagreement are retained. Material disagreement is adjudicated or reported, never averaged away. A pilot estimates variance and reviewer agreement; only then is the confirmatory sample size calculated from the declared smallest useful effect. This applies separately to generic Western drama and native-language `zh-shuang`; sibling revisions of one project cannot cross train/holdout boundaries.

The remaining empirical probes deliberately sit after architecture acceptance but before the corresponding implementation packet can pass:

1. dependency-integrated React Flow bundle, accessibility, and graph-size ladder in ArcReel;
2. ported spatial pure-function fixture parity without a live model call;
3. replay/idempotency behavior for late and corrected analytics observations;
4. actual `16:9`/`9:16`/`1:1` technical renders and blinded semantic-parity review; and
5. profile-specific pilot agreement/variance sufficient to size confirmatory evaluation.

These probes validate replaceable seams rather than justify a second authority, queue, frontend, or truth store. A failed React Flow probe may replace the rendering adapter without changing canvas authority; a failed formatter or spatial probe blocks that capability packet without weakening promotion or learning boundaries.

## 3. Provisional reuse map — not an architecture decision

| Capability | Reuse directly | Adapt/port after parity | Build only missing contract/behavior |
|---|---|---|---|
| Canvas rendering/interactions | ArcReel React shell, Zustand and host component/API conventions | Evaluate React Flow; adapt DramaClaw graph UX, grouping, history, bookmarks and candidate comparison after parity | Graph substrate integration plus server-owned candidate revision/OCC, lineage, audit and promotion adapter |
| Spatial planning | Existing assets, ShotSpec, ProductionBinding, execution fingerprints | DramaClaw topology/gap/seam vocabulary and deterministic normalizers | SpatialCandidate evidence, confidence, validation, corpus and promotion boundary |
| Observation ingestion | UsageRepository, QA/approval/execution records | OpenMontage analysis output shapes and decision-log vocabulary | Lineage-bound observation envelope and source adapters |
| Recommendation lifecycle | Existing profile/policy identities and approval patterns | OpenMontage alternatives/confidence/rejected-reason pattern | Recommendation scope/expiry/evidence, offline evaluation and human disposition |
| Technical exports | Aspect/media utilities, FFmpeg, M7 execution | OpenMontage Remotion composition/profile/validation behavior | OutputProfile identity, receipts and technical parity oracle |
| Semantic multi-format | M6 content basis, scene/shot intent, profile sidecars | Donor reframing primitives where parity-proven | ReframePlan, safe-area/caption checks, semantic parity and approval |

## 4. Findings that are already strong enough to constrain later options

These are research constraints, not a final architecture selection:

1. A second general queue, artifact registry, truth store, or production promotion authority duplicates proven ArcReel/R2 capability and requires evidence of a gap before consideration.
2. The same server-side candidate/revision/promote protocol should cover canvas, spatial, learning-derived change proposals, and format candidates through typed payloads; separate UI stores may not define separate authority semantics.
3. Learning starts with complete, inspectable observations and simple baselines. ML training is optional and evidence-triggered, not the definition of “Learning Engine.”
4. Recommendations are immutable, scoped proposals with currentness and disposition. They are not mutable settings and cannot directly change profile packs or production routing.
5. Multi-format rendering can share one approved source lineage, but semantic changes require a candidate and approval path. Technical conformance alone is insufficient.
6. Western-generic and `zh-shuang` are sibling cohorts over shared mechanics. Metrics may be compared only when metric semantics, content type, format, audience window, and sample policy are compatible.
7. M8 implementation planning must begin from accepted M7 lineage; the present branch contains M7 design packets, not evidence that M7 implementation is complete.

## 5. Research closure and next gate

The decision-changing desk/source research is complete for architecture comparison:

- ArcReel/R2 seams and their semantic limits were inspected rather than inferred from names;
- the pinned DramaClaw tree, persistence protocol, relevant test inventory, coupling scale, and promotion weakness were examined;
- the pinned OpenMontage composition/reframe/QA surfaces received bounded source inspection and fresh local probes;
- internal telemetry reuse limits and external metric semantics were mapped;
- Western-generic and `zh-shuang` isolation, human evaluation, missing/corrected data, and causal-language boundaries were defined; and
- multi-format technical mechanics were separated from semantic projection and approval.

Evidence is saturated enough to compare architectures because the open probes are attached to replaceable adapters or downstream capability gates, not to a disputed authority boundary. The next artifact may score at least three alternatives by quality, verified reuse depth, delivery cost, failure containment, operational burden, reversibility, and evidence risk. Licensing is excluded by sponsor direction and receives no score or veto. No ADR/specification/implementation plan may be written until an architecture proposal is reviewed and explicitly accepted.

## Sources

1. Martin Zinkevich / Google, [Rules of Machine Learning](https://developers.google.com/machine-learning/guides/rules-of-ml), especially Rules 2, 4, 5, 9, 29, 32, 33, 35–37.
2. Google, [YouTube Analytics dimensions](https://developers.google.com/youtube/analytics/dimensions) and [metrics](https://developers.google.com/youtube/analytics/metrics).
3. Remotion, [`renderMedia()` official reference](https://www.remotion.dev/docs/renderer/render-media) and [Parameterized videos](https://www.remotion.dev/docs/parameterized-rendering).
4. TikTok for Developers, [Content Posting API media transfer guide](https://developers.tiktok.com/docs/en/content-posting-api-media-transfer-guide).
5. YouTube Help, [Understand three-minute YouTube Shorts](https://support.google.com/youtube/answer/15424877).
6. TikTok for Developers, [Query Videos](https://developers.tiktok.com/docs/en/tiktok-api-v2-video-query) and [Research API Query Videos](https://developers.tiktok.com/docs/en/research-api-specs-query-videos).
7. YouTube Help, [A/B test titles and thumbnails](https://support.google.com/youtube/answer/16391400).
8. React Flow, [Save and Restore](https://reactflow.dev/examples/interaction/save-and-restore), [Performance](https://reactflow.dev/learn/advanced-use/performance), [Accessibility](https://reactflow.dev/learn/advanced-use/accessibility), and [Sub Flows](https://reactflow.dev/examples/grouping/sub-flows).
9. DramaClaw, pinned source paths and evidence ledger in [`2026-09-12-r2-m8-canvas-learning-multiformat-research.md`](2026-09-12-r2-m8-canvas-learning-multiformat-research.md).
10. OpenMontage, pinned source paths and bounded probe evidence in [`2026-09-12-r2-m8-canvas-learning-multiformat-research.md`](2026-09-12-r2-m8-canvas-learning-multiformat-research.md).
11. TikTok Ads Manager, [TikTok Auction In-Feed Ads](https://ads.tiktok.com/help/article/tiktok-auction-in-feed-ads), Safe Zone section.
12. YouTube Help, [Enhance your Shorts](https://support.google.com/youtube/answer/16215842), overlay placement guides.
