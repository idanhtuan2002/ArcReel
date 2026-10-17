# R2 Idea-to-Story Authoring Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` inline, task by task. Do not dispatch per-task implementers or reviewers. The Human's quota and bounded review preferences take precedence over generic review loops. Implementation starts only after review of this plan and selection of execution method.

**Goal:** Deliver one authenticated user path from an idea through an explicitly selected outline to a complete, persisted and editable Vietnamese short story, using Claude, an OpenAI model or a qualified local model.

**Architecture:** Compose the existing host provider, Ledger, task/execution and project-artifact owners with the existing R2 Canon, NarrativePlan, ContextCompiler and Narrative-lifecycle owners. Runtime progress is a projection of existing tasks and saved evidence; no second story database, scheduler, credential store or Canon writer is introduced. Qualify missing composition seams before exposing them as available.

**Tech Stack:** Existing Python/FastAPI/Pydantic/SQLAlchemy/PostgreSQL, React/TypeScript/Vite, uv and pnpm. No new dependency or schema migration is authorized by default.

**Spec:** `docs/superpowers/specs/2026-10-17-r2-idea-to-story-authoring-design.md`, approved by Human `duyệt` after spec commit `85a2611ccca830f095b16d7abe1b88301e8bce7b` on 2026-10-17. Its historical DRAFT label stays unchanged; this approval record is separate.

## Global Constraints

- Worktree `/home/anhtuan/content-production-os/.worktrees/r2-story-authoring`, branch `design/r2-story-authoring`; implementation continues in this isolated worktree after plan approval. Baseline code `39b9c5dab5d0fd56cf52bf65e95355437cb1023b`. Preserve M9-B clean `bba1bd9622eb4423160c771f4dde2dc927b58f0a` and all root dirty work.
- Initial acceptance is one Vietnamese story with three chapters and a visible ending. Runtime limits are explicit inputs, not a promise to generate arbitrary-length novels. Provider IDs/model IDs come from real configuration; no default paid call.
- Real authenticated owner/project/actor and exact approved Canon/Plan/Scene/Context bases are required. Generated outlines and prose never mint their own Human decisions. No fake IDs, owner-equals-Showrunner assumption, or test authority in runtime.
- One configured provider/model per step; no automatic cross-provider or local-to-cloud fallback. Credentials remain host-owned and never appear in browser storage, output provenance or logs.
- Save every completed chapter; immutable versions remain retrievable after restart. Unknown paid outcomes must not be blindly replayed. No transaction spans model or filesystem I/O.
- Enforce input/output, call-count, repair and cost ceilings before dispatch; count transport/fallback attempts as well as application calls. Unknown cost is not zero. Reject truncated or unterminated output as complete.
- A maximum of one independent final acceptance review and one evidence-driven repair. No per-task or automatic re-review loop. Main agent retains authority for security, transactions and acceptance.
- No production deployment/migration, provider activation, push, merge or public release. A live demonstration requires configured endpoint/model, credentials and an explicit bounded spend authorization; fixtures alone cannot qualify live access.
- All new user-visible strings have en/vi/zh keys. Reuse host UI and storage. Keep port5173 untouched; use5174 with strictPort if available.

## Review Focus

1. Two browser tabs submit or revise the same chapter: one exact result per command, stale expected revision rejected (Tasks2,3,5).
2. Provider responds, then persistence fails or process exits: recover retained output without another paid submission; previous chapters survive (Tasks2,4).
3. Provider ignores schema or terminates at token limit: incomplete output is visible and never exported as a complete chapter (Tasks1,4).
4. Model configuration or approved outline changes mid-run: in-flight step retains exact route/bases; later steps require fresh selection/context (Tasks1,3,4).
5. A local endpoint is unavailable or cancellation arrives during submit: no cloud fallback, no hidden resend and no lost saved chapters (Tasks1,2,4).

## Source-traced reuse and qualification limits

