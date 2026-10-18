# R2 V2 story release — amendment to the idea-to-story plan

Status: DRAFT_FOR_HUMAN_REVIEW. Amends `docs/superpowers/plans/2026-10-17-r2-idea-to-story-authoring.md` (approved 2026-10-17). Everything in that plan stays in force unless this document changes it. Research basis: `docs/research/2026-10-18-r2-v2-story-release-research.md` (commit `a2184771`).

**Goal:** Release V2 = V1 + an automated idea → complete Vietnamese short story flow. The output is an exported manuscript that can also continue into the existing video flow. Run on local Ollama first, then take it to real operation.

## Decisions recorded (sponsor, 2026-10-18)

- Base: `r2-v2/main` `23cf146a` lineage, worked on `design/r2-story-authoring`. M9 is excluded.
- Integrate existing owners only. Glue code is authorized; no redesign and no change to accepted ADRs.
- Model: `ornith:9b` on local Ollama through the existing custom provider `openai_chat` endpoint. Claude and OpenAI stay fixture-qualified only until they are configured.
- Story: one Vietnamese short story, three chapters, visible ending, with explicit limits. Long-form is out of scope (ADR-0089 §8).
- Quality: commercial grade. Defects attributable only to the local model's limits are accepted and recorded as such.
- Human touchpoints are kept to the governance minimum (R2-DEC-001, ADR-0089):
  - Story: **3** — idea + Gate A, outline approval, manuscript acceptance.
  - Video: **3** — Gates B, C and D.
  - Everything between touchpoints runs without a human.

## Change 1 — close Task0 with the recorded owner-map amendment

Add to the owned file map the paths that `R2_STORY_AUTHORING_QUALIFICATION.md` proposes:

- `lib/db/repositories/task_repo.py`: a dedicated guarded text-task checkpoint transition. Video checkpoint methods and guards stay unchanged.
- `lib/ledger.py`: optional explicit input/output token quantities passed into the existing `PricingParams`. Existing callers keep their defaults.
- `lib/budget_guard.py`: enforce an explicitly authorized authoring run/step ceiling in every release mode. Legacy DEV behaviour stays unchanged. Missing pricing refuses a paid call; a local provider still enforces token/call ceilings.
- Tests: `tests/integration/lib/db/repositories/test_task_repo.py`, `tests/integration/lib/db/repositories/test_task_command_idempotency.py`, `tests/integration/lib/test_budget_guard.py`, `tests/unit/lib/test_ledger.py`, `tests/unit/lib/test_text_generator.py`.

No new table, migration, governance authority, frozen R2 contract or capability-profile change.

## Change 2 — Ollama is the first live provider

- Task1 qualifies the custom provider `openai_chat` backend against Ollama `/v1/chat/completions`. It checks the exact request, the `finish_reason` (`stop`/`length`), usage tokens, timeout, cancellation and an unavailable endpoint. It does so with transport fixtures, then with one live probe.
- Default limits for `ornith:9b`, fixed in `StoryLimits` defaults and editable by the operator:

  | Limit | Default |
  |---|---|
  | Output per call | 2,048 tokens |
  | Input per call | 16,384 tokens |
  | Provider calls per run | 3 chapters × (1 write + 1 repair) + 1 outline + 1 review per chapter = 10 |
  | `max_repairs` | 1 per chapter |
  | Cost | 0 minor units with currency `LOCAL` |

- Mixed-script output (CJK characters inside Vietnamese prose) is a deterministic local check that marks the chapter for the bounded repair.
- There is no cloud fallback. A down local endpoint gives a visible, resumable "model unavailable" state.

## Change 3 — automation between Human touchpoints

Task4's orchestration becomes an automatic run.

