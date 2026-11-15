---
status: accepted
---

# Cloud story calls carry a reasoning allowance

Decided 2026-11-15 by the main agent during the first trial run with a cloud writer (sponsor: "tiếp tục sửa").

The story steps cap visible output at 4,096 tokens, and a cloud call was sent and reserved with exactly that cap. Every free cloud writer that writes good Vietnamese (OpenRouter `ernie-5.5-flash-preview:free`, `particle-1:free`, BytePlus `deepseek-v4-1-flash`) is a reasoning model, and providers count reasoning tokens against the request's output limit. Reproduced with the app's own prompts: `ernie` stopped the seed at 1,995 characters after 4,096 tokens, `particle-1` spent 2,768 tokens on a 362-character outline review, `deepseek-v4-1-flash` spent all 4,096 on reasoning and returned nothing. Both trial runs stopped `BLOCKED_QUALITY` on `OUTPUT_TRUNCATED` (seed, then outline review).

1. A cloud story call is sent and reserved with the step's cap plus `REASONING_ALLOWANCE` (12,288) output tokens, on both the OpenAI-compatible and the Gemini transport. A reply over that budget is `COUNT_MISMATCH` as before; a reply that stops inside it is accepted and checked exactly as before.
2. A run's output token budget grows per call by half the allowance when its brief is priced for the cloud (`output_per_call`): the brief, a book part, a prior's extra calls, a short story's digests, a top-up and a reroute all scale by it. Local briefs are unchanged (their approval digest stays the shipped one).
3. Money stays bounded by the brief's USD cap and route prices; the free routes are priced at 0.

Not changed: a writer that returns output the checks reject still does not move to the next fallback writer (ADR-0139 moves on route failure or quota).

Amended 2026-11-15 (trial 5): the allowance is 28,672. With 12,288 the chapter review (2,048 visible + 12,288) was truncated on every free writer in turn: `chapter_review[2]` used 7–8.6k output tokens when it finished and ran past 14,336 on three of four draws of particle-1, deepseek-v4-1-flash and ernie alike. The free models allow at least 131k output tokens and are priced at 0, so the larger budget costs time, not money.
