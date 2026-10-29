# M10-C handoff (live)

Rewrite in place; resume entry for the quality operator surface.

## State
- Worktree `.worktrees/r2-m10-c`, branch `design/r2-m10-c-operator-surface`, base `5256a9d72` (M10 accepted with
  conditions, `R2_M10_ACCEPTANCE.json`). `design/r2-m10-b` is pushed to origin by the sponsor.
- Why: M10-A has no router/UI, so deploying M10 ships a Packaging page whose prerequisites (published V2 profile,
  sealed run, PASS disposition) no operator can create. Sponsor order 2026-10-29: do step 1 (put M10 into the
  release) then step 2 (M9-B); do not stop to ask.
- Design: `docs/superpowers/specs/2026-10-29-r2-m10-c-operator-surface-design.md` (subject resolver, host probe
  catalog, quality router, Quality page, Packaging prefill).

## Next step
Codex design review → implement C1 resolver, C2 catalog, C3 router, C4 UI → review → local Chrome acceptance →
sponsor activated-host qualification + deploy (sudo) → M9-B.
