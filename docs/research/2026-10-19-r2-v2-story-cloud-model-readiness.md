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

## 8. Existing decisions and reusable configuration (sponsor question, 2026-10-19)

The sponsor asked whether the project already decided anything here and what existing configuration, including
the donors', can be reused.

### Decisions already on record (facts)

| Source | What it settles |
|---|---|
| Research 2026-10-18 §1 | "local Ollama first, cloud models later. Commercial quality is required; defects caused only by local-model limits are accepted." |
| Amendment rev5.1, decisions + Change P §1, §5 + Task7 runbook | Claude and OpenAI stay fixture-qualified until configured; `openai_chat` stays "for cloud later"; a provider without grammar support "needs its own qualification; it is never assumed"; the runbook covers "model swap to cloud later (with its own qualification)". |
| ADR 0051 | Text models are configured per task tier (simple / complex) with a default fallback and project-before-global resolution; every call site is mapped to a tier in code; the Agent SDK model is a separate configuration (ADR 0017). |
| ADR 0013, 0014 | Capabilities are declared per model; structured output falls back selectively (Instructor for OpenAI-compatible, prompt injection for Gemini) and is re-validated after a 200. |
| ADR 0039 | `assemble_backend(provider_id, media_type, model_id)` is the one seam that builds a backend from provider configuration, for built-in and custom providers. |
| ADR 0027, 0037 | Provider secrets live only in the database; built-in providers have typed secret columns. |
| ADR 0108 | Precedent for judging with independent models (two reviewers, disagreement retained). |

No ADR yet chooses a cloud provider for story authoring.

### Reusable configuration in this repository (facts)

- Built-in text backends already implemented: OpenAI (native `json_schema` strict + Instructor fallback),
  Gemini (response schema + prompt fallback), Grok, Ark, Agnes; custom-provider endpoints `openai-chat`,
  `gemini-generate`, `ollama-chat`. They report usage tokens and the finish reason.
- Credentials, base URLs and rate limiters for those providers are already configured through the settings UI
  and `assemble_backend`; nothing new is needed to reach OpenAI or Gemini.
- There is no Anthropic text backend: Anthropic credentials serve only the Claude Agent SDK (ADR 0017, 0051).
  Using Claude for story calls needs a new text backend or an adapter.

### Donor configuration (facts, pinned revisions)

| Donor | Model configuration |
|---|---|
| Novel Studio `9b690ae2` | one `default_model` per project, an OpenAI-compatible `baseURL`, `json_schema` strict structured calls |
| Shenbi `65ddfc26` | one model from environment (`SHENBI_LLM_MODEL`, default `deepseek-v4-flash` on an OpenAI-compatible base URL), `json_object` responses, per-skill temperature and max tokens in `executor_config.toml` |
| Huohuo `f104b85` | a **writer** text model and a separate **audit** model (`text_audit`): judging calls use the audit model when enabled and fall back to the writer model otherwise; an unresolvable audit model falls back with a warning; a "cross-model" flag warns when the writer and the detector are the same family |

### Inferences

- The writer/judge split is already a donor pattern (Huohuo `chatCompletionTextAudit`) and matches the tier
  idea of ADR 0051; it is the natural place to plug a stronger model.
- OpenAI and Gemini can be reached through backends and credentials that already exist (ADR 0039), so preparing
  them costs an adapter around an existing backend; Anthropic costs a new backend. This changes the effort
  comparison in §6, not the capability comparison in §3.
- Huohuo's silent fallback to the writer model must not be copied as is: a judge route that falls back must be
  recorded in the run (selection digest) so the Human sees that the check was not independent.

### Plan for the provider-neutral preparation (no vendor needed)

1. Writer and judge routes in the brief (judge defaults to the writer, recorded in the brief digest and the
   manifest), the driver using the judge route for audits, confirmation, critic, outline and plan review.
2. A model-client boundary in the gateway with a capability profile, so that an adapter around an existing
   backend (OpenAI, Gemini) or a new one (Anthropic) can be added and qualified without touching the driver.
3. The qualification harness (`task46_model_smoke`, the Task1 canaries) made provider-neutral, to run after a
   credential is configured.
