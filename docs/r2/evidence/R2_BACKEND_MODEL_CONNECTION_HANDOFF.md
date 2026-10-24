# Backend model connection — NOT IMPLEMENTED / NOT DEPLOYED

Checkpoint UTC: 2026-10-24T02:27:35.407947+00:00
Exact starting HEAD: `b2d65f757da4ff874bb42d1f81064ded52d66fbe`. Branch `feat/v2-explicit-text-backend`.
Managed worktree: `/home/anhtuan/.codex/worktrees/c1b3/content-production-os`.

## Sponsor's latest priority

Make models selectable and usable first through the common backend. Defer further billing/profile refinement and advanced UI. Quota5h near exhaustion. Do not spend the next session on more metering research or report backend connection complete from compiler/kernel tests. A Python constructor alone is not proof that the user can select and use the model through an application entrypoint.

## Actual status

- Backend connection is NOT implemented or deployed. Only its scope/spec/plan and new branch exist; no backend product file or backend test was changed/run in this step.
- Earlier independent pure work is committed: catalog, kernel and price compiler. Latest compiler source `b11709defb532de038d810715c424f7f9423f2ae`, evidence commit `9a6571aa3961ebc5661efb3c8c488b8050727821`. Its374tests/7statics/review do NOT prove backend connection or live provider usability.
- Native Gemini/Grok/OpenAI and other text adapters already exist in `lib/text_backends`, registered through `lib/backend_assembly/specs.py`. Do not build them again.
- `TextGenerator.create(task_type, project_name)` currently resolves project/task/global settings, calls factory/assembler, and uses the existing Ledger wrapper when generating. It has no explicit per-call provider/model arguments yet.
- Native Anthropic Messages text adapter is absent from current registry/specs. The Anthropic constant/Agent configuration does not supply a native text backend. Existing OpenAI-compatible custom gateways may serve such model IDs only when actually configured; do not claim native Claude support.
- Story Authoring remains deliberately custom Ollama-only: `_selection` in `server/story_authoring/service.py` rejects builtin/cloud routes. Do not remove this restriction alone: old brief digests, token counting, retries and budget/qualification semantics would be bypassed.
- One read-only GET of local1251model-candidates returned401. No credentials/config values were inspected, no provider generation call was made, no live cloud selection was verified.

## Concrete resume path

1. Read live Git status and this handoff first. Preserve the two untracked old Gemini drafts.
2. Check which existing user-facing/API selection path and masked provider configuration can already be reused; the live API needs authentication. A configuration/credential gap must not be misdiagnosed as a missing adapter. Do not print credentials or bypass authentication.
3. Scope packet: `docs/superpowers/specs/2026-10-24-explicit-text-backend.md` and matching plan. Proposed backend seam: exact create_text_backend_for_model plus explicit optional pair in TextGenerator.create, preserving default path, task vision policy, actual-model/fallback rejection, provider attribution, and existing release qualification. This packet is not implemented.
4. Ensure the chosen application/API entrypoint can actually select/use the route; deliver and test that entrypoint before claiming user usability. Shared-backend-first does not mean silently enabling cloud StoryBrief or creating an unguarded paid endpoint.
5. Reuse real assembler/config/ledger with constructor/SDK boundary fakes. Existing captured_backend_construction returns object() without `.model`, so it cannot alone test strict actual-model comparison; use a local model-bearing constructor fake or suitable SDK fixture, not a shared-fixture rewrite that forces unrelated full media tests.
6. Native/gateway routes require current configured credentials and existing qualifications. Retain these gates; don't route Claude text through Agent credentials. No migration, new financial framework, provider/model default rewrite or broad new research.
7. Run required affected checks, perform one final independent review and record code/runtime/deployment/live-provider statuses separately. Do not claim the user can use the feature until the actual entrypoint has been exercised and release activation handled explicitly.

## Preservation and verification limits

No push/merge/deploy occurred. Two earlier whole-backend Story Authoring authority assertions remain baseline failures; not fixed or rerun here. Earlier pure-module test counts are not fresh backend tests. Do not start speculative work at this quota boundary.

Initial visible status before this handoff:
```
?? docs/superpowers/plans/2026-10-23-story-gemini.md
?? docs/superpowers/specs/2026-10-23-story-gemini.md
```
