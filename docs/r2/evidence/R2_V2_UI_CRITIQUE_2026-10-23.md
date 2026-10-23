# R2 V2 UI critique — 2026-10-23 (handoff)

Method: ⚠️ partially degraded for quota. Assessment A ran as an isolated sub-agent (screenshots + source). Assessment B ran only as the CLI detector over `frontend/src/components` (5 findings); there was no browser overlay and `src/features` was not scanned. Target: `frontend` (Operate mode), production http://127.0.0.1:1251 on r2-v2.0.2.
Screenshots (not committed): scratchpad `ui-shots/` (desktop 1440x900 and mobile 390x844 for login, projects, workspace, story, episodes, source, settings, project settings). The capture script is scratchpad `ui_shots.py`; it injects the session token as localStorage `arcreel_auth_token`.

## Score: 22/40 (Acceptable)
| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | System status | 2 | Stepper stays at "Chuẩn bị" after story approved, sent and planned; the COMMITTED hint ignores the handoff (StoryAuthoringPage.tsx:566); the 4–5 h run shows only a minutes and token counter |
| 2 | Real-world match | 2 | Jargon in vi copy ("brief", "model", "Tick", "Gate B", tokens, "âm tiết"); raw snake_case genre/theme on the overview; a long world string overflows its card |
| 3 | User control | 3 | Click-twice confirms and a revise path exist; "Rút lại" has the same weight as "Xuất" |
| 4 | Consistency | 2 | The story page has its own buttons and inputs (.sa-btn/.sa-input) and three typefaces; "Noto Serif" is used but never loaded (story-authoring.css:200); kickers say "GATE A" / "TOUCHPOINT 2" |
| 5 | Error prevention | 3 | Approve gated on ticks and digest; STALE_MANIFEST recovery |
| 6 | Recognition | 2 | 16 exception ticks sit below the whole manuscript with no link to their scenes; the handoff path is plain text |
| 7 | Efficiency | 2 | No severity filter or "next unresolved"; the revise-target select is flat (18+ options) |
| 8 | Minimalism | 3 | Brief digest hash and token line are shown to users |
| 9 | Error recovery | 2 | Errors are grey like hints; 422/409 on load; bare /episodes renders blank |
| 10 | Help | 1 | Nothing explains Gate A (4–5 h local run), syllables vs video minutes, or what "Cần bạn quyết định" asks |

## Priority issues
- **P0. No guided path from idea to story to video.** "Viết truyện" is the 6th sidebar item (AssetSidebar.tsx:135); the handoff ends in plain text; the stepper ignores the story; /episodes is blank. Fix: Story as step 0 (or a source choice in "Chuẩn bị"); top of sidebar; a "Tiếp tục: chia tập" CTA after the handoff; an /episodes index route with an empty state. Command: shape/onboard.
- **P0. The multi-hour run feels frozen.** It shows no progress, has no notification, and the story page does not render on mobile (only the agent panel does). Fix: a step tree (planning → chapter n draft → review) with timers; finished chapters readable as they land; the bell or a browser notification on completion; a mobile story route; copy "Có thể đóng tab". Command: harden/adapt.
- **P1. Approval checklist detached from the text.** Fix: inline ticks on margin notes; a sticky "7/16 · next ↓" bar; links to scenes; a severity filter; per-item "Giữ nguyên / Sửa cảnh này". Command: layout/clarify.
- **P1. Status contradictions and leaked internals.** Fix: a handoff-aware hint; humanised genre/theme; wrap/clamp long fields; hide the digest; product words in kickers; remove "Gate B" from vi copy. Command: clarify.
- **P2. Typography/a11y on the story page.** Instrument Serif has no Vietnamese subset (index.html:19), so diacritics fall back glyph by glyph; Noto Serif is not loaded; 9–11px labels; about 3:1 contrast on unreached stages; grey errors; mobile projects scrolls horizontally (758px on 390px). Fix: a serif with Vietnamese coverage, a 12px minimum, danger-token alerts, a collapsing projects header. Command: typeset/adapt.

## Detector (src/components only)
gray-on-color MentionPicker.tsx:291; side-tab NarrationAudioCard.tsx:81, ShotDetail.tsx:951, AgentHandoffHint.tsx:168; layout-transition AssetSidebar.tsx:170.

## Strengths
The manuscript proof with severity-coloured margin notes (editorial metaphor); honest server-owned guards (ticks plus digest, idempotent handoff, draft persistence); the distinctive Darkroom identity on the projects page.

## References to borrow
- GitHub Actions / Vercel: a step-tree job view with timers.
- Google Docs suggestion mode / Reedsy: anchored comments, a next-comment navigator, a resolved count.
- Frame.io / Descript: approved → next stage as a clickable status.
- Linear: the next action offered inline after a status change.

## Next (awaiting Human choice of scope)
Recommended order: P0 flow (step 0 + handoff CTA + /episodes empty state) → P0 run progress and mobile → P1 checklist → P1 copy → P2 type/a11y → polish. Re-run the critique after the fixes, with a full detector pass over `src/features` and a Chrome overlay.

## Done in r2-v2.0.3 (a3aa1144, tagged; deploy pending Human)
P0/P1 on the story page plus the sidebar order and the overview labels. See the tag message for the full list and the deferred items.

## Next phase: whole-app optimisation (proposed 2026-10-23, start next week)
The Human pointed out that the story page is only one part of the product. The UI must use V2 fully, following the design priority "fully automatic, with Human monitoring and intervention at any important decision" (memory: autonomy-with-oversight-design).
1. Pipeline control center: the Overview becomes a live dashboard of stages (Story → Source → Episodes → Assets → Storyboard → Video → Export), each with server status, running jobs, pending decisions and an auto/manual toggle.
2. Decision inbox: every pending Human decision (Gate A, story approval, Gates B–D, batch-video admission) in one place, with notifications.
3. Activity center for long jobs (story, planning, generation), usable on mobile.
4. Unified stepper with story as step 0, driven by server state.
5. App-wide audit: icon-only header buttons, mobile overflow, empty states (/episodes), 422/409 on load, a serif with Vietnamese coverage, a11y.
6. Re-run the critique app-wide: Chrome overlay plus a detector pass over all of `frontend/src` (including features); compare against 22/40.
Workflow: impeccable `shape` for 1–3 (new surfaces; run /frontend-design first per repo rule), then `audit`/`adapt`/`typeset` for 5, `critique` for 6.
