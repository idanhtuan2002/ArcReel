# M10 bootstrap code review and repair

Reviewed candidate:5652fec045c3ea689fa28503c9d4d57d87273158.
Independent bounded code-review verdict: CHANGES REQUIRED. This is not either
of the two normative M10 design reviews and grants no implementation acceptance.

| Confirmed finding | Repair | Evidence |
| --- | --- | --- |
| Inherited GIT_DIR can redirect the requested repository | FIXED: strip inherited GIT_* variables, resolve requested worktree root, disable global/system Git config, graft file, lazy fetch and remote protocols; disable hooks/fsmonitor/external transforms | Two-repository regression observes requested HEAD despite contaminated environment |
| Index-only staged content can evade git diff HEAD | FIXED: inspect index vs pinned HEAD and worktree vs index independently, plus bounded ignored/untracked owned paths | Stage altered verifier then restore working bytes; refusal preserves complete repository snapshot |
| HEAD can move after its initial capture and receive stale eligibility | FIXED: fresh HEAD comparison before and after verification, all comparisons use pinned commit | Unit before/during probes and actual out-of-scope commit after GitRepository capture are refused |
| Blanket docs/ candidate scope permits unrelated evidence changes | FIXED: exact design-owned path set, including restored M10 corpus/handoffs and this bootstrap evidence; no docs prefix exemption | Unrelated acceptance-document mutation refuses with M10_SCOPE_EXPANSION_REQUIRED |

Six regression scenarios were RED on the reviewed candidate, then GREEN after
one combined repair pass. Final affected verifier suite:94 tests pass, no
failures/errors/skips. Type/lint/import/dependency/test-audit gates pass. The
changed candidate was verified by the parent; there was no second independent
code-review verdict and no normative review/acceptance claim.

The real repository remains ineligible: actual committed-source bootstrap
returns M10_DESIGN_NOT_ACCEPTED. Human custodian qualification, durable factual
currentness, a reviewed prerequisite/sequence treatment and normative design
freeze remain unproved. The tooling verifies structural/hash/lineage consistency,
not whether a declared reviewer is actually independent or qualified.
