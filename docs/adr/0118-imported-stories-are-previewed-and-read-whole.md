---
status: accepted
---

# Imported stories are previewed and read whole

Decided 2026-11-09 by the main agent under the sponsor's instruction to inherit the donors' import tooling (step 4 of the long-novel plan). Research: [long-novel and skill gaps](../research/2026-11-09-r2-donor-long-novel-and-skill-gaps.md) §4(d). Builds on [ADR-0115](0115-stories-enter-from-ideas-text-continuations-and-variants.md).

Before this decision a run read a project's sources without showing what it found, and a continuation or variant read at most the last 12 chunks of about 8 000 characters (a variant of a longer story was refused), so the first half of a long imported novel never reached the canon lock.

1. **Preview before the run.** `GET /projects/{p}/story-sources/preview` (Showrunner of the project) lists each source file a run reads with its size, the chapters its headings mark (`Chương`, `Chapter`, `Hồi`, `Phần`, `Quyển`, `第…章`, Markdown headings) and warnings: no headings (read as one chapter), CJK text, a chapter over 40 000 characters, an empty file. The run panel and the story page show it when the story comes from the project (DramaClaw import format check, without blocking: a story without headings is still a story).
2. **Long stories are read whole.** A continuation or variant reads up to 60 chunks (about 480 000 characters); every chunk is summarized, the chunks before the last 12 are condensed twelve at a time into `arc_summary[g]` nodes, and the canon lock is built from the arcs and the last 12 chunk summaries (shenbi `import-analysis` passes, `memory-distill` arcs). A continuation of a longer text reads its last 60 chunks; a variant of one is refused as before. The brief's call budget counts the chunks and arcs the text actually has. A text of 12 chunks or fewer is read exactly as before.
3. **The source's voice is measured.** The prior text's average sentence and paragraph length and share of dialogue paragraphs are computed in code and given to the planning prompts with the canon lock (shenbi `style-learning`); ADR-0117's drift check holds the new part to the same numbers.

Not adopted: a separate import-analysis report with nine fact categories and provenance labels (shenbi `truth-sync`); the canon lock's name attestation already keeps only what the text writes, and a book bootstrapped from an imported text is left to a later decision.