Verified call surface: `TextGenerator.create/generate` -> `create_text_backend_for_task` -> host assembly/configuration and Ledger; `TaskRepository.enqueue` accepts string task types and actor-scoped command receipts; `generation_worker._execute_task` dispatches through `generation_tasks.execute_generation_task`; text-prefixed tasks currently enter `tool_runtime.execute_queued_text_task`. Authoring uses explicit `story_authoring_*` task types in the existing executor map, rather than pretending to be a legacy script task.

`TaskRepository.enqueue` commits internally and can roll back after a dedupe conflict. Do not compose it inside an assumed atomic R2 transaction. `NarrativePlanService.commit_revision` requires an exact approval; `NarrativeContextCompiler.compile` needs exact readers; `NarrativeShowrunnerAuthorityPort` denies by default and needs a real host authority adapter. `CurrentShowrunnerGrantReader` alone does not establish a compatible Narrative grant scope.

Existing `TextGenerationResult` has text/model/usage but no finish reason; plain-text truncation currently only logs. `TextGenerator` records usage but does not itself enforce a whole-story cap. Existing `ArtifactKind` has no narrative outline/manuscript kind. These are concrete additive gaps, not already-available interfaces.

Graph evidence: predecessor `r2-v2-main`, fast Tier2 generation2026-10-15T01:19:44Z, material paths coverage-checked. Direct source read covered changed advanced_creative router, excluded docs/tests and runtime profile. New worktree is not indexed; verify its own source and refresh coverage before implementation. Prior12 evidence-service tests are historical baseline, not an authoring acceptance run.

## Owned file map

Create:
- `server/story_authoring/__init__.py`, `contracts.py`, `generation.py`, `runtime.py`, `narrative.py`, `artifacts.py`, `service.py`: focused host composition modules; their interfaces are fixed below.
- `server/routers/story_authoring.py`.
- `frontend/src/features/story-authoring/api/storyClient.ts`, `ui/StoryAuthoringPage.tsx`, `ui/story-authoring.css`.
- `docs/r2/evidence/R2_STORY_AUTHORING_QUALIFICATION.md`, `R2_STORY_AUTHORING_ACCEPTANCE.json`; `docs/r2/runbooks/story-authoring.md`.
- `tests/unit/server/story_authoring/test_generation.py`, `test_contracts.py`, `test_artifacts.py`, `test_service.py`; `tests/unit/server/routers/test_story_authoring.py`.
- `tests/integration/server/story_authoring/test_runtime.py`, `test_narrative.py`, `test_resume.py`.
- `frontend/src/features/story-authoring/ui/StoryAuthoringPage.test.tsx`, `api/storyClient.test.ts`.
- `tests/e2e/test_story_authoring.py` for the explicitly enabled model/browser demonstration; default CI never calls a provider.

Modify only where the qualification proves it necessary:
- `lib/text_backends/base.py`, `openai.py`, `lib/text_generator.py`, `lib/text_backends/instructor_support.py`, `lib/custom_provider/backends.py`, `lib/custom_provider/endpoints.py`: opt-in authoring limits, termination and bounded transport/fallback exposure. Existing defaults remain compatible.
- `lib/generation_queue.py`, `lib/generation_worker.py`, `server/services/generation_tasks.py`: additive authoring task dispatch/admission/restart routing; no second queue.
- `lib/artifact_manifest.py`, `lib/artifact_registration.py`, `lib/artifact_currency.py`: additive outline/manuscript artifact kinds and exact-basis validation.
- `server/app.py`, `frontend/src/router.tsx`, `frontend/src/app-routes.ts`, `frontend/src/components/pages/ProjectSettingsPage.tsx`: authenticated composition and one discoverable project entry.
- `lib/i18n/{en,vi,zh}/errors.py`, `frontend/src/i18n/{en,vi,zh}/workflow.ts`, `frontend/src/i18n/types.ts`: supported locale strings/types; no extra namespace needed.
- Corresponding existing `tests/unit/lib/test_text_generator.py`, `tests/unit/lib/text_backends/test_base.py`, `test_openai.py`, `test_factory.py`, `tests/unit/lib/test_generation_queue.py`, `tests/unit/lib/test_artifact_manifest.py` and `tests/unit/server/services/test_generation_tasks.py` only for changed shared behavior.

