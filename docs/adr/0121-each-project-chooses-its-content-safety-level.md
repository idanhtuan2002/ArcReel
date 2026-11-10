---
status: accepted
---

# Each project chooses its content safety level

Decided 2026-11-09 by the main agent at the sponsor's request for a per-project choice between strict, limited and no blocking of sensitive content in stories. Amends [ADR-0117](0117-story-audits-cover-craft-safety-and-the-whole-book.md) §2.

1. **Four levels, set in the project's settings** (`content_safety` in `project.json`, unset = `standard`), read into the story brief when it is drafted, so the level a run audits at is part of what Gate A greenlights and a later change does not alter a running story:
   - `strict` (readers from 12): `standard`, plus detailed violence, horror, coarse language and suggestive scenes as major.
   - `standard`: self-harm methods and instructions for drugs, weapons or explosives are critical; explicit sex, excessive gore or torture and hate speech are major (ADR-0117 as before).
   - `mature`: sex between adults, violence and gore are not defects; self-harm methods and drug or weapon instructions stay critical; hate speech stays major.
   - `off`: everything is recorded as minor and never stops a run, except the line below.
2. **Sexual content involving minors is critical at every level, `off` included.** No setting turns this off.
3. Severity keeps its meaning: critical stops the run (a hard integrity defect, read a second time first), major goes to the Human and is never accepted automatically, minor is recorded. A variant written with the `young-readers` profile is audited at `strict` whatever the project's level.

Amended 2026-11-10 by the sponsor: a project that sets no level is read at the lowest level, `off` (it was `standard`). Sexual content involving minors stays blocked at every level. Projects that never chose a level, or chose `standard` before this change (it was stored as unset), now read as `off`.
