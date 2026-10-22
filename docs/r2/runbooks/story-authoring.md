# Story authoring runbook (R2 V2)

Turns one idea into an approved three-chapter Vietnamese short story and hands it to the video flow as the
project's source. Design: `docs/superpowers/plans/2026-10-18-r2-v2-story-release-amendment.md`; model routes:
ADR 0109; evidence: `docs/r2/evidence/R2_STORY_AUTHORING_QUALIFICATION.md`.

## 1. Setup

1. Ollama ≥ 0.32 on the host, reachable from the server (default `http://localhost:11434`).
2. Pull the models:
   - writer: `qwen3.5-vimax:9b` (6.6 GB, fits an 8 GB GPU);
   - review (recommended, optional): `gemma3:12b` (8.2 GB; on an 8 GB GPU it runs partly on the CPU at
     5–7 tokens/s, so review dominates run time).
   The gateway sends `num_ctx` 32768, `truncate: false` and the decoding of each step with every request; the
   Modelfile's own parameters are not relied on.
3. In **Settings › Providers**, add a custom provider (base URL of Ollama, no API key) and add each model with the
   endpoint **`ollama-chat`**. Only enabled `ollama-chat` models are offered on the Story page; other endpoints are
   refused (`ROUTE_NOT_QUALIFIED`).
4. The operator needs the project's Showrunner grant (governance) to start, approve or change a run.

## 2. Touchpoints

A clean run needs two Human actions; video then keeps its own Gates B–D.

| # | Where | Action |
|---|---|---|
| Gate A | Story page › New story | Prepare the brief (idea, genre, writer and review model, length 7,000–11,000 syllables), read it, **Approve and start**. The approval binds the brief's exact digest; editing the brief needs a new approval. |
| Touchpoint 2 | Story page, run "Ready for your review" | Read the manuscript with the review notes beside each scene. Tick every item marked "Needs your decision" (narrative-critical exceptions, unverified claims, blurb claims the story lacks). **Approve story** binds the manuscript digest you read and the ticked items. |
| Gates B–D | Video workflow | Unchanged. **Send to video** uploads the approved story as `<slug>.md` through the project's source upload, which stores it as the normalized `source/<slug>.txt` of a novel project (same bytes as the export). |

Optional actions: **Ask for a revision** (a chapter, a scene, the outline or the title/blurbs, with a note; the run
rewrites that part and everything stale after it, then offers again), **Discard**, **Withdraw** (an approved
story; video jobs already started keep running — cancel them in Tasks and do not approve Gate B; refused while a
Send to video is uploading), **Export (.md)**. A second Send to video while one is uploading is refused
`IN_PROGRESS`; wait and send again with the same click (the page reuses its command id).

Agents never perform these actions.

## 3. States and recovery

| State | Meaning | What to do |
|---|---|---|
| Writing | Planning, drafting and review in progress; the page refreshes itself | Wait; a clean local run takes about 3–4 h on an 8 GB GPU |
| Ready for your review | Touchpoint 2 | Approve, revise or discard |
| Saving your approval / Approval incomplete / Approval stopped | The commit of approved chapters is running or was interrupted | **Resume** (only the approver), or **Stop here** (keeps recorded chapters, nothing more; a step that was being saved when you stopped is still recorded) |
| Stopped at the budget | The run used its calls (292), tokens or about 9 h 44 min of model time | A run's usage never resets, so Retry stops again; discard it and start a new brief |
| Stopped on a quality check | A hard check could not pass within its caps; the reason and findings are shown | Read the reason; **Retry**, or ask for a revision of the named part |
| Model unavailable | The frozen model route no longer matches the provider settings | Restore the provider/model as it was, then **Retry**; or discard and start a new brief |
| Story data changed / A change could not be applied | Canon or plan bindings moved under the run | **Retry** rebuilds from the current state |
| Needs attention | Saved state could not be recovered safely | Discard and start again |

A server restart resumes a running story from its last recorded step; nothing is lost and no model call is
counted twice.

## 4. Quality policy

- **Hard** (CJK characters, copied or truncated text, broken structure, contradictions confirmed by a second
  reading): repaired or regenerated within caps; if still open the run stops and is never offered.
- **Needs your decision** (narrative-critical): offered at touchpoint 2; Approve stays disabled until each is ticked.
  A blocking claim the second reading could not confirm arrives here marked "[chưa kiểm chứng]".
- **Style** and **model limit**: recorded with the story; no tick needed.
- The reviewers' verdicts are evidence for the Human, not the quality verdict: the Approve is.

Known limits of local 9B models (evidence, runs 1–11): coherent prose, but kinship terms can drift, scenes often
lack dialogue, some do-not items slip through review, and blurbs can invent facts (flagged for your decision).
Names outside the story bible (real places, holidays) are recorded as style findings and not repaired.

Video episode planning after the hand-off is not qualified on `qwen3.5-vimax:9b`: on the acceptance story its
end anchors were not verbatim and planning failed 3/3 attempts. Use a qualified text model for episode planning.

## 5. Limits and cost

Per run: 292 generate calls (the bound of a story whose every review fails, with up to five scenes per chapter),
292 × 24,576 input and 292 × 4,096 output tokens, and 292 × 120 s of model time; the next call is refused once
model time reaches the ceiling. Acceptance run `accept-clean` (writer `qwen3.5-vimax:9b`, review `gemma3:12b`,
2026-10-22): 138 generate calls, 1.06 M input / 109 k output tokens, about 4 h 7 min, no cloud cost.

## 6. Switching to a cloud model later

A cloud provider serves a route only after its own qualification (ADR 0109): an adapter states which
pre-generation guarantees it provides (exact token count, truncation signal, no-CJK pattern, length bounds, seed),
and a qualification run proves them. Credentials go only into Settings › Providers (database). Data leaves the
machine only when a Human configures a cloud route and approves a brief that names it. Readiness research and cost
estimates: `docs/research/2026-10-19-r2-v2-story-cloud-model-readiness.md`.

## 7. Backup coverage

Run state lives in the `tasks` table (PostgreSQL) and run artifacts under the project's `story_authoring/` folder;
approved chapters are R2 narrative records. All are covered by the deployment backup
(`docs/r2/runbooks/m7-backup-restore.md`): back up with the server stopped, restore into an empty database and
data root, and verify before use.
