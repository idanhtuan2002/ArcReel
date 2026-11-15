---
status: accepted
---

# One fact pack, four narration forms

Decided 2026-11-15 on the sponsor's catalog (rank 8 explainer / curiosity, rank 9 top list / trivia / quiz), building on ADR-0162.

1. The research, claim verification and citation rules of ADR-0162 are shared; only the narration shape changes. `make_documentary(..., form=)` takes `story` (default, ADR-0162), `top_list` (countdown, one item per chapter titled `#N …`, most surprising last), `quiz` (one question per chapter: question + pause cue, then answer + its fact) or `explainer` (question hook, steps from the known to the new, one concrete example each, two-sentence summary). Any other form is refused (`UNKNOWN_FORM`).
2. Every paragraph still cites verified claims; a list item, a quiz answer or an explainer step cannot state a fact the pack does not hold.
3. The form is recorded in `research_pack.provenance["form"]` and on the job; API `POST /projects/{p}/documentaries` takes `form`; the source page offers it next to the language.

Not covered: on-screen countdown numbers, quiz timers or explainer charts/diagrams (the film path renders the narration like any story source; deterministic charts are a later catalog step), non-Wikipedia sources.
