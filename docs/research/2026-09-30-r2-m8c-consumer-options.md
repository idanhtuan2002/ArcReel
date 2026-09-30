# R2 M8-C spatial consumer options: current-source comparison

## Scope and evidence point

This is a read-only comparison of the two representation directions requested
for M8-C. It records current consumers and stated requirements; it does not
select an architecture, authority, storage model, migration, or implementation
plan.

ArcReel observations are from worktree HEAD
`147bfa8cafbdbf6f4784db3e6e00bd41caef6c42`. DramaClaw observations are static
source observations from the local pinned commit
`b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83`. No donor test, provider call, or
runtime execution was performed.

The repository graph generation supplied for this task is
`2026-09-27T03:07:32Z` and does not cover this worktree's M8 files. The parent
had already identified missing freshness for
`r2/contracts/advanced_creative.py`, `r2/advanced_creative/exploration.py`, and
`r2/production_intelligence/readiness.py`; this note therefore uses direct
source inspection and literal searches in `r2`, `lib`, and `server`. Any
absence statement below is limited to those searched paths at this HEAD.

## Observed ArcReel facts

### ProductionBinding inventory

`ProductionBinding` is a contract with target, semantic, production, role,
asset, variant, and state fields. Its field list has no spatial assertion,
constraint, seam, direction, gap, source-span, or constraint-reference field
([`r2/contracts/preparation.py:20`](../../r2/contracts/preparation.py#L20)-[`34`](../../r2/contracts/preparation.py#L34)). Its target enum is only
`SCENE` or `SHOT`, and its role enum is the listed reference roles
([`r2/contracts/enums.py:60`](../../r2/contracts/enums.py#L60)-[`75`](../../r2/contracts/enums.py#L75)).

The direct `ProductionBinding` constructor sites under the searched runtime
paths are fixture/preparation code:

| Site | Observed behavior |
| --- | --- |
| `r2/m3/preparation.py:53-72` | Golden A creates an in-memory source-footage binding only when a reused asset is supplied, then returns it inside a frozen prepared-shot value ([source](../../r2/m3/preparation.py#L53)). |
| `r2/production_intelligence/fixture_loader.py:143-159` | The canonical golden fixture creates an in-memory character binding for a fixture case ([source](../../r2/production_intelligence/fixture_loader.py#L143)). |

The current direct readers are also pure/in-memory:

| Reader | Observed use |
| --- | --- |
| `ProductionReadinessEvaluator` | Matches a supplied binding sequence by role and shot target and returns readiness with the matched binding ID ([`r2/production_intelligence/readiness.py:27`](../../r2/production_intelligence/readiness.py#L27)-[`114`](../../r2/production_intelligence/readiness.py#L114), [`124`](../../r2/production_intelligence/readiness.py#L124)-[`132`](../../r2/production_intelligence/readiness.py#L132)). |
| `compute_content_fingerprint` | Serializes and hashes the supplied bindings, sorted by binding ID and version, alongside the shot and other source references ([`r2/contracts/fingerprints.py:27`](../../r2/contracts/fingerprints.py#L27)-[`46`](../../r2/contracts/fingerprints.py#L46)). |

A direct literal search found no `ProductionBinding` reference in `lib` or
`server` Python source at this HEAD; the bounded result does not rule out
indirect construction, reflection, or future paths. The M8 exploration service
explicitly refuses a `PRODUCTION_BINDING` preview target before the slot/master
path, with the error naming the missing authority ([`r2/advanced_creative/exploration.py:253`](../../r2/advanced_creative/exploration.py#L253)-[`275`](../../r2/advanced_creative/exploration.py#L275)).

### Spatial candidate and execution seams

`SpatialCandidate` contains a `SpatialPayload`; each assertion has an evidence
class, source references, generic relation, subject references, confidence, and
warnings. The payload keeps seam locks, direction locks, duplicate warnings,
execution ID, and normalizer version ([`r2/contracts/advanced_creative.py:275`](../../r2/contracts/advanced_creative.py#L275)-[`296`](../../r2/contracts/advanced_creative.py#L296)). These values are not fields of
`ProductionBinding`.

The M4 prompt-planning seam has a possible semantic-to-provider location, but
does not currently read a binding or spatial constraint:

- `PromptPlanner.build` receives only a shot, method decision, and resolved
  identity, and derives its plan from shot purpose, framing, camera, duration,
  and identity constraints ([`r2/production_intelligence/prompting.py:42`](../../r2/production_intelligence/prompting.py#L42)-[`72`](../../r2/production_intelligence/prompting.py#L72)).
- `PromptPlan` has semantic, composition, camera, reference, identity,
  controls, and output-requirement fields; it has no spatial-constraint field
  ([`r2/contracts/execution.py:48`](../../r2/contracts/execution.py#L48)-[`70`](../../r2/contracts/execution.py#L70)).
- `DefaultPromptCompiler` validates controls/reference kinds and emits a fixed
  provider payload whose keys include instruction, subject, environment,
  action, composition, camera, timing, references, identity, and controls
  ([`r2/production_intelligence/prompting.py:119`](../../r2/production_intelligence/prompting.py#L119)-[`176`](../../r2/production_intelligence/prompting.py#L176)).
- The M7 video submit seam creates a `ProviderRequest` from the existing
  `VideoGenerationRequest` semantic payload and hands it to the durable attempt
  submitter ([`lib/video_backends/execution_adapter.py:136`](../../lib/video_backends/execution_adapter.py#L136)-[`197`](../../lib/video_backends/execution_adapter.py#L197)). The durable submitter hashes and validates the exact request/route before
  calling its adapter ([`r2/host_hardening/host_submit.py:70`](../../r2/host_hardening/host_submit.py#L70)-[`130`](../../r2/host_hardening/host_submit.py#L130)).

**Inference, bounded by those interfaces:** a spatial consumer could be added
upstream of `PromptPlan`/`DefaultPromptCompiler`, but the inspected interfaces
do not currently carry typed spatial constraints or resolve a binding snapshot.
Passing spatial data through either path would require a contract and
integration change; this note does not define either one.

## DramaClaw 360 consumer fact

DramaClaw's `scene_360_builder` demonstrates an actual static consumer of a
spatial artifact. When master and reverse references exist, it loads the spatial
contract, generates direction and topology guide references, and passes the
loaded contract's prompt insert to `build_prompt`
(`b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83:src/novelvideo/director_world/scene_360_builder.py:894-984`).

In automatic mode, `load_scene_spatial_contract` returns no insert if the file
is absent, stale against inputs, malformed, or schema-version-mismatched; on
success it returns only `pano_prompt_insert`
(`b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83:src/novelvideo/director_world/scene_360_builder.py:718-751`). `build_prompt` places that insert under `SCENE SPATIAL CONTRACT` when
both views are present
(`b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83:src/novelvideo/director_world/scene_360_builder.py:275-287`); it also treats an optional spatial-layout image as geometry/layout
ground truth in its reference instructions
(`b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83:src/novelvideo/director_world/scene_360_builder.py:216-243`).

The donor therefore consumes a file-derived prompt fragment and optional image
reference during scene-generation request construction. Static inspection does
not show this as a versioned production-binding read, nor does it establish an
R2 persistence or authority mechanism.

## What the locked M8 material requires

The M8 design assigns `SpatialCandidate` to the `PRODUCTION_BINDING` target and
states that the target means an existing R2 production-binding authority rather
than the contract class alone; missing or non-atomic authority stops the work
([`docs/superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md:524`](../superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md#L524)-[`541`](../superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md#L541)). It also says spatial model calls are bounded M7 executions, spatial
evidence preserves its classifications and locks through serialization,
revision, preview, and promotion, and a promotion adapter may not turn gaps
into facts ([`docs/superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md:646`](../superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md#L646)-[`658`](../superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md#L658)).

The M8-C plan separately fixes the initial scope at evidence-preserving
normalization and candidate revisions, says no direct `ProductionBinding` or
master write, and makes C2 a later execution/promotion step
([`docs/superpowers/plans/2026-09-13-r2-m8c-spatial-candidates.md:5`](../superpowers/plans/2026-09-13-r2-m8c-spatial-candidates.md#L5)-[`37`](../superpowers/plans/2026-09-13-r2-m8c-spatial-candidates.md#L37)). ADR-0095 makes the operational prerequisite explicit: M8-A refuses the
binding target without writes; a persistent CAS-versioned binding authority is
required for `SpatialCandidate` promotion, while candidate validation/append
may proceed without it ([`docs/adr/0095-m8a-defers-the-production-binding-promotion-target.md:37`](../adr/0095-m8a-defers-the-production-binding-promotion-target.md#L37)-[`49`](../adr/0095-m8a-defers-the-production-binding-promotion-target.md#L49), [`62`](../adr/0095-m8a-defers-the-production-binding-promotion-target.md#L62)-[`68`](../adr/0095-m8a-defers-the-production-binding-promotion-target.md#L68)).

Locked `R2-DEC-031`, as instantiated for selected M8 donor surfaces, requires a
machine-readable `DonorParityContract` containing the exact donor revision and
surface, behavior/test/fixture inventory, same-fixture differential evidence,
quality/resource dimensions, exact integrated HEAD, commands, required skips,
and independent review. Every material row must be `PARITY` or `IMPROVED`; an
intentional donor correction needs a regression fixture, and missing source
execution, material verification, required skips, or HEAD binding blocks the
capability packet ([`docs/adr/0079-m8-integrated-exploration-learning-format-kernel.md:61`](../adr/0079-m8-integrated-exploration-learning-format-kernel.md#L61)-[`70`](../adr/0079-m8-integrated-exploration-learning-format-kernel.md#L70)).

## Comparison of the two stated paths

| Path | Directly supported by current facts | Requirement or unresolved item shown by current sources |
| --- | --- | --- |
| A. Persistent `ProductionBinding` plus typed `SpatialConstraintSet` and a production consumer | The current binding-read locations provide concrete potential snapshot consumers: readiness uses binding identity and content fingerprints serialize binding content. The prompt/compiler and M7 request seams identify where a generation consumer would need to receive semantic constraints. The donor provides an example of spatial data affecting a generated request. | `ProductionBinding` has no spatial field, and the current prompt/compiler/M7 request interfaces do not carry one. ADR-0102 is **proposed**, says this path needs a typed immutable constraint set, an exact reference/digest on a binding version, and a consumer that uses it; it also says neither path is accepted and requires a sponsor decision plus a checked consumer/read path ([`docs/adr/0102-production-binding-is-a-versioned-production-authority.md:17`](../adr/0102-production-binding-is-a-versioned-production-authority.md#L17)-[`24`](../adr/0102-production-binding-is-a-versioned-production-authority.md#L24)). |
| B. Candidate-only spatial evidence plus roadmap amendment | Current contracts, M8-C C1 scope, and the refusal path support retaining validated `SpatialCandidate` revisions without a binding write. This preserves visible/inferred/gap and lock evidence in the candidate payload. | It does not satisfy the design's current `SpatialCandidate -> PRODUCTION_BINDING` promotion target or C2 promotion wording. ADR-0102 describes this as an interim scope that leaves promotion unavailable and requires a roadmap amendment so M8-D is not described as starting from accepted M8-C ([`docs/adr/0102-production-binding-is-a-versioned-production-authority.md:21`](../adr/0102-production-binding-is-a-versioned-production-authority.md#L21)-[`24`](../adr/0102-production-binding-is-a-versioned-production-authority.md#L24)). |

## Unknowns and limits

- No inspected source establishes which existing readiness/fingerprint caller is
  an end-user production flow, or a concrete production-generation consumer of
  spatial constraints. The cited evaluator and fingerprint function are direct
  code readers; the observed constructors are fixtures/preparation values.
- No current `ProductionBinding` persistence writer, binding snapshot resolver,
  or typed spatial-constraint reader was found in the bounded searched runtime
  paths. This is a bounded literal-search observation, not a whole-repository or
  runtime-proof claim.
- The donor consumer was inspected statically only. Its file-based freshness and
  prompt-injection behavior cannot establish parity, success under provider
  execution, or an R2 authority design. Any selected donor-derived behavior
  remains subject to the R2-DEC-031 evidence requirements above.
- ADR-0102 is a proposal, not an accepted decision. Its storage, CAS,
  transaction, authorization, wire-contract, and migration statements are not
  adopted by this note.
