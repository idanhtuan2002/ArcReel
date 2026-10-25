# Shared backend model selection

Branch: `feat/v2-explicit-text-backend`.
Worktree: `/home/anhtuan/.codex/worktrees/c1b3/content-production-os`.
Plan baseline: `b2d65f757da4ff874bb42d1f81064ded52d66fbe`.

## Implemented interface

`TextGenerator.create(task_type, project_name=None, *, provider_id=None, model_id=None)` accepts an exact provider/model pair. Omitting both preserves existing task/project resolution. Partial pairs, unknown or non-text builtins, noncanonical custom IDs and unsupported known vision routes fail before assembly. An unknown task fails. Existing assembly owns credentials and release qualification; existing Ledger owns generation accounting/admission. A custom loader's default fallback is rejected if its actual model differs from the explicit selection. No provider SDK, database schema, billing policy or persistent default is added.

The operator entrypoint is `python -m lib.text_backends.console` in this checkout and the backend's configured environment. It uses the application's runtime qualification installer. It does not initialize/migrate a database or create qualification records.

```bash
# Run from the feature checkout, using its project dependencies.
uv run python -m lib.text_backends.console --list

# Choose an exact ID from the list; construction only, no generation request.
uv run python -m lib.text_backends.console --provider gemini-aistudio --model gemini-2.5-flash --check

# This sends a generation request and can incur provider charges.
uv run python -m lib.text_backends.console --provider gemini-aistudio --model gemini-2.5-flash --prompt 'Write one short greeting in Vietnamese.' --max-output-tokens 64
```

For another provider, use its exact `provider_id` and `model_id`. Custom routes accept the existing `custom-N` identity and enabled model ID from backend configuration; `--list` lists registered builtins only. Output is JSON. Provider failures return a sanitized `MODEL_CALL_FAILED` with exit code 1, without printing raw credential-bearing exceptions. Troubleshoot through existing protected backend diagnostics.

The command needs the existing backend database and credential/master-key context (`DATABASE_URL` or `ARCREEL_DATA_DIR`, plus the deployment's existing encryption configuration). Do not point it at an empty checkout database or copy keys into prompts/CLI flags. Use the same release mode and governance context as the backend; never downgrade release mode to bypass qualification. Listing indicates registered metadata only. `--check` indicates successful construction, not working credentials, quota or remote availability. The default output limit is 256 tokens; explicit positive limits are supported. Existing adapter retries and ledger pricing behavior remain in effect.

## Verification and limits

Automated tests use disposable config/ledger databases and replace SDK construction or generation boundaries. They exercise exact native Gemini/Grok/OpenAI attribution, real assembly/ledger, fallback rejection, capability/qualification refusal, legacy resolution and console parsing/error sanitization. Actual CLI listing has been exercised: 42 registered text models across 9 provider IDs. Final exact code SHA, command outputs and review verdict are recorded in `R2_EXPLICIT_TEXT_BACKEND.json` after the verification gate.

No cloud generation has been performed against real credentials. No production activation, push or merge has occurred. The V2 web UI and Story Authoring selection remain unchanged; Story Authoring remains Ollama-only. Native Anthropic Messages is not registered; compatible custom gateways are not native Claude support. Earlier pure catalog/metering/compiler tests are not evidence for this connection. Historical whole-backend Story Authoring baseline failures are outside this affected-domain run and are not claimed fixed.

Preserve the two unrelated old Gemini draft files. M9/M10 remain paused. Further UI/story/cloud acceptance and production release are separate work.
