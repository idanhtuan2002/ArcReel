# R2-M8B Creative Canvas: executable plan (release of packet M8-B)

> Makes `2026-09-13-r2-m8b-creative-canvas.md` (tasks B1–B4) executable against the accepted M8-A integration paths, as the umbrella plan requires ("B-F are released one at a time only after the prior accepted implementation fixes their actual integration paths"). Where this plan names a path, test or gate, it refines the packet; it does not relax any packet or spec rule.

**Inputs**

- **Spec:** `docs/superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md` §2, §4 (`CanvasCandidate`, `CanvasNode`, `CanvasEdge`), §7 and §11.
- **Accepted base:**
  - M8-A (`R2_M8_A_IMPLEMENTATION_ACCEPTANCE.json`, acceptance record `68be75bf`);
  - `r2-v2/main`, which includes V2-02c and V2-02d;
  - Alembic head `8a8c4a0e0001`. M8-B adds no migration.
- **Sponsor input:** `docs/r2/evidence/R2_M8_B_GRAPH_ENVELOPE_SPONSOR_DECISION_2026-09-29.json`, option B.
- **Donor:** DramaClaw `b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83`, fully checked out at `~/.cache/r2-donors/dramaclaw-full`.
  - Runtime: Node v22.22.1, pnpm 11.5.0, vitest 4.1.6.
  - Baseline: the 19 selected donor test files pass (182 tests). See `R2_M8_B_DONOR_BASELINE.json`.

**Worktree:** `.worktrees/r2-m8b`, branch `impl/r2-m8b-creative-canvas`, from the `r2-v2/main` commit that adds this plan and amendment 13.

## Derived decisions

These follow from the spec; none is a new architecture choice.

- **D1 — Node types of the ArcReel Canvas v1.** Spec §2 excludes the donor's provider, billing, auto-commit and project shell, so no Canvas node starts a generation. The selected node types are:
  - `beat` (script/beat text);
  - `note` (text annotation);
  - `frame` (a storyboard frame referencing an existing ArcReel image asset or version);
  - `clip` (a reference to an existing video asset or version);
  - `audio` (a reference to an existing audio asset);
  - `group`.

  Media nodes hold references only (artifact key or version ref plus digest), never bytes. The donor generation, upload, export, 3D, pano360, skill, style and compose node types are excluded.
- **D2 — Scope.** One Canvas per episode (sponsor envelope). A Canvas is one M8-A `CanvasCandidate`, and every save is one M8-A revision (append with `expected_head_version`).
- **D3 — Browser harness.** Benchmarks and axe checks reuse the repository's Python Playwright 1.63 (`tests/e2e`) with `axe-core@4.13.0` injected into the page. `@playwright/test` is not added.
- **D4 — Differential parity harness.** Canonical fixtures (JSON inputs and operation scripts) run through two adapters:
  - a donor adapter executed inside the donor checkout;
  - the port adapter in ArcReel.

  Each adapter writes canonical JSON outputs. `scripts/r2/m8b_parity_rows.py` compares them and emits the `BehaviorParityRow`s of a `DonorParityReport`. `scripts/r2/verify_donor_parity.py` (from M8-A) recomputes its surface digest and verdict. Donor tests run unmodified.

- **D5 — M8-A error bodies.** The M8-A API returns `{"detail": <localized message>}`; its stable keys are i18n keys and are not in the body. The canvas classifies a save failure by status (409 conflict, 404 not found, 422 invalid, network/408/429/5xx retry) and shows `detail` as is. On autosave, a 409 is a moved head: every save uses a fresh command id, so a reused command cannot occur. No M8-A change is needed.
- **D6 — Browser storage.** The recovery modules use the browser `localStorage` through the ported quota-safe wrapper, as the donor does, with the clock injected (`now`). Tests use jsdom's storage, and the parity harness uses a budgeted fake storage.
- **D7 — Module-private donor code.** When a selected donor behavior lives in a module-private function (the hydrate decision in `useCanvasSync.ts`), the donor harness copies that function's exact source, with the helpers it calls, into a scratch module and runs it. The donor file is in the selected surface with its hash.

## Selected donor surface

| Area | Donor paths | Donor tests (run unmodified) |
|---|---|---|
| Graph, groups, storyboard order | `frontend/src/stores/canvasStore.ts` (selected functions only), `features/canvas/domain/storyboardGroup.ts`, `groupSelectionDelete.ts`, `groupSelectionDuplicate.ts`, `groupColors.ts` | `canvas-store-storyboard-group`, `canvas-store-group-grow`, `canvas-store-projection-group`, `canvas-store-auto-group-spawn`, `group-selection-delete`, `group-selection-duplicate`, `duplicate-group-nodes` |
| Selection, layout | `features/canvas/application/nodeSelection.ts`, `autoLayout.ts` | `node-selection`, `auto-layout` |
| History (bounded undo/redo, `MAX_HISTORY_STEPS = 50`) | `canvasStore.ts` history functions | `canvas-store-undo-history` |
| Viewport bookmarks | `features/canvas/domain/viewportBookmarks.ts`, `application/bookmarkActions.ts` | `viewport-bookmarks-domain`, `canvas-store-viewport-bookmarks` |
| Save coordination, save decision, payload caps, clear intent | `features/freezone/canvasSaveCoordinator.ts`, `canvasSyncCore.ts` (the pure save decision, payload limits and error classification), `canvasAutosaveHold.ts`, `stores/save-status-store.ts` | `canvasSaveCoordinator`, `canvasSyncCore`, `canvas-autosave-hold`, `save-status-store` |
| Draft recovery, payload caps, pruning, shedding, hydrate decision | `features/freezone/canvasDraftStorage.ts`, `lib/localStorageQuota.ts`, `features/freezone/useCanvasSync.ts` (the hydrate decision only, D7) | `canvas-draft-storage`, `local-storage-quota`, `canvas-store-draft-hydrate` |
| React Flow interaction | `features/canvas/Canvas.tsx` (interaction and LOD only), `application/canvasLod.ts` | the LOD behaviour, measured by the benchmark |

