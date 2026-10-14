# R2-M8D D3: scoped recommendation lifecycle

**Parent plan:** [`2026-09-13-r2-m8d-learning-recommendations.md`](2026-09-13-r2-m8d-learning-recommendations.md), Task D3.
**Spec:** [`2026-09-13-r2-m8-canvas-learning-multiformat-design.md`](../specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md), §3 invariant 7, §5, §6, §9 and §12 Gate D.
**Builds on:**
- D1 observations: `m8_learning_observations`, with cutoffs at or before the watermark;
- D2 adapters and derived features.

## Current state (facts)

- **The contracts exist** in `r2/contracts/advanced_creative.py`:
  - `LearningRecommendation`: id, evidence observation ids, hypothesis, applicability, exclusions, confidence, guardrails, lineage, `expires_at`;
  - `RecommendationDecision`: id, recommendation id, disposition, `expected_recommendation_digest`, actor, reason, `governed_proposal_ref`, `decided_at`;
  - `RecommendationDisposition`: `ACCEPT`, `REJECT`, `DEFER`, `REQUEST_EXPERIMENT`;
  - `ExperimentDesign`.
- **The port** `RecommendationService.propose/decide` exists in `r2/advanced_creative/ports.py`.
- **Spec §9:**
  - V1 means transparent cohort summaries, rule-based evidence thresholds, offline replay and a Human disposition. There is no trained ranker.
  - Only `CONCURRENT_RANDOMIZED` and `PLATFORM_MANAGED` evidence may use causal language.
  - Holdout is project-disjoint, then future-time, and sibling revisions never split.
  - `generic-western` and `zh-shuang` are never pooled.
  - Evaluation is pre-registered before results (`M8_EVALUATION_NOT_PREREGISTERED`).
- **No code exists** for summaries, rules, replay, recommendation persistence, routes or UI.

## Decisions (agent-chosen under sponsor delegation)

1. **Cohort key.** A cohort is defined by:
   - `creative_profile_id` and `creative_profile_version` from the lineage;
   - `source_family`, `metric_name`, `metric_definition_version` and `window.aggregation`;
   - one split dimension, `format_profile_ref` in V1.

   Evidence for one recommendation must share the profile, family, metric, definition and aggregation. Anything else is `M8_PROFILE_COHORT_LEAK`.
2. **Transparent summary.** Each cohort reports:
   - `n`, the missing count by reason;
   - mean, median, min and max of the present values;
   - the observation ids.

   Missing values are counted and never imputed.
3. **One rule type in V1: `compare_cohorts@1`.** It compares two arms of the split dimension.
   - It needs at least `min_per_arm` present values in each arm.
   - It needs a relative difference of means of at least `min_relative_lift`.
   - When it fires, it yields a hypothesis, the applicability (profile, metric, arms), exclusions (missing counts), a confidence equal to the share of present values, guardrails, and evidence equal to every input id.
4. **Causal language.**
   - The hypothesis is generated from a template.
   - It reads "is associated with" unless every evidence observation has `experiment_design` in {`CONCURRENT_RANDOMIZED`, `PLATFORM_MANAGED`} with one shared `exposure_ref` surface. Only then may it read "caused".
   - A checker refuses causal verbs in any associative hypothesis, including one a caller supplies.
5. **Offline replay.** `split_holdout(observations, eval_share, cutoff)`:
   - assigns whole projects to train or eval by a stable hash, so siblings never split;
   - keeps only eval observations whose window starts after the train cutoff.

   `replay(protocol, train, eval)` runs the rule on the train set and reports whether the direction holds on the eval set. A protocol is `{rule, params, cohort, baseline arm, effect threshold, window, exclusions}` with a digest and a `registered_at`. Replay refuses with `M8_EVALUATION_NOT_PREREGISTERED` when any eval observation was ingested before `registered_at`.
6. **Persistence** (migration `915c4a0e0001`), all append-only and scoped:
   - `m8_learning_recommendations`: the body JSON and digest, the evidence ids, the `evidence_cutoff` watermark, the rule id/version, a proposal key and the command id.
   - `m8_learning_recommendation_decisions`: append-only. At most one terminal decision (`ACCEPT`/`REJECT`) per recommendation. `DEFER` and `REQUEST_EXPERIMENT` may precede it.
7. **Currentness at decision.**
   - The decision names `expected_recommendation_digest`.
   - The recommendation must not be expired.
   - Every evidence observation must still be the tip of its correction chain.

   Otherwise the decision is refused as stale (`m8_recommendation_stale`).
8. **Repeat rejection.** The proposal key is the digest of the rule id/version and the applicability.
   - Proposing the same key after a `REJECT` is refused unless the evidence includes at least one observation that the rejected recommendation did not use.
9. **Authority boundary.**
   - `ACCEPT` records a `governed_proposal_ref` (`learning-proposal:<decision_id>`) and writes nothing else.
   - The recommendation service has no production, Canon, Narrative, policy, routing or governance write port. An architecture test enforces this.
   - Decisions need an interactive session user; an API key is refused.
10. **Routes** under `/projects/{project}/m8/learning/`:
    - `POST observations`;
    - `POST recommendations/evaluate`, which runs `compare_cohorts@1` at the scope watermark and proposes;
    - `GET recommendations`;
    - `POST recommendations/{id}/decisions`.
11. **UI.** A Learning page lists recommendations with:
    - the hypothesis and an associative/causal badge;
    - the evidence summary per arm and the expiry;
    - the decision history.

    It decides with a required reason and shows server refusals. Strings are in zh/en/vi.

## Packets

- **D3a, pure:**
  - `r2/learning/cohorts.py`: key, summary, the rule, the hypothesis template and the causal checker;
  - `r2/learning/replay.py`: holdout split, protocol and replay;
  - unit tests.
- **D3b, backend:**
  - migration and models;
  - `LearningRecommendationRepository`;
  - `server/services/learning.py`;
  - the router;
  - SQLite and PostgreSQL tests;
  - the architecture boundary.
- **D3c, frontend:** the page, the API, i18n and Vitest. Then `pnpm check` and a browser check.

Each packet runs only its related tests, the static gates and an independent Codex review.
