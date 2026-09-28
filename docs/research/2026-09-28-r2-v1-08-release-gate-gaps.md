# R2 V1-08 — release-gate gaps: factual Gate B and the audio decision

Date: 2026-09-28. Candidate `7186fffb` (branch `feat/r2-m7e-v1-lineage`). The research was
delegated by the sponsor ("research until the best option is chosen; do not ask"). License is out
of scope.

## Question

The V1 release gate (strategy §6) requires every product to hold valid A, B, C and D decisions,
bound to exact revisions. It also requires the §2 product contract: intelligible selected audio,
or an explicit mute decision. The restore drill at `7186fffb` showed two gaps against these.

## Facts

1. **Gate B is mandatory for every product** (ADR-0089 decision 3; strategy §2 and §3).
   - The §2 pipeline puts "B: Narrative Lock" before production for a factual source as well
     as a narrative one.
   - CONTEXT.md defines it as "人对确切 source 与 script revision 作出的叙事锁定，允许该修订进入制作"
     (a human's narrative lock on the exact source and script revision, which admits that
     revision into production).
2. **The only Gate B mechanism is screenplay admission** (`POST /gates/narrative-lock`,
   `AdaptationAuthorityService`).
   - It needs an adaptation branch, a profile and an evaluation report.
   - It is a drama adaptation authority (M6). A factual explainer has no screenplay branch.
3. **Golden A has no Gate B decision.** In the drill at `7186fffb`, Golden A (the 75 s H.264
   explainer) has Greenlight, per-shot and final Gate C, and Gate D, but no Narrative Lock. The
   two Golden B siblings do have one (`d-admit-golden-b-*`).
4. **All three finals carry a silent audio track.**
   - Golden A and Golden B Western both measure `mean_volume = max_volume = -91.0 dB`
     (ffmpeg `volumedetect`).
   - The no-provider fixture pipelines render no narration.
   - No mute decision is recorded anywhere.
5. **Precedent for Gates A and D** (P1 design, 2026-09-22):
   - each is a small append-only decision table, bound to a digest;
   - each has a session-authenticated route;
   - ADR-0089 decision 5 allows this: it is "the smallest host-owned A–D receipt … without
     creating a new governance database".
6. **The Gate C receipt** (`gate_final_cut_receipts`) is the audit record of the Final Cut
   decision. For a `COMPOSITE` final, the server already reads the exact bytes being approved.
7. **ffmpeg is a host dependency** already: the composer uses it and the drill uses ffprobe.
   `volumedetect` reports `max_volume` for a stream.

## Options for Gate B on a factual product

| Option | Assessment |
|---|---|
| **B1: add a factual script lock.** An append-only decision per project binds `source_digest` and `script_digest`, with action `LOCK` or `REVOKE`, through `POST /gates/script-lock`, following the Gate A pattern. | Matches fact 5 and the glossary's binding (exact source and script revision). Adds one table and one route. |
| B2: reuse the Greenlight table with a new action | Mixes Gate A and Gate B history. It breaks the `GreenlightDecision.action` contract and the Gate A reading. Rejected. |
| B3: reuse screenplay admission | A factual product has no branch, profile or evaluation, and faking them would forge M6 authority records. Rejected. |
| B4: exempt factual products from Gate B | Contradicts ADR-0089 decision 3 and strategy §2. Rejected. |

## Options for the audio decision

| Option | Assessment |
|---|---|
| **A1: the Gate C final approval carries the decision, and the server verifies it.** `audio_decision: AUDIO | MUTE` is required for a `COMPOSITE`, checked against the approved bytes (MUTE: no stream or `max_volume ≤ -60 dB`; AUDIO: an audio stream above that), and stored on the receipt. | Binds the decision to the exact final that Gate C approves. The server can prove the claim. One column. |
| A2: carry it in the Gate D request | Gate D binds publication intent. The media decision belongs to the final cut, so this is the wrong gate. |
| A3: note it in `approval_record` text | Not structured and not checked. Rejected. |
| A4: render real narration | Needs TTS. A paid TTS provider is not qualified in V1; a local TTS is new scope. The contract explicitly permits a mute decision. Deferred. |

## Decision (recorded as ADR-0092)

**Gate B for a factual product: B1.** The lock is additive. Screenplay admission stays the Gate B
for drama.

**The audio decision: A1**, with the thresholds verified by ffmpeg. Shots do not carry it.

**The release gate checks every product through its gate history.** The history shows:

- A: the latest Greenlight is `GREENLIGHT`;
- B: the latest script lock is `LOCK`, or, for drama, a Narrative Lock admission;
- C: the final receipt carries an audio decision;
- D: the latest Publish Approval is `APPROVE_PUBLISH` of the exportable digest.

**Not decided here:** runtime enforcement of "B before production" (refusing shot production
without a lock). Production is not a single host call in V1. The dossier check verifies the
order: the lock precedes the first shot receipt.

## Unknowns

- **The `-60 dB` threshold** is a policy choice. The measured silence is `-91 dB`. Speech
  normally peaks above `-20 dB`.
