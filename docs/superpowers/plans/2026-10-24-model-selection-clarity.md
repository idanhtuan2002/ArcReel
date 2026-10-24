# Model selection clarity

Approved user scope:system defaults → project overrides → explicit per-story override; reuse current UI/config and conserve quota. Base3961fa2fd9d504d32e06b997df4170dc84eed1fe.

Frontend-only change. Reuse effectiveModel and existing project/system config reads, text complex(SCRIPT)>default precedence, server-qualified story routes and immutable approved briefs. No new backend/provider/billing/schema/credential framework. With no explicit setting, retain automatic selection among story-eligible routes and label it Automatic. An explicit inherited model that is unsupported/unavailable must require an override, never silently select another model. Judge follows writer by default. Global/project defaults are fetched in parallel with route facts. Existing server guards still validate the selected exact route.

1.Write failing inheritance/UI tests. Implement a pure default resolver and collapsed story summary with per-run override/reset, keeping cloud budget and approval visible.
2.Reuse ModelConfigSection for compact inherited summaries and optional project/create-wizard customization; show existing overrides. Add global scope explanation and rename its navigation label to Model defaults. Translate all new text in en/vi/zh.
3.Run affected frontend tests, full frontend check/build, translation consistency and test audit; no unrelated full-backend/provider runs. Inspect desktop/mobile once, repair material findings once. Record exact source and release status, preserve unrelated drafts. Prepare a concrete scoped deployment, with sudo handled only after checks.

## Verification and release handoff

Implementation complete on feat/v2-model-selection-clarity, based on3961fa2fd9d504d32e06b997df4170dc84eed1fe. Frontend only; no schema/provider/backend changes.

- pnpm --dir frontend check: typecheck, ESLint, knip pass;234 test files pass;2633 tests pass,4 skipped.
- pnpm --dir frontend exec vite build: pass; existing icon dynamic-import warnings.
- i18n consistency:18 pass. scripts/audit_tests.py --check:0 violations. git diff --check:pass. Impeccable detector on changed UI files:empty findings.
- Browser preview on5175 against unchanged1251 backend: global/project scope text present; existing project overrides remain visible; per-story override selects exact route and reset restores original inherited route; unsupported inherited route is explicitly warned. Desktop1440 and mobile390 inspected; mobile document width390, no horizontal overflow. No story submission, provider generation, settings save or credential change. Screenshots stay outside Git because surrounding existing project data is private.
- Full frontend and evidence logs: .superpowers/sdd/2026-10-24-model-selection-clarity/. Relevant graph coverage was checked; story additions missing from graph, exact source and tests used instead.
- Production remains r2-v2.0.7 until manual sudo authentication. Candidate tag:r2-v2.0.8. Deployment reuses the existing pinned backup/cutover/preflight with rollback safeguards, updated to this candidate. Command after preflight: sudo bash /tmp/arcreel-v2.0.8-cutover.sh.
- After deployment, verify post-result and actual1251 browser. Do not report production active before that.
- Preserve unrelated untracked2026-10-23-story-gemini plan/spec drafts.