1. **Touchpoint 1 (Gate A).** One form takes the idea, genre, chapter count and limits. Its submit button records Gate A greenlight through the existing `POST /gates/greenlight`, bound to the digest of the exact idea text, and enqueues outline generation.
2. **Automatic.** The outline is generated and validated locally against its JSON schema. An invalid outline gets at most 1 regeneration within limits.
3. **Touchpoint 2.** The Human approves (or edits, then approves) the outline. This records the real `NarrativePlanApproval` through `NarrativePlanService`.
4. **Automatic, sequential per chapter.** For each chapter:
   - compile the context;
   - generate the chapter;
   - run the deterministic checks: termination, length window, mixed-script, coverage of the outline beats, ending present in the last chapter;
   - run the M5C `continuity_rules`;
   - run one model "literary review" pass whose findings are advisory;
   - if any blocking finding remains, run at most `max_repairs` repairs;
   - store every output as an immutable R2 draft candidate/revision.

   The run stops visibly, keeping every saved chapter, when limits are exhausted or the outcome is unknown.
5. **Touchpoint 3.** The Human reads the assembled manuscript with its findings and accepts it, optionally editing it first. One click records a narrative acceptance decision per selected revision through `NarrativeAcceptanceService` with the real Showrunner authority adapter. If Task3 proves that a multi-decision command is not supported, the client sends the per-chapter decisions sequentially from that single click; each decision is still Human-bound to its exact revision.
6. **Automatic.** The accepted manuscript is exported as Markdown through host artifacts, with exact revision IDs.

A run never approves anything by itself. Model reviews are recommendations (ADR-0089 "automatic QA score" is not an approval).

## Change 4 — hand-off into the video flow

Add `StoryAuthoringService.send_to_video(scope, manuscript_ref, command_id)`. It calls the existing `server/tool_runtime.py::upload_source` with the exported `.md` and `on_conflict` set explicitly. The project's existing novel-source pipeline (episode planning → script → storyboard → video) then runs unchanged, followed by Gates B–D as today. The project must already be `source_kind=novel`; nothing changes in the video pipeline. The UI offers this as one button after acceptance. Pressing it is not a gate; it only copies bytes into `source/`.

Owned additions: `server/story_authoring/handoff.py` and `tests/unit/server/story_authoring/test_handoff.py`.

## Change 5 — release and real operation (new Task7)

After Task6 acceptance:

1. Merge `design/r2-story-authoring` into `r2-v2/main`. Annotate the release tag `r2-v2.0.0` on the exact accepted commit (ADR-0089 §7 lineage rule). Push only with Human confirmation.
2. Take a pre-upgrade backup of the V2 staging environment (`~/arcreel-v2-staging`) using `docs/r2/runbooks/m7-backup-restore.md`. Deploy the tag, run `alembic upgrade head` (expected: no new revision), register the Ollama custom provider, and run one live three-chapter story plus the video hand-off.
3. Write the operator runbook `docs/r2/runbooks/story-authoring.md`: setup, the 3+3 touchpoints, resume, limits, the model swap to cloud later, and backup coverage of the authoring artifacts.
4. Production activation (outward-facing) happens only on explicit Human confirmation at that time.

## Acceptance additions

- One live `ornith:9b` run from idea to an exported three-chapter manuscript with an ending. Zero Human actions besides the three touchpoints are needed, and a restart in the middle of chapter 2 resumes without regenerating chapter 1.
- The quality record lists every deterministic, continuity and review finding, each marked fixed, open, or "local-model limit".
- The sponsor reads the manuscript; their acceptance at touchpoint 3 is the quality verdict.
- The video hand-off creates `source/<story>.md`, and the existing episode-planning step accepts it.
- Regression: the affected-domain static gates plus the related tests listed in each task. PostgreSQL interleavings for the checkpoint/budget changes. No full suite unless asked.

## Execution

Main agent, inline and serial, in the order: Task0 close → Task1 → Task2 → Task3 → Task4 (with Changes 3 and 4) → Task5 → Task6 → Task7. One progress report per task gate; one final independent review (Codex) and at most one repair.
