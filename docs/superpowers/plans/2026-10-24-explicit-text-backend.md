# Explicit shared text-backend selection plan

> REQUIRED SUB-SKILL: superpowers:executing-plans, sequential main implementation; reuse existing isolated worktree and preserve old Gemini drafts.

**Goal:** Choose an exact configured model through TextGenerator's existing generation/ledger path.
**Spec:** ../specs/2026-10-24-explicit-text-backend.md
**Architecture:** Existing assembly/qualification and SDK adapters; additive explicit selection, no new dispatch authority or billing layer.
**Tech stack:** Existing Python/pytest; no dependency or schema changes.

## Task 0: Baseline

- [ ] Pin source/graph and current scope; source fallback for stale/missing paths. Preserve dirty drafts and record current default-resolution tests. Reuse existing fixture/fake boundaries; do not mock away the assembly or ledger under test.

## Task 1: Explicit selection and use

**Modify:** lib/config/resolver.py (shared pure vision wrapper + equivalent legacy call), lib/text_backends/factory.py, lib/text_generator.py; tests/unit/lib/text_backends/test_factory.py; tests/unit/lib/test_text_generator.py. A separate integration test file may be used for real assembly/config fixture coverage.

- [ ] RED: new create_text_backend_for_model absent; native Gemini/Grok/OpenAI resolve exact current IDs through actual assembly with constructor-only fake; assert constructed kwargs/provider attribution. Existing credentials/qualification remain owned by current seams.
- [ ] RED: unknown builtin/model, non-text model, invalid canonical custom ID, partial/empty pair, unknown task, unsupported vision fail without generation; custom fallback returned by existing loader is rejected by actual-model comparison. Qualifier refusal propagates.
- [ ] RED: TextGenerator.create accepts complete explicit pair and generate calls selected backend and records provider/model in disposable real Ledger. Omitting pair still calls existing task factory. No config persistence or default modification.
- [ ] Implement specified three modules, retaining default behavior and using existing policy predicate. No provider calls or UI/story/price work.
- [ ] GREEN: run factory/generator tests then full text-backends/config/backend-assembly domains and release-binding integration tests. Run Ruff/format/basedpyright/imports/deptry/test-audit and committed-range diff-check. No unrelated media suite absent a CONTRIBUTING trigger.
- [ ] Commit owned paths before task-done; record exact source range and actual outputs.

## Additive operator entrypoint (scope clarification, 2026-10-24)

The sponsor asked to select/use models through the shared backend. Include `lib/text_backends/console.py` and `tests/unit/lib/text_backends/test_console.py`: list registered builtin text IDs without SDK construction; check a selected configured route without generation; generate via the same explicit TextGenerator/Ledger path. Reuse the application's runtime qualification installer. No HTTP/auth boundary, persistent settings, SDK, database migration or story behavior change. Listing does not claim configured/qualified/live availability; construction does not verify provider access. Existing backend environment/database/master-key context is required. Errors must not print raw credential-bearing exceptions.

## Task 2: Review/handoff

- [ ] One independent read-only review for identity substitution, capability/qualification bypass, attribution and default compatibility. Main owns decisions; one significant repair pass if necessary.
- [ ] Evidence with exact source/test counts/limits and instructions for the backend Python interface. State native-Claude/live-provider/UI/story limitations; no production activation. Archive/checkpoint then evidence-only commit. No push/merge/deploy.