No Alembic, R2 public contract, accepted donor, governance registry or capability-profile edits are authorized by this map. If Task0 proves one necessary, record the precise incompatibility and return that bounded design change; do not widen scope silently. New dependency/native Anthropic transport similarly needs an explicit revised path decision before code. Do not claim feature completion while such a gate is open.

## Task0: Qualify host composition before implementation

**Files:** Create `docs/r2/evidence/R2_STORY_AUTHORING_QUALIFICATION.md`; read exact reused source and relevant existing fixtures.

**Consumes:** approved spec, fixed baseline, existing task/model/artifact schemas, provider settings, authority and execution contracts.
**Produces:** `READY_WITHIN_OWNED_MAP` or named `DESIGN_GAP` findings, each with exact source paths and a native reproducer. This is evidence, not runtime authority.

- [ ] Pin live HEAD/status; source-trace task enqueue/claim/dispatch, dedupe, restart and paid admission. Probe an additive authoring task in an isolated database with the existing queue and no network. Confirm the public DTO accepts text tasks.
- [ ] Qualify exact production Canon/Plan/Scene/context readers and Human-approval bootstrap. Reuse actual grant scope/custody rules; test missing and mismatched authorization refuse before model dispatch. Identify a real path for a new project to receive its initial approved bases.
- [ ] Trace provider profile, budget, SDK retry and fallback behavior. Check that a synchronous text execution can use the existing host admission/checkpoint owners without fabricated provider-job identity. Otherwise record `TEXT_EXECUTION_CUSTODY_GAP` and stop before runtime code.
- [ ] Prove existing host project/manifest storage can own outline, pending returned bytes and selected manuscript with additive kinds; no separate authoritative run file/database. Check backup/restore inventory includes these files.
- [ ] Record exact fixture paths and source hashes. Selected donor baseline covers parsing/continuity only; no donor writer parity is inferred. Run only the narrow probes required to close the observed gaps, retain native outputs, then commit this evidence file.

## Task1: Qualify selectable text generation and finite call limits

**Files:** Create `server/story_authoring/contracts.py`, `generation.py`, `__init__.py`, their unit tests; modify the listed text modules and existing tests where required by Task0.

**Produces:** frozen `StoryScope(user_id,project_name,actor_id)`, `StoryLimits(chapters,max_input_tokens,max_output_tokens,max_provider_calls,max_repairs,max_cost_minor_units,currency)`, `StoryModelSelection(provider_id,model_id,config_digest)`, `StoryStepRequest(step_id,kind,context_digest,prompt,selection,limits)`, and `StoryStepOutput(text,provider_id,model_id,finish_reason,usage,request_digest)`. `kind` is OUTLINE/CHAPTER/CONTINUITY/REPAIR. Minor units and token/call ceilings must be positive finite integers; max_repairs may be0. No unspecified implicit paid budget. Token limits are tokens, text length is Unicode characters and monetary ceilings use the configured currency minor unit; never treat word count as token count. Store an explicit pricing/version reference for cloud estimates; unknown pricing disables paid admission. Local token/call limits remain mandatory even when cloud charges are not applicable.

`AuthoringTextGateway.generate(*,scope:StoryScope,request:StoryStepRequest)->StoryStepOutput` is the only application-level generation seam. It consumes a frozen resolved route; it does not silently re-resolve another model after an error. Shared `TextGenerationResult.finish_reason: str|None = None` is an additive field; the authoring gateway requires a qualified non-truncated termination value, while old consumers retain defaults.

