# V2 Gemini text model catalog takeover

Base: `2626fc10026e69064888832f9e68199edd631ad1` (release branch after r2-v2.0.5).
The user requested continuation of Claude Code's Gemini cloud-model work.
The incoming registry change and its backup remain unchanged in the original
release worktree; this fix is isolated on `fix/v2-gemini-text-catalog`.
M9 and M10 remain paused.

## Scope and existing implementation

Reuse the built-in AI Studio provider, database credential custody, Google SDK,
GeminiTextBackend and pricing model. Add the six inherited catalog entries with
explicit rates/capabilities; include registered text models in the existing
Gemini connectivity discovery while preserving image/video discovery. Embedding
and TTS models do not become text models through a name-prefix heuristic.

No key is copied into source, environment variables or evidence. The existing
saved credential is read only for metadata and bounded synthetic checks. No
project/global model selection, route qualification or running deployment is changed.
The Story gateway still requires its separate cloud qualification (ADR-0109).

## Primary-source checks, 2026-10-23

Google's [model catalog](https://ai.google.dev/gemini-api/docs/models) and the
saved key's actual `models.list` response include all six entries. The API
returned 60 models. Listing proves visibility, not successful generation or
account billing-tier eligibility.

[Google pricing](https://ai.google.dev/gemini-api/docs/pricing) distinguishes
free and paid tiers. Gemma 4 is free-only; Gemini free access has model/account
limits. Registry Gemini prices are standard paid token estimates, not a promise
that the user's key is billed or free. Rates per million input/output tokens:

| Model | Input USD | Output USD |
| --- | ---: | ---: |
| gemini-3.8-flash | 0.75 | 3.75 |
| gemini-3.6-flash | 0.75 | 3.75 |
| gemini-2.5-flash | 0.30 | 2.50 |
| gemini-3.5-flash-lite | 0.30 | 2.50 |
| gemma-4-31b-it | 0 | 0 |
| gemma-4-26b-a4b-it | 0 | 0 |

The 3.8/3.6 published rates above apply through 2026-12-31 and need a future
pricing refresh; no new time-dependent pricing engine is introduced.
[Deprecations](https://ai.google.dev/gemini-api/docs/deprecations) limits 2.5
access to existing users; keep it available when returned by the configured key.
Gemini text capabilities follow the official model pages, including
[3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash) and
[3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite).
Gemma is declared text-generation only; no unqualified structured/vision claim
is added.

## Validation and limits

- RED: four new discovery/pricing regressions failed; 26 existing cases passed.
- GREEN: the same files passed all 30 tests.
- Affected provider/config/pricing/Gemini suites: 554 passed, 8 warnings, no skips
  or failures. Unit HTTP requests use the real SDK with intercepted transport.
- Seven backend static/import/dependency/audit/diff checks passed; type checking
  reports zero errors/warnings. The initial conflicting type-CLI flags failed
  before analysis; the corrected single environment selector passed.
- Live synthetic, free-only model checks: Gemma 4 26B A4B returned OK using the
  existing Gemini backend and a system prompt; 16 input and 1 output token.
  Gemma 4 31B exceeded the 25-second outer deadline and is not counted as a
  successful generation. No blind retry or paid Gemini generation was performed.
- These checks do not qualify Story authoring, schema generation, a paid route,
  every model's uptime, or production deployment.

The graph index is the older r2-v2-main project, used provisionally; affected
paths and callers were checked and the actual release source read directly.
The existing release backup, unrelated processes and project settings are preserved.
Release plan Task7 requires explicit Human confirmation for push/production
activation; this change is prepared for that final approval.
