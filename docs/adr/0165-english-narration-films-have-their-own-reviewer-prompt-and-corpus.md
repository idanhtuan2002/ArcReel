---
status: accepted
---

# English narration films have their own reviewer prompt and corpus

Decided 2026-11-15 on the sponsor's language order (Vietnamese, then English, then Chinese; catalog C2 row L1a: an English film from a translated story).

Before this decision every automatic film was Vietnamese: the launch profile allowed only `vi`, and both reviewer prompts ask for "natural Vietnamese" narration, so an English film would be scored down or flagged as the wrong language. The reviewer's answer must also name the policy language (`r2/automation/assessment.py`), and reviewer qualifications are bound to the launch profile and the language.

1. **Launch profile `fiction_narration_en_v1`**: the Vietnamese narration profile's pictures (local klein stills, still clips, face-identity selection) with an English voice, Gemini TTS `gemini-3.8-flash-tts` (ADR-0156), and 2.5 words per second until the media probe measures the route. The story comes from a translation (ADR-0120) imported as a project source (ADR-0115); the film path already reads the project's `source_language` (speech rate, episode and next-episode cards, publish metadata).
2. **Reviewer prompts per language**: `review_prompts(language)` gives the frames and watch prompts; English prompts ask for natural English with the same scales, rules and schema. A Vietnamese prompt digest is byte-for-byte what it was (pinned by a test), so recorded Vietnamese qualifications stay valid; another language adds itself to the digest. A language without prompts has no reviewer.
3. **Qualification per language**: a profile's language picks its corpus from `ARCREEL_REVIEWER_CORPUS_<LANGUAGE>` (Vietnamese keeps `ARCREEL_REVIEWER_CORPUS`) and keeps its receipts under `<receipts>/<language>/`; the reviewer route is qualified again on that corpus before an English run can start (preflight unchanged).
4. **English corpus**: the Vietnamese corpus builder's 20 stories, translated scene by scene, spoken in English and rendered on the same pictures; each story's critical-defect variant uses the same defect types. Built on the host as an operations step; until it is recorded, an English run is refused at preflight (`REVIEWER_NOT_QUALIFIED`), which is the intended state.

Not covered: native English story authoring (L1b), Chinese (L2a/L2b), English voices on a local route.