- [ ] Write RED tests: OpenAI/Claude-compatible/Ollama transport fixtures inspect exact requests; no credential leakage or cloud fallback; actual model provenance survives. Nonfinite/negative limits and changed config digest refuse. A truncated/unknown termination or invalid outline fails completion. Check the declared maximum includes backend and schema-fallback attempts, with max_repairs0 producing no extra call.
- [ ] Run `PYTHONPATH="$PWD" $R2_PYTHON -m pytest tests/unit/server/story_authoring/test_contracts.py tests/unit/server/story_authoring/test_generation.py -q`; expect missing feature/assertion failure, never import-environment failure counted as RED.
- [ ] Implement the gateway with existing TextGenerator/Ledger/config. Use locally validated JSON as outline output; do not rely on Anthropic response_format enforcement. Add opt-in attempt policy/termination propagation only where Task0 qualifies it. No direct unaccounted SDK call or hardcoded credential.
- [ ] Rerun the new tests and actual changed text-backend suites; confirm all pass and old behavior remains covered. Commit exact Task1 files.

## Task2: Persist runtime steps and host artifacts with recoverable publication

**Files:** Create `runtime.py`, `artifacts.py`, unit artifact tests and integration runtime tests; modify owned task dispatch/restart and artifact seams.

**Consumes:** Task1 contracts, actual existing host task/execution/artifact owners qualified by Task0.
**Produces:** `AuthoringRuntime.enqueue(*,scope,command_id,request:StoryStepRequest)->StepView`, `recover(*,scope,step_id)->StepView`, `AuthoringArtifacts.retain_output(*,scope,step_id,output:StoryStepOutput)->ArtifactRef`, `read_exact(*,scope,ref:ArtifactRef)->bytes`. Define immutable `StepView` and `ArtifactRef` in contracts.py; they expose exact IDs/digests/status, not credentials. Status is a projection, not a new authority table.

- [ ] Write RED scenarios: concurrent same command returns one task; different command content conflicts; two worker claims cannot both submit; process exit before submit/after response/after retained output/before final success. Restart recovers retained bytes without provider I/O; unresolved submit yields a visible OUTCOME_UNKNOWN projection and no automatic retry. Cross-project artifact refs, path traversal and symlink output refuse.
- [ ] Run new unit/integration tests on disposable targets, confirm RED. Implement typed payload/result envelopes in existing task fields, task-to-runtime dispatch and immutable host-artifact publication. Do not wrap the internally committing TaskRepository.enqueue in a fictitious outer transaction.
- [ ] Probe task cancellation and orphan-startup behavior: completed chapters survive, cancellation cannot requeue an uncertain call, saved response publication can finish without a new model request. Add PostgreSQL controlled interleavings for claim/finalization locks. No production DB.
- [ ] Rerun affected queue/worker/artifact suites; verify backup inventory includes retained outputs. Commit exact Task2 files.

## Task3: Bootstrap real Narrative bases and save/edit actual R2 drafts

**Files:** Create `narrative.py`, integration narrative tests; use existing R2 services/readers unchanged unless a separately approved gap changes the map.

**Consumes:** explicit authenticated Human decisions, selected outline artifacts, existing CanonTransactionService/NarrativePlanService/NarrativeContextCompiler/NarrativeLifecycleEvidenceService, and Task2 exact retained output. `decision` is a locally verified host envelope carrying the actual existing `NarrativePlanApproval` and any required Canon/bootstrap decisions; clients cannot submit an already-verified envelope. Define its typed `OutlineDecision` with authenticated actor and exact proposal/digest bindings in contracts.py. `expected_basis` is `AuthoringBasis | None`; IDs are strings, chapter_index is a positive integer and expected_revision_id is `str | None`.
**Produces:** `NarrativeAuthoring.prepare_outline(*,scope,outline_ref,decision,expected_basis)->AuthoringBasis`, `compile_context(*,scope,basis,chapter_index)->CompiledStoryContext`, `save_output(*,scope,basis,output_ref,expected_revision_id)->ChapterView`, `append_edit(*,scope,chapter_id,text,expected_revision_id,command_id)->ChapterView`. Define `AuthoringBasis`, `CompiledStoryContext`, `ChapterView` in contracts.py with exact immutable R2 IDs/digests.

