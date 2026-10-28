# M10-B7 pilot runbook (export-only, Human decisions by the sponsor)

Preregistration: `R2_M10_B7_PILOT_PREREGISTRATION.json` (frozen before any run). Order: Western explainer →
vertical factual Short → `zh-shuang`. Nothing here uploads or calls a provider.

For each cohort:

1. **Sponsor picks the approved V2 final** (artifact key + master version). The agent records it in
   `R2_M10_B7_PILOT_<cohort>.json` before any check.
2. **Agent prepares the V2 profile draft** with the cohort's platform constraints (dimensions, duration window,
   locale, rules) → **sponsor publishes it** through the interactive A3 custodian (Human gate).
3. **Agent runs the probes and prepares the run**; the sponsor records the Human narrative observation; the run is
   sealed → **sponsor issues the disposition** (PASS/REWORK/WAIVE) through the A6 custodian (Human gate).
4. **Agent saves the clean package draft and the seeded-defect revisions** on the Packaging page and runs the check
   for each; the dossier records caught/missed per defect id.
5. **Sponsor reviews the clean final's findings** (true/false positive per finding) and, if useful, corrects the
   package through the page and re-checks.
6. **Sponsor previews and selects** the package as showrunner (Human gate).
7. **Agent exports twice with fresh commands**, records receipt digests (determinism), wall time, worker peak
   memory and archive size, and downloads the archive once.
8. The dossier is complete when every preregistered metric has a value; the cohort passes only against the frozen
   thresholds.

Stop points for the agent: steps 2, 3, 5 and 6 need the sponsor in an interactive session. The embedded agent's
token cannot pass these gates by design.
