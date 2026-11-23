# Coverage: the new assembly must include everything the old app and the donors do well

Date: 2026-11-23. The sponsor asked for another round: what the new version can do must **include the old app and
all the donors**, inheriting the well-made functions it still lacks — without changing direction (ADR-0170).
Companion to [old app vs assembly](2026-11-23-r2-old-app-vs-assembly.md). Sources: the content forms catalog
(`docs/r2/R2_CONTENT_FORMS_CATALOG.md`), the donor forms inventory (2026-11-15), ADR-0089 … 0169, and the donor
checkouts (OpenMontage `pipeline_defs/`, `tools/publishers/`). Labels: **FACT**, **INFER**.

## 0. How a gap is filled without changing direction

The assembly is: huohuo (story, whole) → translation → DramaClaw (film, whole) → finishing and review post-stages →
OpenMontage (non-fiction and repurposing, whole). A gap is filled, in this order of preference:
1. **Already there because a donor runs whole** — expose the donor's own UI/feature; nothing to build.
2. **Another donor's whole unit at the donor's extension point** — a skill folder, a pipeline file, a provider entry;
   recorded as a donor seam in PORTING.
3. **The old app's unit as a connector feature or post-stage**, when no donor has it (with "Why not ported: no donor").
4. **Not now** — gaps no one covers, listed for later.

## 1. Story

| Capability | Old app | Donors | In the assembly | Gap filled by |
|---|---|---|---|---|
| Long-form novel engine (premise, outline, memory, chapters, audits, repairs) | own re-implementation | huohuo (best), shenbi | ✅ huohuo whole | — |
| Genres 21 (都市/高武/历史 planned) | 28 Vietnamese packs | huohuo genre skill folders (`novel-genre-registry.ts`, one skill per genre per agent) | ✅ 18 active | — |
| Action-adventure, family tearjerker | ✅ packs `action`, `family` | — | ❌ | (3) old pack text as a huohuo genre skill folder (2-style extension, recorded seam) |
| Comedy, fanfic/spinoff (canon/au/ooc/cp) | comedy pack; variants | **shenbi** `轻喜剧`, review-fanfic/spinoff skills | ❌ | (2) shenbi skills whole as huohuo genre skills |
| Children's, fairy tale, fable | pack | ViMax audience adaptation | ❌ | (2) ViMax prompt unit as a genre skill |
| Bedtime / sleep story, real-life storytime | packs (no donor) | — | ❌ | (3) old packs, no donor |
| Parody, interactive branching | ❌ | DramaClaw README claim only | ❌ | (4) not now |
| Import an existing text | ✅ (0115, 0118) | huohuo `import-sources`; DramaClaw `ingest/upload` | ✅ | — |
| Continuation / sequel, variant of a story | ✅ (0115) | huohuo routes `chapters/:id/continue`, `dramas/:id/generate-remaining` (continue a chapter, write the remaining chapters); a sequel book: UNKNOWN | 🟡 continuation within a book; ❌ sequel, variant | (3) old continuation/variant step as a connector feature producing a new premise for huohuo |
| Story from a video URL | ✅ (0161) | OpenMontage video downloader/analyzer | ❌ | (2) OpenMontage analysis tools feeding a premise; (3) old ADR-0161 step if OpenMontage cannot run unattended |
| Translation zh → vi / en | ✅ (0120) | — | ✅ (ADR-0170) | — |
| AI-text detection, humanize | humanize (0119) | huohuo `detect-ai`, humanize hook | ✅ huohuo | — |
| Content safety level per project | ✅ (0121) | — | ❌ | (3) a connector setting passed into huohuo's premise and DramaClaw's prompts as text, no code change |
| Audiobook, sleep story audio | ✅ (0159) | — | ❌ | (3) old audiobook as a post-stage of the story stage |

## 2. Film (fiction)