**Excluded** (spec §2 and D1): generation, task and resume logic; asset library and upload; Director World 3D and 360; audio and voice generation; export and compose; billing and credits; companion; auto-commit and push; the donor project shell and routing; donor i18n content.

## Owned paths

All new, unless marked.

- `frontend/src/features/creative-canvas/domain/{graph,groups,storyboardOrder,history,bookmarks,selection,layout,payloadLimits,clearIntent,nodeTypes}.ts`, each with a colocated `*.test.ts` (repository rule FE-TESTS-DIR)
- `frontend/src/features/creative-canvas/recovery/{saveCoordinator,draftRecovery,storageQuota,autosaveHold}.ts` with colocated tests
- `frontend/src/features/creative-canvas/state/canvasSlice.ts` and a test
- `frontend/src/features/creative-canvas/api/explorationClient.ts` and a test (the M8-A endpoints only)
- `frontend/src/features/creative-canvas/ui/**` (the page, the React Flow adapter, node components, the keyboard and a11y layer, conflict and preview UI) and tests
- `frontend/src/features/creative-canvas/__fixtures__/parity/**`
- Modified: `frontend/src/app-routes.ts`, `frontend/src/router.tsx` (or `StudioCanvasRouter`), the episode navigation entry, and `frontend/src/i18n/{en,vi,zh}/*` (the new keys only)
- Modified: `frontend/package.json` and `frontend/pnpm-lock.yaml` (`@xyflow/react` pinned to the donor-locked 12.x, `axe-core@4.13.0`)
- `tools/parity/dramaclaw/canvas-harness.test.ts` (the donor adapter, copied into the donor checkout to run) and `scripts/r2/m8b_parity_rows.py` with tests
- `tests/e2e/test_m8b_canvas_benchmark.py` and `tests/e2e/test_m8b_canvas_a11y.py`
- The evidence files:
  - `docs/r2/evidence/R2_M8_B_DONOR_BASELINE.json`
  - `R2_M8_B_CANVAS_BENCHMARK_PROTOCOL.json`
  - `R2_M8_B_CANVAS_PARITY.json` and its schemas under `docs/r2/evidence/schemas/`
  - `R2_M8_B_BASELINE.json`, the scope file for `verify_m8_scope.py`

No backend, migration or M8-A file changes. A needed M8-A change stops with `M8_BASE_SEAM_CHANGED`.

## Tasks

### B0 — Release gate (35 behaviors in `R2_M8_B_DONOR_BASELINE.json`: 32 planned PARITY, 3 planned IMPROVED (S10, R06, R07))

No product code.

1. Freeze `R2_M8_B_DONOR_BASELINE.json`: the donor URL and SHA, the selected paths with their sha256, the donor test inventory, the runtime identity, and the baseline run log sha256.
2. Write the behavior inventory. Each behavior id maps to its donor function(s), its donor test(s) and the fixture(s) to write.
3. Freeze `R2_M8_B_CANVAS_BENCHMARK_PROTOCOL.json` from the sponsor envelope before any result exists.
4. Freeze `R2_M8_B_BASELINE.json` (the base head, this allowlist, and the seams: the M8-A router and contract hashes). `verify_m8_scope.py` must print `M8_BASELINE_OK`.
5. Commit `test(r2): freeze M8-B donor baseline and benchmark protocol`.

### B1 — Pure domain port

This runs the packet's B1 steps: RED on missing modules, then the port; then donor and port on the same fixtures give parity or improved rows. Pure modules import no React, Zustand, API or storage.

Commit `feat(canvas): port parity-proven graph behavior`.

### B2 — Save and recovery

This runs the packet's B2 steps: races, coalescing, waiters, canvas switch, corrupt/oversized/expired drafts, seven-day pruning, history-first shedding, and explicit empty clear. The injected clock, storage and API come first, with fixtures on both sides.

Commit `feat(canvas): preserve saves and recover drafts safely`.

### B3 — React Flow, API and UI

This runs the packet's B3 steps, including the benchmark ladder of the frozen protocol and the axe and keyboard checks.

Commit `feat(canvas): integrate accessible creative canvas`.

### B4 — Seal

1. Write `R2_M8_B_CANVAS_PARITY.json` with its schema. `verify_donor_parity.py` must return `PASS`, and the gates of the packet and of CLAUDE.md must pass.
2. Commit `test(r2): prove Creative Canvas donor parity`.
3. Stop for independent review under the amendment 12 stopping rule.

## Gates

- **Frontend:** `(cd frontend && pnpm check)`
- **Backend:** the static gates (`ruff`, `basedpyright`, `lint-imports`, `deptry`, `audit_tests.py`) for the new Python scripts and tests; targeted pytest.
- **Scope and parity:** `verify_m8_scope.py` with the M8-B baseline, and `verify_donor_parity.py`.
- The benchmark and a11y e2e.
- A broad backend run only when backend files change (they should not).