- [ ] Write RED tests proving a new project's real Canon/Plan/Scene/context bases are resolved and saved candidates point to those actual rows. Missing grant, forged actor, model-created approval, changed outline, foreign bases and stale expected revision all refuse. Human outline selection must not auto-accept generated prose or Canon mutations.
- [ ] Run integration tests, expect feature failures. Implement host authority/read composition and legitimate bootstrap through existing owners; compile real context, normalize/hash/fingerprint through R2 helpers, then store candidates/revisions through NarrativeLifecycleEvidenceService. Do not import tests/factories at runtime.
- [ ] Verify exact reopen after disposing/recreating DB sessions. Concurrent edits preserve both immutable inputs but only a valid expected predecessor can become the selected revision. Label previous unaccepted draft context explicitly; never turn it into accepted Canon facts.
- [ ] Rerun changed-area R2 Narrative suites and commit. No generic Agent call is accepted as evidence that this binding exists.

## Task4: Orchestrate a finite complete manuscript and scoped API

**Files:** Create `service.py`, `server/routers/story_authoring.py`, service/router unit tests and integration resume tests; modify `server/app.py` and backend en/vi/zh errors.

**Consumes:** Tasks1–3 interfaces.
**Produces:** `StoryAuthoringService.propose_outline`, `select_outline`, `generate_next`, `revise_chapter`, `resume`, `read`, `export_manuscript`, each accepting authenticated scope and command/expected-version fields for mutations. Typed request/response classes live in contracts.py. Public outline input is `CreateOutlineRequest(command_id,idea,language,genre,limits,selection)`; outline decision is `SelectOutlineRequest(command_id,outline_ref,expected_outline_digest)`; chapter generation is `GenerateChapterRequest(command_id,chapter_index,expected_basis_digest)`; edits are `ReviseChapterRequest(command_id,text,expected_revision_id)`; resume is `ResumeStoryRequest(command_id,expected_state_digest)`. Resolve scope, actor, trusted prompt, approvals and context server-side, never from caller-supplied R2 identity claims. Provider changes are explicit request selection changes validated against configured scope and frozen only for new steps.

Expose under `/api/v1/projects/{project_name}/r2/story-authoring`: POST `/outlines`, POST `/outline-decisions`, POST `/chapters`, POST `/chapters/{chapter_id}/revisions`, POST `/resume`; GET `/state`, GET `/chapters/{chapter_id}/revisions/{revision_id}`, GET `/export`. Return task/result IDs for asynchronous steps. Human-only mutations use the existing interactive-auth dependency. Reads follow authenticated-read scope; foreign identities look absent.

- [ ] Write RED service/router tests: idea-to-outline waits for Human selection, exactly3 selected chapters can reach manuscript-ready, missing ending/coverage/truncation leaves incomplete, duplicate resume does not regenerate completed chapters, selected export bytes match stored exact revisions. Input revision drift invalidates the affected completion projection.
- [ ] Implement sequential orchestration on host tasks; freeze per-step route/bases and record honest provider/usage provenance. Require explicit new command/selection for regeneration. Continuity findings are recommendations; limit any repair by configured max_repairs and total call/cost ceilings. No new scheduler or free-running review loop.
- [ ] Simulate a connection loss after result retention and a browser reload after each chapter. Recover via exact saved refs. Return typed, localized errors for missing setup, budget, unavailable model, stale basis, unknown outcome and incomplete output. Never raw SDK exception strings.
- [ ] Run new service/router/resume suites and affected host auth/API regressions; commit exact Task4 files.

## Task5: Deliver the user-facing authoring page

**Files:** Create storyClient.ts, StoryAuthoringPage.tsx, story-authoring.css and corresponding tests; modify owned route/project-entry/i18n files.

