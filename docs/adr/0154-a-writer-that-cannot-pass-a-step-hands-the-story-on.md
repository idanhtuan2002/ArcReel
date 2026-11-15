---
status: accepted
---

# A writer that cannot pass a step hands the story on

Decided 2026-11-15 by the main agent on the sponsor's rule "chúng ta ưu tiên cao nhất cho chất lượng", after the cloud-writer trial runs.

ADR-0139 moves a story to the project's next writer only when its model fails (`MODEL_UNAVAILABLE`: quota, outage). In the trial the free cloud writers failed differently: `ernie-5.5-flash-preview:free` reasoned past the whole 16,384-token budget on three draws of the story bible (its reasoning varies from 12k to 51k characters on the same prompt; OpenRouter's `reasoning.effort=low` does not bound it), and `particle-1:free` once on the outline. Each time the step spent its call cap without an acceptable output and the story stopped `BLOCKED_QUALITY`, so the whole run failed although the next writers on the list pass the same step.

1. A story whose step spent its call cap without an acceptable output (block reason `CAP_EXHAUSTED`) is treated like one whose model failed: the production run moves it to the next writer the settings list, under the same rules (held to the run's policy, counted as a STORY repair up to `unit_repair_limit`). The move reopens the unfinished nodes (`reopen_unconverged`), so the step's cap starts again for the new writer; everything already written stays.
2. The new writer's output meets exactly the same checks; nothing is relaxed. A story blocked on its content (an outline that still fails its deterministic checks, review findings) does not change writer: that is the story's problem, not the writer's.
3. One predicate, `needs_next_writer`, decides for both the reroute and the production run's story adapter.

Amended 2026-11-15 (trial 4): a judgment (chapter review, outline review, any `_judge` node) whose three attempts all fail with a retryable code (`OUTPUT_TRUNCATED`, `OUTPUT_INVALID`, …) now blocks with the same `CAP_EXHAUSTED` marker. Before, the raw step error (`OUTPUT_TRUNCATED at chapter_review[1]@r0.0.3#14`) stopped the run without the marker, so the story did not move although the reviewer was the writer's own route. A story with a separate judge route still moves its writer only; the judge is qualified separately.
