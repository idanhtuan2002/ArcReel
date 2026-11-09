---
status: accepted
---

# Stories are translated paragraph for paragraph

Decided 2026-11-09 by the main agent under the sponsor's instruction to inherit the donors' translation tooling (step 6 of the long-novel plan). Research: [donor writing capabilities](../research/2026-11-09-r2-donor-writing-capabilities.md) §2.2 (multi-language row) and [long-novel and skill gaps](../research/2026-11-09-r2-donor-long-novel-and-skill-gaps.md).

Before this decision the story existed only in the language it was written in (Vietnamese for written stories). Only OpenMontage localizes (a dub script with a glossary and protected terms); DramaClaw keeps supplied names verbatim; neither huohuo nor shenbi translates.

1. **A translation is a text task of the project, not a story run.** `text_story_translation` (tool `translate_story`, route `POST /projects/{p}/story-translations` for the project's Showrunner) translates every story source the project's runs read into English, French, Spanish, German, Vietnamese, Chinese, Japanese or Korean with the project's script text model, and writes `translations/<language>/<file>.md` with a record of the source digest. The story's sources, episodes, adaptations and films are never touched; a story already in the target language is refused.
2. **Paragraph for paragraph, checked in code.** Paragraphs are sent in batches of about 4 000 characters with the end of the translation so far. An answer must hold exactly the batch's paragraph count and keep every registered character name the paragraph writes as a name verbatim (OpenMontage protected terms, DramaClaw names verbatim): a CJK name wherever it is written, any other name where it is capitalized and a whole word, so "Hoa" in "vườn hoa" is translated as the flower it is. Scene and prop names are often ordinary nouns and are translated. Its length must stay within a band of the source length that depends on the scripts: 0.4–3 between alphabetic languages, 0.12–1.2 into Chinese, Japanese or Korean, 0.8–8 out of them, a text counting as CJK when more than 30 % of its letters are, names aside. It must carry no Chinese, Japanese or Korean characters, its CJK names aside, unless the target is one of those. A failing batch is retried with the reasons at most three times, then the task fails with a retryable problem. A name that is also a word and opens a sentence is still checked as a name; the prompt asks the model to keep names, so this rarely costs a retry.
3. **Repeatable.** A file whose source digest matches its translation record is skipped, so a translation interrupted by a failure resumes where it stopped and an appended chapter file is translated alone.

Not adopted: a translated story as a new story run or a dubbed film; a film in another language would be a new project made from the translation, which the existing import path (ADR-0115) already accepts.