**Consumes:** Task4 endpoints.
**Produces:** authenticated `/app/projects/:projectName/story-authoring`, reachable from the existing project settings/workspace entry. One page provides idea/model/limits, outline selection, chapter progress/editor/history, resume and text export. The API owns truth; UI state is a recoverable draft/selection projection.

- [ ] Read applicable frontend and React skills before UI implementation. Write RED browser/component tests for all user actions, two-tab stale edits, reload with unsaved text, unavailable local endpoint and API validation errors. Preserve typed input until a save succeeds; warn before leaving unsaved edits.
- [ ] Implement using existing host components, provider settings and request/auth helpers. Provider availability is per configuration and qualification; do not show all three as connected by default. Keep technical receipt IDs out of the primary writing flow unless needed for recovery.
- [ ] Add en/vi/zh translations and keyboard/label/focus behavior. Show COMPLETE only when the server confirms selected coverage/ending criteria; show outstanding findings separately from generated text. Do not equate a green network response with literary quality. Manuscript-ready means all selected chapters and the explicit ending section are present; record unresolved continuity findings and require operator review of narrative quality before any stronger acceptance claim.
- [ ] Run new component/client tests and full frontend `pnpm check`, backend i18n consistency and affected browser gates. Commit exact Task5 files.

## Task6: Demonstrate, verify and hand off one runnable result

**Files:** Create runbook, acceptance JSON and explicitly enabled e2e demonstration; reuse existing browser automation skill when executing the UI.

- [ ] Choose a supplied idea and configured provider/model in an isolated development data root. Record model limits and approved spend; absent credentials/spend is a LIVE_DEMO_PENDING gate, never a product pass. Use the3-chapter Vietnamese corpus, real Human outline decisions and actual stored R2 bindings.
- [ ] Demonstrate idea->outline->selected plan->three chapters->ending->edit->restart/reopen->exact export. Preserve source/model/config/context hashes, selected revisions, actual commands, logs and exported manuscript. Live status is separate for each provider; do not imply all three were run because fixtures pass.
- [ ] Run required affected-domain backend gate from AGENTS.md: Ruff check and format, basedpyright, lint-imports, deptry, full backend pytest when shared DB/contracts/fixtures require it, test audit and frontend pnpm check. Run migration roundtrip only if a separately approved schema change exists. Website check only if website changes. Tests must collect nonzero cases. Do not rerun unchanged successful gates without a new concern.
- [ ] One independent exact-candidate acceptance review, at most one repair; if a blocker remains after that repair, write a durable handoff instead of restarting a review loop. Main agent owns final acceptance, with implementation, live demonstration and production activation reported separately.
- [ ] Commit scoped evidence; record exact HEAD/status, disabled routes and resume commands. No push/deployment. Keep M9 and root dirty paths unchanged.

## Commands and execution handoff

Reuse the existing interpreter without a source-tree symlink:

```bash
R2_PYTHON=/home/anhtuan/content-production-os/.worktrees/r2-v2-main/.venv/bin/python
PYTHONPATH="$PWD" "$R2_PYTHON" -m pytest <task-owned-tests> -q
```

The angle-bracket test set is substituted from each task's exact Files list; it is not a literal executable command. Install no new dependency merely because this worktree lacks a local.venv. Use a disposable PostgreSQL target with a verified current ownership proof; never assume M9's old port/grant remains valid. Frontend launch after implementation uses `pnpm dev --port 5174 --strictPort`; verify availability first and follow the runbook for a separate backend/data root.

Inline self-review: spec requirements map to Tasks0–6; the five Review Focus scenarios have owning tasks; new types are defined in contracts.py and owned before consumption. Known unknowns are Task0 gates with explicit stop outcomes, not presumed available adapters. No code or new acceptance test has been authored by this plan. Only its source-grounded design and file map are offered for approval.

Recommended execution: Native/inline by the main agent, serially, reusing interface context and one final bounded review. This follows the Human's remaining-quota constraint. Do not choose per-task subagents by default.
