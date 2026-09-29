---
status: accepted
---

# M8 uses an integrated port-accelerated exploration, learning, and format kernel

M8 shall extend the ArcReel host with one integrated, provider-neutral capability
kernel rather than importing a second donor application or creating independent
Canvas, Learning, Spatial, or Format services. The kernel owns typed exploration
candidate revisions, preview-bound promotion, lineage-bound observations and
recommendations, and format-projection evidence. ArcReel remains the application
host; PostgreSQL remains durable authority storage; existing Production Authority
remains the only path to an ApprovedMaster; M7 remains the execution, receipt,
resource-control, and recovery substrate.

DramaClaw behavior shall be selectively ported where source inspection found
high-value graph, history, grouping, bookmark, save-coordination, recovery, payload
limit, and spatial-normalization behavior. OpenMontage composition, crop,
validation, and replay mechanics shall be adapted behind R2 ports. Donor filesystem
authority, project/provider/billing shells, auto-commit and direct push behavior,
and parallel runtimes shall not cross the stable R2 boundary. React Flow,
analytics adapters, spatial providers, Remotion, and FFmpeg remain replaceable
adapters; candidate identity, lineage, promotion, observations, and evaluation
remain stable R2 contracts.

Canvas state and browser recovery data are never Production Truth. A promotion
consumes an immutable candidate revision and a non-expired `PromotionPreview`
that binds its payload digest, target, expected current parent or master, complete
impact, and authorization scope. The server revalidates every binding in the
same short transaction that records idempotent promotion evidence and invokes
the existing authority adapter. A changed candidate, target, parent, scope,
preview, or authorization fails closed. Spatial inference remains a
`SpatialCandidate`; visible evidence, inferred regions, gaps, locks, confidence,
and execution fingerprints are preserved instead of being collapsed into fact.

Learning stores source-specific immutable `LearningObservation` records and
append-only correction lineage. Normalization preserves the raw metric identity,
window, platform artifact, retrieval semantics, profile/policy/content lineage,
format, transformation version, missingness, and experiment design. It emits
scoped, expiring `LearningRecommendation` proposals with evidence and Human
disposition. Recommendation acceptance may create a separate governed proposal;
it cannot mutate Canon, NarrativePlan, CreativePolicy, routing defaults, Claim
truth, production artifacts, or governance.

Generic Western and Chinese short-drama `zh-shuang` observations, rubrics,
recommendations, evaluations, and holdouts remain sibling cohorts over shared
mechanics. Pooling is explicit and allowed only when metric semantics, content
class, output format, audience window, and declared policy are compatible.
Profile identity, policy digest, content basis, reviewer evidence, and disagreement
remain visible throughout the lineage.

Multi-format output is a projection from an exact ApprovedMaster:
`ApprovedMaster -> FormatProjectionPlan -> M7 RenderExecution ->
TechnicalValidationReport + SemanticParityReport -> FormatCandidate -> PROMOTE`.
Resize, pad, and cover mechanics may be deterministic. Cropping, tracking,
caption relocation, timing, shot replacement, or text changes that can alter
meaning are explicit reframe decisions and require semantic review. Independent
generation per aspect ratio creates a new production candidate lineage rather
than masquerading as a projection.

Every selected donor surface is governed by locked `R2-DEC-031` through a
machine-readable `DonorParityContract`. It records the exact donor revision,
selected and reachable surface, runtime, behavior inventory, donor tests and
fixtures, intentional differences, same-fixture differential results, quality
dimensions, resource measurements, integrated HEAD, commands, required skips,
and independent review. An imported behavior is accepted only when every material
row is `PARITY` or `IMPROVED`; a corrected donor defect requires a regression
fixture. Missing source execution, unverified material behavior, required skips,
or an unbound integrated HEAD blocks the capability packet. Licensing is outside
M8 selection, scoring, rejection, and sequencing by sponsor direction.

## Considered options

- A wholesale DramaClaw/OpenMontage enclave was rejected because raw copied
  volume retains donor coupling while R2 must still replace persistence,
  authority, execution, identity, and audit semantics.
- A minimal native rewrite was rejected because it discards the donor's inspected
  concurrency, recovery, history, graph, spatial, rendering, and adversarial-test
  value without a compensating authority benefit.
- Separate capability microservices were rejected because no measured workload
  requires them, while they duplicate M7 control and introduce distributed
  ordering, idempotency, and schema-evolution failure surfaces.

## Consequences

- M8 is delivered as six independently accepted packets: shared exploration and
  promotion, Canvas, Spatial, Learning, Multi-format, and integrated utility.
- Packet probes can replace a graph, provider, analytics, or render adapter
  without weakening the stable authority contracts.
- “Quality greater than or equal to donor” applies to each selected reachable
  donor surface, not to unrelated features intentionally outside M8.
- Implementation starts only from an accepted, clean M7 lineage. A design branch
  containing M7 documents is not implementation evidence.
- This ADR authorizes M8 specification and implementation planning only. It does
  not authorize code implementation, migrations, provider/platform calls,
  credential use, runtime activation, deployment, publication, or production
  approval.
