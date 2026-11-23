# How large organisations build, govern and accept projects — and what R2 lacks

Date: 2026-11-23, round 3 of the off-course research ([round 1–2](2026-11-23-r2-why-the-project-went-off-course.md)).
Question from the sponsor: how do large organisations run projects (method, governance, monitoring, acceptance);
where are we missing something; how to never go off course again, control quality and spend resources well.
Labels: **FACT** (with source), **INFER**. External sources are listed at the end; book sources are cited by title.

## 1. The practices, side by side with R2

| # | Practice (who uses it) | What it requires | R2 (FACT, from rounds 1–2) | Gap |
|---|---|---|---|---|
| 1 | **Verification vs validation** (NASA SE Handbook ch. 5; NASA SWEHB) | Verification: "you built it right". Validation: "you built the right thing", against stakeholder expectations, "continually asked" in every phase | 345 k lines of tests, 162 ADRs, acceptance packets, 23 relayed design reviews — all verification against R2's own contracts. The first validation of the product (an automatic film) came on 11-08; never against a donor's film | **Validation missing for 2 months; verification over-built** |
| 2 | **Continued business justification; stages with go/kill** (PRINCE2 principles; Cooper Stage-Gate) | The business case is re-checked at every stage; a project or stage that no longer delivers its benefit is stopped. Gates are real Go/Kill/Hold/Recycle decisions on value, not scheduling checkpoints | Gates checked readiness of authority packets. On 10-06 the sponsor said progress was slow and the product is "ghép các phần tốt nhất"; the reset kept M8–M12 and the architecture | **No value gate; nothing was ever killed** |
| 3 | **Manage by exception with tolerances** (PRINCE2) | The board sets tolerances (time, cost, quality, scope); work inside them is delegated; only a breach is escalated | No tolerances. The sponsor gave 38 technical confirmations, relayed 23 reviews, pasted 36 agent instructions, wrote 70 session/quota messages | **The sponsor managed by inclusion, not by exception** |
| 4 | **Focus on products** (PRINCE2) with product descriptions and quality criteria | Each deliverable has a description and measurable quality criteria agreed up front | The deliverables were documents and packets; "a film at donor quality" had no product description until reviewers came in November | **Product never described** |
| 5 | **Working backwards: PR/FAQ** (Amazon, *Working Backwards*) | Start from the customer experience written as a launch press release and FAQ; most PR/FAQs are rejected — that is the point | Started from an imported architecture package (vision of a "Creative Production OS"); the sponsor's one-line goal was never written as the product | **No customer-first definition** |
| 6 | **Mechanisms over good intentions** (Amazon) | A recurring problem is fixed by a mechanism (tool + adoption + audit), not by asking people to try harder | The goal was restated 20+ times and research-first 8+ times as intentions; the first mechanisms (hooks) came on 11-23 | **Intentions for 2.5 months** |
| 7 | **Single-threaded owner** (Amazon) | One owner per initiative, not split across a matrix | The sponsor relayed between three AI roles (design elsewhere, Codex review/design, Claude implementation); the product goal had no owner | **Matrix with the sponsor as router** |
| 8 | **Phases discovery → alpha → beta → live, each assessed against user needs** (UK GDS Service Manual; US Digital Services Playbook plays 1 and 8) | Understand the need, prototype cheaply, then build; an assessment at each phase against the Service Standard; "Before moving into live, a service must show it used beta to build something meeting the needs identified in discovery and alpha" | Architecture frozen on 09-06 before any alpha (no prototype film, no donor baseline); assessments were against the architecture | **Froze before discovering** |
| 9 | **Start from a simple system that works** (Gall, *Systemantics*: "A complex system that works is invariably found to have evolved from a simple system that worked"; Cockburn's walking skeleton; Brooks's second-system effect, *The Mythical Man-Month*) | Get the thinnest end-to-end path running first, then grow | The simple working systems existed — the donors produce films end to end — and were not used as the starting skeleton; a 58 k-line governance core was built first | **Built the complex system first** |
| 10 | **Blameless postmortem / Correction of Errors with tracked action items** (Google SRE ch. 15; Amazon COE) | Root causes, action items owned and tracked; an unreviewed postmortem "might as well never have existed" | The 10-06 reset was a postmortem whose action items left the root cause in place; nobody checked whether the cause recurred (it did: 91 releases, 44 % on own governance) | **Postmortem without root-cause action or follow-up** |
| 11 | **Delivery metrics** (DORA: deployment frequency, lead time, change failure rate, time to restore) | Measure speed and stability of change; act on trends | Never measured. Today's audit: 91 releases in 14 days, most fixing the previous ones (a high change-failure rate) | **No metrics** |
| 12 | **Decisions that can be superseded** (Nygard ADRs; GDS Way: "proposed → accepted → superseded", link to the replacement) | Every decision carries its context; when the context changes, a new decision supersedes it | "FROZEN v1"; changes need an approval nobody asked for; the context (the sponsor's goal) changed in meaning, the freeze never moved | **Freeze without review trigger** |
| 13 | **Tailor to suit the project** (PRINCE2 principle 7) | Governance proportional to size, risk and team | One operator ("hệ thống do một mình tôi vận hành") received enterprise governance: five authority planes, custody, grants, attestation, offline fences, independent reviews per packet | **Not tailored** |
| 14 | **Production readiness / launch reviews** (Google SRE PRR, launch checklist) | Readiness is checked against operating the service users get | Readiness was checked for authority invariants; disk, backups and run blocks surfaced only in production (INSUFFICIENT_DISK twice) | **Readiness of the wrong thing** |

## 2. What this says about R2 (INFER)

R2 applied the *verification and control* half of large-organisation practice with great rigour — contracts, ADRs,
independent reviews, acceptance evidence — and skipped the *direction* half: validation against the stakeholder,
a business case re-checked at every stage, kill decisions, a customer-first product definition, tolerances, a single
owner, a simple working skeleton, and tailoring. Large organisations put the direction half first because
verification of the wrong thing is the most expensive failure (NASA's "continually asked" validation question; GDS's
discovery and alpha before build; PRINCE2's business case before and throughout).

## 3. The operating model that closes the gaps

Each element names the gaps it closes and the mechanism that enforces it (not an intention).

1. **Product charter, written backwards** (gaps 4, 5, 12). `docs/GOAL.md`: the sponsor's goal in the sponsor's own words, then a
   one-page PR/FAQ per form ("a drama episode from a story, as good as DramaClaw makes it, with no human step") and
   its quality criteria (both reviewers accept; the sponsor's eye; ≥ the donor baseline on the same story). Every
   ADR, plan and frozen document is subordinate and carries a "Charter check" line; a document the charter
   contradicts is superseded the same day (ADR status `superseded by …`). *Mechanism*: ADR template field + the
   per-turn hook prints the charter's first line.
2. **Validation first, at every stage** (gaps 1, 8, 9). For each form: *discovery* = run the donor itself on a
   reference story (the baseline film); *alpha* = the thinnest path that makes a film in our app by taking the donor
   pipeline whole; *beta* = our app ≥ baseline on several stories; *live* = automatic runs. A stage ends with an
   assessment against the charter's criteria, not against our contracts. *Mechanism*: a stage cannot be recorded as
   done without the film files and both verdicts linked in the tracker.
3. **Value gates with Go / Kill / Hold / Recycle** (gaps 2, 10). At each stage end and whenever the sponsor questions
   direction or speed, the agent presents: the evidence, the frozen clauses involved, and the four options. "Process
   only" is not an allowed answer to a direction question. *Mechanism*: the rule in AGENTS.md and the gate record
   template.
4. **Tolerances and management by exception** (gaps 3, 7). The sponsor sets tolerances once per stage — e.g. days,
   weekly quota share, releases per day, share of governance work (class G+Q ≤ 20 %) — and decides only product
   questions (goal, money, publication, direction). The main agent owns the product goal end to end, decides
   technical semantics after research and records them; reviews are run by the agent, never relayed. Only a
   tolerance breach goes to the sponsor. *Mechanism*: tolerances in `GOAL.md`; the weekly metrics report flags
   breaches.
5. **Metrics, weekly** (gaps 11, 14). From git, the tracker and the run ledger: releases, share fixing a previous
   release (change-failure rate), lead time from a defect seen to a released fix, runs blocked and by class (G/Q/C/D/
   E/T), films produced and their verdicts against the baseline. *Mechanism*: a script writes
   `docs/r2/evidence/WEEKLY_METRICS.md`; the agent reports it each Monday.
6. **Correction of errors with tracked actions** (gap 10). A block or defect that repeats, or a sponsor complaint
   about direction, gets a short COE: what happened, root cause by five whys, actions with owners, and a check one
   stage later that the cause did not recur. *Mechanism*: the run ledger links each repeat to its COE.
7. **Tailored governance** (gap 13). Every governance or authority mechanism has to name the risk it removes for a
   single-operator system and its recurring cost; one that cannot is removed. This is the input to the re-foundation
   decision (round 2, §5.6), not decided here.
8. **Rules as mechanisms** (gap 6; in place): codebase-memory first, `Donor:`/`Consumers:` in code commits, the
   per-turn reminder, the run block ledger, port lists at the end of donor research.

## 4. Resource use

The same model is what saves resources: validation first stops verification work on the wrong thing (39 % of
commits were docs-only, 44 % of recent releases repaired our own governance); tolerances stop the sponsor's time
going to relays (≈ 185 of 698 messages: confirmations, relayed reviews, pasted instructions, session and deploy relays); a donor baseline lets us take whole the part that already works instead of
re-deriving it; metrics show the waste each week instead of after two months.

## Sources

- NASA Systems Engineering Handbook, ch. 5 Product Realization (verification/validation; "Are we building the right
  product for our users and other stakeholders?"): https://www.nasa.gov/seh/5-realization ;
  https://www.nasa.gov/sites/default/files/atoms/files/nasa_systems_engineering_handbook_0.pdf
- NASA Software Engineering Handbook, SWE-029 Validation Planning: https://swehb.nasa.gov/display/SWEHBVB/SWE-029+-+Validation+Planning
- PRINCE2 principles (continued business justification, manage by stages, manage by exception, focus on products,
  tailor): https://en.wikipedia.org/wiki/PRINCE2 ; https://www.knowledgetrain.co.uk/res/ebooks/prince2-principles-ebook.pdf
- Cooper Stage-Gate, Go/Kill/Hold/Recycle: https://commons-os.github.io/patterns/stage-gate-process-cooper/ ;
  https://www.mindtools.com/?p=57792
- Amazon Working Backwards (PR/FAQ, mechanisms, single-threaded leaders), C. Bryar & B. Carr; summaries:
  https://review.firstround.com/how-to-build-an-invention-machine-6-lessons-that-powered-amazons-success/ ;
  https://www.aboutamazon.com/news/workplace/an-insider-look-at-amazons-culture-and-processes
- UK GDS Service Manual, phases and assessments: https://www.gov.uk/service-manual/phases/alpha ;
  https://www.gov.uk/service-manual/phases/beta ; https://www.gov.uk/service-manual/phases/live ;
  https://www.gov.uk/service-manual/service-assessments/get-your-service-on-govuk
- US Digital Services Playbook: https://github.com/usds/playbook ; https://tech.gsa.gov/guides/digital_services_playbook/
- Google SRE book, ch. 15 Postmortem Culture; ch. 32 engagement model (PRR):
  https://sre.google/sre-book/postmortem-culture/ ; https://sre.google/sre-book/evolving-sre-engagement-model/
- DORA four key metrics: https://www.atlassian.com/devops/frameworks/dora-metrics
- Architecture Decision Records and supersession: https://www.martinfowler.com/bliki/ArchitectureDecisionRecord.html ;
  https://gds-way.digital.cabinet-office.gov.uk/standards/architecture-decisions.html
- Books: J. Gall, *Systemantics* (1975); F. Brooks, *The Mythical Man-Month* (second-system effect);
  A. Cockburn, walking skeleton (*Crystal Clear*); C. Bryar & B. Carr, *Working Backwards* (2021).