| Capability | Old app | Donors | In the assembly | Gap filled by |
|---|---|---|---|---|
| Episodes, assets, identities, storyboards, video, voices, compose | own | DramaClaw (best), huohuo | ✅ DramaClaw whole | — |
| Narrated motion comic, dialogue drama, vertical micro-drama, anime and live-action looks | ✅ | DramaClaw (narration + dialogue beats, styles), huohuo 34 styles | ✅ | — |
| Canvas, manual shots, director world, chat assistant | M8 canvas; ArcReel agent | DramaClaw freezone canvas, `manual_shots`, `director_world`, chat | ✅ DramaClaw UI | — |
| Vietnamese voices | ✅ VieNeu, Gemini TTS | edge-tts `vi-VN` inside DramaClaw's TTS generator | ❌ in IndexTTS2 slot | (1) configuration (old-vs-assembly #1) |
| Finishing: loudness, music bed, ambience, grade, captions, cards | ✅ (0133, 0140, 0143, 0150, 0160) | DramaClaw subtitles only; OpenMontage audio mixer, subtitle and music tools | ❌ | (3) old finish post-stage now; OpenMontage's tools when it joins |
| Final-film review | ✅ two reviewers + AIVPE guards (0169) | AIVPE judge; DramaClaw image/text verifiers | ❌ | (3) old review post-stage (AIVPE's guards already in it) |
| Trailer | ✅ (0164) | OpenMontage cinematic | ❌ | (3) old trailer post-stage |
| Hybrid stills + AI video | ❌ | OpenMontage `hybrid`, huohuo two modes | 🟡 DramaClaw modes | (1) DramaClaw video modes |

## 3. Non-fiction and repurposing

| Capability | Old app | Donors | In the assembly | Gap filled by |
|---|---|---|---|---|
| Documentary montage, explainer, animation, character animation, cinematic, talking head/avatar, clip factory, podcast, localization/dub, screen demo, hybrid | narration forms only (0162, 0163) | OpenMontage 13 pipelines (`pipeline_defs/`) | ⏳ OpenMontage needs an agent driver and gate approval ([review](2026-11-23-r2-review-of-the-assembly-plan.md) R7) | research the driver (M5) |
| Facts only from sources; top list, quiz, biography, true crime forms | ✅ fact pack (0162, 0163) | — | ❌ | (3) old fact pack as the story source for OpenMontage documentary/explainer |
| English narration with its own reviewer prompt | ✅ (0165) | OpenMontage (English) | ✅ | — |
| News commentary, motivation quotes, music/lyric video, review-reaction | ❌ | OpenMontage partial (music tools, analysis) | ❌ | (4) not now |

## 4. Running it

| Capability | Old app | Donors | In the assembly | Gap filled by |
|---|---|---|---|---|
| Stage sequence, resume, retries | ✅ production run | DramaClaw task backend resume per stage; huohuo per call | ❌ across donors | (3) connector (P0) |
| Autopilot drawing its own idea, batches, a control room for many projects, alerts outside the app | ✅ (0122–0125, 0137) | — | ❌ | (3) connector features (P2) |
| Free-tier model map, fallbacks, one gateway, usage | ✅ registry, 0139 | DramaClaw NewAPI gateway | 🟡 | (1) NewAPI channels from the registry; huohuo through the same gateway |
| Local models when quotas run out | ✅ ComfyUI, VieNeu, Ollama | ViMax/OpenMontage ComfyUI tools | ❌ | (1)/(3) an OpenAI-compatible proxy in front of ComfyUI for NewAPI |
| Multi-user, roles | single operator + grants | DramaClaw users and roles | ✅ | — |
| Backups, restore, power-loss recovery, autostart | ✅ | Docker only | ❌ | (3) runbook + backup set includes donor volumes (P2) |
| Vietnamese operator page | ✅ whole UI | huohuo UI has `vi`; DramaClaw `zh`/`en` | 🟡 | (3) small Vietnamese run page in the connector; huohuo UI as is |
| Packaging with metadata | ✅ (0115) | OpenMontage `export_bundle`; DramaClaw SRT + ZIP | 🟡 | (2) OpenMontage `export_bundle` when it joins; old packager until then |
| Mobile / desktop apps | ❌ | huohuo `mobile-app/`, `desktop/` | ✅ with huohuo whole (story side) | — |

## 5. Gaps no one covers (the original vision's DISCOVER / DISTRIBUTE / LEARN)

Opportunity research, publishing upload (OpenMontage's publishers stop at a bundle), audience analytics and learning
from them: neither the donors nor the released old app have them (M9 work was never released). Listed for after the
assembly makes films; not part of the current direction's first steps.

## 6. What this changes in the plan

Nothing in the direction. It adds to the ordered list of [old app vs assembly](2026-11-23-r2-old-app-vs-assembly.md):
- **P1**: genre coverage beyond huohuo — shenbi comedy/fanfic skills and ViMax's children's adaptation whole as huohuo
  genre skills; the old action, family, bedtime and storytime packs where no donor has them.
- **P2**: variant of a story and story-from-video as connector features; the content safety setting; audiobook from
  the story stage.
- **P3**: fact-pack sources for OpenMontage; packaging through OpenMontage's `export_bundle`.
