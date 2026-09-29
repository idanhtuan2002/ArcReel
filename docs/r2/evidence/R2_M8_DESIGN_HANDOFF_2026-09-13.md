# R2-M8 design handoff — 2026-09-13

Status: `DESIGN_COMPLETE / IMPLEMENTATION_NOT_AUTHORIZED`

## Accepted direction

The sponsor accepted Alternative A, the port-accelerated integrated capability
kernel, on 2026-09-13. Licensing is outside M8 selection, scoring, rejection and
sequencing. Locked `R2-DEC-031` remains mandatory: every selected donor surface
must prove capability and quality greater than or equal to its exact source.

Design lineage:

- M7 design handoff: `5d81d833`;
- M8 research checkpoints: `619d8678`, `9a7a6411`, `81625dcc`, `bcd6e2fa`;
- research gate closed: `7d6f4f18`;
- architecture proposal: `66a322d0`;
- accepted ADR/glossary: `f00f2005`;
- accepted design spec: `d0fa883a`;
- umbrella implementation plan: `a38696a6`;
- six Claude Code execution packets: `268e82dc`.
- independent contract-review remediation: `4b2e8e59`.
- normative review validators: `59d8ae94`.
- non-interactive M8-A execution packet: `76cd3150`.
- evidence-head field alignment: `6a5107b3`.

## Authoritative design artifacts

- Research:
  `docs/research/2026-09-13-r2-m8-reuse-first-comprehensive-research.md`
- Accepted options record:
  `docs/research/2026-09-13-r2-m8-architecture-options.md`
- ADR:
  `docs/adr/0079-m8-integrated-exploration-learning-format-kernel.md`
- Specification:
  `docs/superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md`
- Umbrella plan:
  `docs/superpowers/plans/2026-09-13-r2-m8-canvas-learning-multiformat.md`
- Packets:
  - `docs/superpowers/plans/2026-09-13-r2-m8a-exploration-promotion.md`
  - `docs/superpowers/plans/2026-09-13-r2-m8b-creative-canvas.md`
  - `docs/superpowers/plans/2026-09-13-r2-m8c-spatial-candidates.md`
  - `docs/superpowers/plans/2026-09-13-r2-m8d-learning-recommendations.md`
  - `docs/superpowers/plans/2026-09-13-r2-m8e-multiformat-projection.md`
  - `docs/superpowers/plans/2026-09-13-r2-m8f-integrated-utility.md`
- Review-remediated document hash manifest:
  `docs/r2/evidence/R2_M8_DESIGN_MANIFEST_2026-09-13.json`
- Non-interactive execution contract:
  `docs/r2/evidence/R2_M8_EXECUTION_CONTRACT_2026-09-13.json`

The 2026-09-12 M8 checkpoint is historical and superseded as a live handoff.

## Independent review disposition

All eleven findings in the 2026-09-13 contract review were verified as valid
and resolved before implementation. The amendment locks frozen extra-forbid
Pydantic v2 contracts, discriminated Canvas/Spatial/Format candidate payloads,
the full payload-digest domain, explicit project scope, separate preview-command
idempotency, a normative transaction lock order, CandidateHead version rules,
browser-only seven-day pruning, a closed promotion-target/version universe and
a maximum one-hour preview TTL. The plan and affected packets now carry the same
schema, scope, locale, accessibility, benchmark and review-pre-registration rules.

The M8-A packet now fixes its owned paths, API routes/request models, database
tables/constraints, digest domains, error mapping, RED/GREEN commands, PostgreSQL
proof, evidence schema and parent-HEAD convention. Claude Code receives no
architecture choice: a missing accepted M7 base, atomic seam, disposable
PostgreSQL proof or allowlisted path produces a stop receipt instead of a question
or substitute implementation. B-F remain intentionally unreleased until the
preceding packet is independently accepted; their human-owned inputs are listed
in the execution contract and fail closed when absent.

## Non-negotiable implementation gates

1. Implementation begins only in a new worktree from independently accepted,
   clean M7 implementation at Alembic head `7b7c4a0e0001`.
2. M8-A runs first and fails before writes when prerequisite lineage, migration,
   document, seam or donor evidence differs.
3. A machine-readable `DonorParityContract` instantiates `R2-DEC-031`. Every
   applicable dimension is `PARITY` or `IMPROVED`; required skips, material
   unknowns, source drift or a non-current integrated HEAD block acceptance.
4. Canvas, Spatial, Learning and Format remain non-authoritative. Production
   changes use preview-bound explicit promotion through existing authority.
5. Generic Western and `zh-shuang` evidence remain separately identifiable,
   evaluated and held out. No implicit pooling is allowed.
6. Every packet ends at a clean evidence HEAD and waits for independent Codex
   review. Claude Code does not begin the next packet early.

## Preserved unrelated work

The following pre-existing dirty files remain outside M8 scope and must not be
staged, reverted or edited by an M8 executor:

- `AGENTS.md`
- `docs/superpowers/plans/2026-09-09-r2-m5c-narrative-lifecycle.md`
- `docs/superpowers/specs/2026-09-09-r2-m5c-narrative-lifecycle-design.md`

## Verification performed

- Documents were checked for non-empty presence and cross-document canonical
  type/stop-code references.
- Placeholder scan found no incomplete implementation instruction.
- `git diff --check` passed after every checkpoint.
- No implementation code, migration, runtime, provider/platform call, credential,
  deployment, publication or production operation was performed.

## Exact next action

Do not execute M8 from this design branch. Once M7 implementation is independently
accepted, create a clean M8 worktree from that exact HEAD and give Claude Code only
the ADR, spec, umbrella plan, execution contract and M8-A packet. The base must be
the commit containing `R2_M7_IMPLEMENTATION_ACCEPTANCE.json`, whose parent is the
accepted M7-E candidate HEAD. M8-A Task A0 must establish the new baseline before
any implementation file is created; failed checks emit the defined stop receipt
and do not invite architecture changes.
