# Three independent rounds, reconciled — and the last research note before a film

Date: 2026-11-23. Rounds: [A — what to do](2026-11-23-r2-independent-round-a.md), [B — what it will produce](2026-11-23-r2-independent-round-b.md),
[C — what can make it fail](2026-11-23-r2-independent-round-c.md), run as separate read-only agents. The main agent
re-checked the two findings that change decisions: DramaClaw's `drama` spine rejects text without scene headers
(`structured_ingest.py:81-86`, "精品剧必须包含场景头") and its Ken Burns path exists only as a test mock on the API path
(`video_generator.py:4517-4553`). Round C's advice is taken: **no further research notes until a film exists**.

## Where all three agree (FACT, cited in the rounds)

| # | Finding | Change to the plan |
|---|---|---|
| 1 | `pipeline/status` returns task types (`ingest_fast`, `build_characters`, `script_writer`, `single_video`, …), not the §5 keys | §5 keyed by task type; the connector walks DramaClaw's own step order and uses status only as the completion check |
| 2 | "Nothing to do" answers (e.g. `audio_generation_not_required` for silent beats) while status still waits → endless loop, the class of R2's 2.5.85/87 | one class rule: a step answered "not required"/no-op counts as done for that episode; a step that repeats without progress twice stops the run with its reason |
| 3 | Voice samples upload only after the `characters` step ("Character not found"); the reference reaches the adapter as an inline `data:` URL, not a relayed download; DramaClaw stores the uploaded bytes unchanged | casting after `characters` (and per age group after `identity_plan`); the adapter decodes the `data:` URL, maps by SHA-256, returns MP3 at a `host.docker.internal` URL; an unknown sample stops with an error (no silent narrator) |
| 4 | Video: Seedance's once-only free pool covers roughly 18–23 clips / 33–93 s of 720p video; the M2 story needs ~29 clips / 161–189 s | **free video cannot finish even M2** → a decision before M2 (see "For the sponsor") |
| 5 | Ken Burns is not available on the API path | removed from fallbacks; the free video route is DramaClaw's own **ComfyUI channel** with our local Wan workflow, set up before M2 |
| 6 | Vision: the global video optimizer makes one image-carrying call per beat; Gemini allows 20/day/model; the D6 fallback (nemotron-vl) returned broken JSON in our probe | vision slots spread over several Gemini models; nemotron removed; Groq `qwen3.8-27b` (≤3 images) as the last fallback |
| 7 | Language: DramaClaw treats Vietnamese as Chinese (`source_language.py`) — descriptions and image prompts in Chinese; spoken lines and subtitles come from the source text and stay Vietnamese | accepted (Chinese prompts suit Seedream); M2 acceptance checks Vietnamese speech and subtitles explicitly |
| 8 | Call DramaClaw's REST endpoints directly; the Hermes plugin is an LLM-agent layer | **no vendoring of the plugin**; it is the reference for endpoints and arguments |
| 9 | huohuo's compose does not pass `HUOHUO_PRESET_*` or `extra_hosts`, publishes on all interfaces with a known default token; its batch writer stops when the stream drops | our override (like DramaClaw's): env, host gateway, loopback, random token; resume with `mode: "remaining"` |

## New from one round, accepted

- **B: the `drama` spine needs scene headers; prose only goes through `narrated`.** D26 becomes: prose stories → `narrated`
  (vertical size set explicitly); dialogue drama later through huohuo's `drama_script_formatter` → translation → header
  rewrite to `INT. <nơi> - DAY` → `drama` (an M3+ item).
- **B: `structured_v1` makes one episode per chapter**; the connector writes `Chapter N` markers (DramaClaw does not read
  `Chương N`). huohuo's default chapter (~3 000 characters) gives long episodes; episode length follows the story (D23).
- **B: sketches default to the nanobanana model** → pin `sketch_image_selection` to `LingShan-G2` (Seedream) at configure;
  Seedream 4.0 as a second 200-image pool.
- **B: every identity needs its image** (status checks only the main character) → the connector generates identity images
  for all identities.
- **B: compose burns no subtitles, ignores BGM, no loudness** → the M4 finish post-stage is required, captions always.
- **A: Cloudinary is an entry gate for M2**, not a side note.
- **A: M2b thin** — run list, start form, step timeline with Continue / Pause / Redo and deep links into huohuo's and
  DramaClaw's own screens, errors, film player; no re-implementation of donor screens.
- **A/C: M4's REWORK** regenerates whole steps → report-only until the sponsor approves that cost.
- **C: D15** retries capped per step to avoid re-billing a whole episode step three times: media steps 1 retry, text 3.
- **C: images pinned by digest**; the media-catalog auto-update stays off; check that the running 2.0.2 matches `b299bfd`.

## For the sponsor (product and GOAL questions)

1. **Video money**: free Seedance cannot finish M2. Options — local Wan through DramaClaw's ComfyUI channel (free, slower,
   lower quality), 480p to stretch the pool, or a paid video budget.
2. **GOAL amendment**: the DramaClaw Vietnamese UI (D25) changes donor code for a reason other than a missing model; GOAL
   rule 1 needs an explicit exception for interface localization the sponsor requires.
3. **GOAL additions** (C): a tolerance for using up once-only pools, M2 as the spike with a Go/Kill criterion, and a code
   size count per milestone.
4. Cloudinary account (or the inline relay seam).

## The UI question (answer)

All rounds and the interface note agree: **a new, thin Vietnamese run console** for what no donor shows (runs, start,
step timeline with controls, errors, film player), deep links into huohuo's `vi` UI and DramaClaw's UI/canvas for per-step
work; the old app's code is not reused (its run panel speaks R2's digest/qualification contract to ArcReel's server); its
Vietnamese wording and layout are.
