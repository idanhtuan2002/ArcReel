---
status: accepted
---

# Documentary narration from a sourced fact pack

Decided 2026-11-15 on the sponsor's catalog (rank 7: history, true crime, mysteries, biography — evergreen, higher-RPM faceless niches; vision R-A2 "the narrative agent never invents a fact; it takes it from the Research Pack").

1. **Research**: a topic is searched on Wikipedia through the public MediaWiki API, the requested language first, then English; up to 3 pages, their paragraphs (with section headings as locators) are the evidence (at most 60). Client name `ArcReel-documentary/1.0 (automated research client)`; no user data is sent beyond the topic.
2. **Claims**: the project's script text route (fallbacks per ADR-0139) lists claims, each with the evidence id and a verbatim quote; a claim whose quote is not in its evidence (case and spacing aside) is dropped. Fewer than 3 verified claims refuses the topic.
3. **Narration**: the route writes a hook and 2–6 chapters; every paragraph lists the claim ids it states; a paragraph citing none or an unknown id sends the draft back (3 attempts). Style rules: spoken, concrete, no naming of the structure, at most three numbers per paragraph, disagreements between sources said aloud.
4. **Records**, reusing the factual contracts (`r2/contracts/factual.py`): `research/<slug>/research_pack.json`, `claim_ledger.json` (all `VERIFIED`, quote in provenance), `sources.json`, `evidence.json`, `manuscript.md`, `citations.md`; and `source/<slug>.txt` (the narration without headings) for the film path. API `POST/GET /projects/{p}/documentaries`; UI on the source page (topic, language vi/en/zh).

Smoke (2026-11-15, "Cầu Long Biên", vi, OpenRouter `particle-1:free`): 3 pages, 40 verified claims, 139 s; the narration states the 1898/1899 date disagreement of its sources. The first draft named its own chapters ("Chương một mở ra…") and stacked numbers; rules for both were added.

Not covered: stock footage or archive images (OpenMontage documentary-montage), a separate claim reviewer, non-Wikipedia sources.
