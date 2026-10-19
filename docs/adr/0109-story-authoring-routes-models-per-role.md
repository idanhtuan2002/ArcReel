---
status: proposed
---
# Story authoring routes models per role; a cloud model enters only through its own qualification

**Context.** Ten live runs on local 9B models (`docs/r2/evidence/R2_STORY_AUTHORING_QUALIFICATION.md`, Task4.6)
fixed every structural pipeline defect they exposed, and with `qwen3.5-vimax:9b` the prose became coherent. Runs
still stop in chapter 1 because the memo-compliance hard gate is judged, and confirmed, by the same 9B model. The
sponsor asked (2026-10-19) to prepare for a stronger cloud model later, without choosing a vendor yet. Research:
`docs/research/2026-10-19-r2-v2-story-cloud-model-readiness.md`.

## Decision

1. **Two routes per run.** A brief names a writer route (drafting, planning, repair, packaging) and may name a
   judge route (outline and chapter-plan review, chapter audits, the confirming second reading, the manuscript
   critic, the blurb check). Without a judge route the writer route reviews. This follows Huohuo's writer/`text_audit` split
   (`f104b85`, `chatCompletionTextAudit`), minus its silent fallback: the judge route is part of the brief digest
   that Gate A greenlights and of every review node's fingerprint, so the Human sees whether review was
   independent, and changing it stales exactly the review nodes.
2. **Both routes are qualified routes.** Today only the native Ollama `ollama-chat` endpoint is qualified
   (amendment Change P); a judge route on another Ollama model (local or self-hosted) works now.
3. **A cloud provider enters through its own qualification, never by assumption.** Before a provider can serve
   a route, its adapter states which pre-generation guarantees it provides, and the qualification run proves
   them:

   | Guarantee | Required behaviour when the provider lacks it |
   |---|---|
   | Exact input-token count before generating | an estimate is accepted only with a recorded safety margin under the context limit; billed usage is reconciled after the call |
   | Truncation signal | none — a provider without a reliable stop reason is not qualified |
   | No-CJK `pattern` in structured output | the post-hoc CJK detector and retry carry the invariant alone; recorded per route |
   | Item and length bounds in the grammar | the post-hoc paragraph and length checks carry them; recorded per route |
   | Seed | runs are not reproducible on that route; recorded per route |

   The post-hoc checks (schema, CJK detector, paragraph count and length, L1, quote verification) already run
   for every output regardless of provider.
4. **No vendor is chosen by this ADR.** The adapter is built for the provider the Human chooses; OpenAI and
   Gemini can reuse the existing backends and credentials (ADR 0039), Anthropic needs a new text backend
   (its credentials serve only the Agent SDK, ADR 0017/0051).

## Rejected

- **Huohuo's silent fallback** from the audit model to the writer model: it hides that review was not
  independent.
- **Ollama Cloud for the judge:** its documentation states that structured outputs are not supported, so every
  judgment would depend on retries alone.
- **One global model setting** (Novel Studio's `default_model`, Shenbi's single `SHENBI_LLM_MODEL`): it cannot put
  a stronger model where it pays most (review) while drafting stays local.
- **A provider-neutral client interface before a second provider exists:** an interface with one implementation
  is shallow (the same reasoning as ADR 0039's rejected `BackendRequest`); it is written with the first cloud
  adapter.

## Consequences

- Implemented: brief `judge_selection`, driver judge gateway, executor resolves both routes before any call,
  service and route accept an optional judge provider and model (`0b7f18cc`).
- A cloud adapter later is a bounded change: one adapter, its qualification run, a credential the Human
  configures in the settings UI (ADR 0027: secrets only in the database), and the brief naming it as the judge or
  writer route.
- Cost and data leave the machine only when the Human configures a cloud route and greenlights a brief that
  names it.
