# R2 V2 story authoring — readiness for a stronger cloud model (2026-10-19)

Sponsor instruction (2026-10-19): research and prepare so that a stronger cloud model can be used later. Nothing
is sent to a cloud provider, no credential is requested and no policy is relaxed by this work.

## 1. Why (internal evidence)

`docs/r2/evidence/R2_STORY_AUTHORING_QUALIFICATION.md`, live runs 1–10:

- Every structural pipeline defect the runs exposed is fixed and tested (cap per round, copy/replay removal,
  plan review and bounded replan, grammar length bounds, judgment retry, string ceilings, blocking-claim
  confirmation).
- With `qwen3.5-vimax:9b` the prose is coherent, in voice, without copying or loops.
- No run sealed chapter 1. The remaining blocker is the memo-compliance hard gate judged — and confirmed — by
  a 9B model: claims are frequently strained, and the same model confirming its own claim is not independent.
  Chapter 1 alone costs 64–87 of the 132-call run ceiling.

Inference: the judge (L2 audits, confirmation, L3 critic, plan/outline review) is the first place a stronger
model pays off; drafting can stay local.

## 2. What the gateway relies on today (internal)

`server/story_authoring/generation.py` (`AuthoringTextGateway`) qualifies only the native Ollama `ollama-chat`
endpoint (Change P) and enforces:

| Guarantee | Ollama mechanism |
|---|---|
| Input fits the context, fail-closed | COUNT probe (`num_predict` 1) returns the exact `prompt_eval_count`; `truncate:false` → HTTP 400 instead of silent truncation |
| Truncation is detected | `done_reason` must be `stop` |
| No CJK in any string | grammar `pattern` on every string, plus the post-hoc detector |
| Prose shape | `minItems`/`maxItems` paragraphs and a `{n,m}` length range inside the pattern (Ollama ignores `minLength`/`maxLength` beside a pattern) |
| Reproducibility | `seed` from the step id |
| Output validity | strict schema validation, paragraph count and length checks after generation |

The post-hoc validation (schema, CJK detector, paragraph checks, L1) already runs for every output, whatever the
provider; only the pre-generation guarantees depend on the provider.

## 3. Providers (primary sources, fetched 2026-10-19)

| Capability | Ollama local | Ollama Cloud | Anthropic Claude | OpenAI | Google Gemini |
|---|---|---|---|---|---|
| Schema-constrained JSON | yes (`format`) | **no** — "Ollama's cloud currently does not support structured outputs" | yes, `output_config.format` `json_schema` | yes, strict `json_schema` | yes, response schema |
| `pattern` (no-CJK) | yes | — | yes; simple `{n,m}`; "complex `{n,m}` quantifiers with large ranges" unsupported | yes | not listed |
| `minItems`/`maxItems` | yes | — | `minItems` 0 or 1 only | yes | yes |
| `minLength`/`maxLength` | ignored beside `pattern` | — | unsupported | unsupported | not listed |
| Input token count before sending | exact (probe) | not documented | `count_tokens`, free, documented as an **estimate** | not verified | not verified |
| Truncation signal | `done_reason` | `done_reason` (same API) | `stop_reason` `max_tokens` | `status: incomplete`, `max_output_tokens` | not verified |
| Seed | yes | not verified | not verified | not verified | not verified |
| Data use (paid API) | local | "not used to train models" | not verified here | not verified here | paid tier: not used to improve products |

Prices per million tokens (input / output), standard tier, as published on 2026-10-19:

| Model | Input | Output |
|---|---|---|
| Claude Opus 5.5 | $4 | $20 |
| Claude Sonnet 5.5 | $2 | $10 |
| Claude Haiku 5.5 (≤100k prompt) | $0.10 | $0.50 |
| OpenAI gpt-6.1-sol | $2 | $10 |
| OpenAI gpt-5.6-sol | $4 | $20 |
| Gemini 4 Argon (to 2026-11-30) | $2 | $10 |
| Gemini 3.8 Flash (to 2026-12-31) | $0.75 | $3.75 |

Sources: platform.claude.com structured-outputs, token-counting and pricing pages; developers.openai.com
structured-outputs (Supported schemas) and pricing; ai.google.dev structured-output and pricing;
docs.ollama.com cloud and structured-outputs; ollama.com/search?c=cloud.

## 4. Cost estimate (inference)

Measured volumes on chapter 1 (runs 8 and 10, including retries and repairs): 0.37–0.53 M input and 53–63 k
output tokens. Extrapolated to a whole story with a stronger judge (fewer repair loops): about 1.0–1.6 M input
and 0.15–0.20 M output tokens; the judge's share is about 0.35 M input and 0.04 M output.

| Route | Per story (estimate) |
|---|---|
| Everything on Claude Sonnet 5.5 / gpt-6.1-sol / Gemini 4 Argon | ≈ $3.5–5 |
| Everything on Claude Opus 5.5 / gpt-5.6-sol | ≈ $7–10.5 |
| Judge only on Claude Sonnet 5.5 (writer local) | ≈ $1.1 |
| Judge only on Claude Opus 5.5 (writer local) | ≈ $2.2 |
| Judge only on Claude Haiku 5.5 | ≈ $0.05 |

These are planning estimates, not measurements; Task6 measures them.

## 5. Unknowns

- Vietnamese literary quality of each cloud model on our fixtures (needs the same-fixture differential).
- Whether a cloud model's count endpoint matches billed input closely enough for a fail-closed context check
  (Anthropic says "estimate"; OpenAI and Gemini not verified).
- Seed support and determinism on each cloud API.
- Whether Ollama Cloud adds structured outputs later.

## 6. Options

1. **Role routing + one cloud adapter for the judge (recommended).** Split the run's model selection into a
   writer route (drafting, planning, repair) and a judge route (L2 audits, confirmation, L3 critic, outline and
   plan review, packaging verification). The writer stays on local `qwen3.5-vimax:9b`; the judge can be local
   now and a cloud model later, which also makes the confirmation independent (different model). Cost about
   $1–2 per story on Sonnet/Opus-class judges.
2. **Everything on one cloud model.** Simplest operationally, highest quality ceiling, $3.5–10 per story, and the
   whole manuscript leaves the machine.
3. **Ollama Cloud.** Reuses the native API, but structured outputs are unsupported today, so every structured
   call would rely on post-hoc validation and retries only; not recommended for the judge.

## 7. Preparation that is provider-neutral (no cloud call, no credential)

- A provider-capability profile in the gateway: which pre-generation guarantees a route provides (exact count,
  pattern, item bounds, seed). Missing guarantees fall back to the post-hoc checks that already run, and a count
  that is only an estimate gets a safety margin.
- A `StoryModelClient` boundary so that an Anthropic, OpenAI or Gemini adapter plugs in beside Ollama, tested with
  recorded or mock transports.
- Writer/judge role routing in the brief and the driver; the judge route defaults to the writer route.
- A qualification probe script per adapter, run only after the Human configures a credential.

Decision needed from the Human before an adapter is built: which cloud provider (and which model) to prepare
first. Recommendation: Anthropic Claude (Sonnet 5.5 as judge; Opus 5.5 to compare) because it supports the
no-CJK `pattern`, has a free count endpoint, and its price sits at the low end of the flagship tier; OpenAI is
the alternative with `pattern` and item bounds.
