---
status: accepted
---

# V1 locks a factual product's script at Gate B and binds a verified audio decision at Gate C

The V1 release gate (ADR-0089; strategy §6) requires every product to hold A, B, C and D
decisions bound to exact revisions, plus intelligible audio or an explicit mute decision
(strategy §2). The restore drill at `7186fffb` found two gaps:

- the factual product has no Gate B decision, because the only Gate B mechanism is drama
  screenplay admission;
- no product records its audio decision, although every final's audio track is silent.

The sponsor delegated the choice to research:
`docs/research/2026-09-28-r2-v1-08-release-gate-gaps.md`.

**Gate B for a factual product.**

- **What is added.** A factual product's Narrative Lock is an append-only script-lock decision:
  project, `source_digest`, `script_digest`, action `LOCK` or `REVOKE`, and the session-derived
  authorization. It is recorded through `POST /projects/{p}/gates/script-lock`. The shape is
  the same as Gates A and D (the P1 design).
- **How it relates to drama.** Screenplay admission stays the Gate B for drama. A product needs
  one of the two, not both.
- **What changes it.** A changed source or script is a new revision and needs a new lock.
- **What the server checks.** Only the digest format (`sha256:<64 hex>`). The server does not
  recompute the digests from the source and script bytes. The lock records the operator's decision about
  the named revisions, like Gate A's `source_digest`. The release dossier checks the recorded
  digests against the product's own revisions, and it checks that the lock came before
  production.

**The audio decision at Gate C.**

- **What is required.** A `COMPOSITE` final's Gate C approval must carry
  `audio_decision: AUDIO | MUTE`.
- **How the server verifies it.** The server checks the decision against the exact bytes it
  approves:
  - `MUTE`: no audio stream, or a peak (`max_volume`) at or below -60 dB;
  - `AUDIO`: an audio stream that peaks above -60 dB.
- **Where it is stored.** The decision is stored on the Gate C receipt. Shot approvals carry
  none.

**Release check.** The V1 release dossier verifies each product from its gate history:

- A is `GREENLIGHT`;
- B is `LOCK`, or a drama admission;
- the lock precedes the first Gate C receipt;
- the final receipt carries an audio decision;
- D is `APPROVE_PUBLISH` of the exportable digest.

## Considered options

- **Reuse the Greenlight table for B.** Rejected: it mixes Gate A and Gate B history, and it
  breaks the Gate A contract.
- **Fake a screenplay admission for factual products.** Rejected: that would forge M6 authority
  records.
- **Exempt factual products from B.** Rejected: it contradicts ADR-0089 decision 3.
- **Carry the audio decision on Gate D, or as free text.** Rejected: that is the wrong gate, or
  an unverified claim.
- **Render narration for V1.** Deferred: it needs a qualified TTS route, and the contract
  permits a mute decision.

## Consequences

- **Schema.** One additive migration: the `gate_script_lock_decisions` table and a nullable
  `gate_final_cut_receipts.audio_decision` column.
- **UI.** The project settings gate panel gains a script-lock action.
- **Drill.** The restore drill locks Golden A's script and records `MUTE` for all three finals.
- **Enforcement.** Refusing production without a lock is not enforced at runtime in V1. The
  dossier checks the order instead.
