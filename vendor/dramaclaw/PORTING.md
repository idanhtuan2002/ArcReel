# DramaClaw identity planner — ported whole

Donor: DramaClaw @ `b299bfd` (local checkout `~/.cache/r2-donors/dramaclaw-full`). Decision: ADR-0168.
Installed as the path package `dramaclaw-identity` (root `pyproject.toml`, `[tool.uv.sources]`); the import name stays
`novelvideo`, so donor files and tests run without edits.

## Copied verbatim (no edits)

| File | Donor path |
|---|---|
| `src/novelvideo/agents/identity_planner.py` | `src/novelvideo/agents/identity_planner.py` |
| `src/novelvideo/models.py` | `src/novelvideo/models.py` |
| `src/novelvideo/time_of_day.py` | `src/novelvideo/time_of_day.py` |
| `src/novelvideo/utils/asset_names.py` | `src/novelvideo/utils/asset_names.py` |
| `src/novelvideo/utils/derived_scenes.py` | `src/novelvideo/utils/derived_scenes.py` |
| `src/novelvideo/utils/source_language.py` | `src/novelvideo/utils/source_language.py` |
| `src/novelvideo/utils/identity_resolver.py` | `src/novelvideo/utils/identity_resolver.py` |
| `src/novelvideo/shared/env_guard.py` | `src/novelvideo/shared/env_guard.py` |
| `tests/test_identity_planner_appearance_validation.py` | `tests/` (same name) |
| `tests/test_identity_planner_language.py` | `tests/` |
| `tests/test_identity_planner_character_promotion.py` | `tests/` |
| `tests/test_character_identity_age_group.py` | `tests/` |
| `tests/test_source_language.py` | `tests/` |

Dependency versions are the ones DramaClaw's `uv.lock` resolves (`pydantic-ai-slim==1.107.0`, `langid`, `langdetect`,
`wordninja`, `pypinyin`).

## Written by us (seams)

| File | What it replaces |
|---|---|
| `src/novelvideo/__init__.py`, `agents/__init__.py`, `utils/__init__.py`, `shared/__init__.py` | Donor inits re-export modules that are not ported (episode planner, keyframe builder, logging); ours are empty. |
| `src/novelvideo/config.py` | The three members the planner reads. `get_newapi_text_pydantic_model` calls a host factory (`set_text_model_factory`) instead of DramaClaw's newAPI gateway; the other two are donor code. |
| `src/novelvideo/sqlite_store.py` | Only `load_episode_planning_content`, copied verbatim; the SQLite store is not ported. |
| `src/novelvideo/knowledge_pipeline.py` | `is_structured_pipeline` is always true: ArcReel has no Cognee graph, so the planner takes its structured path (aliases from the character table). |
| `src/novelvideo/cognee/__init__.py`, `cognee/ladybug_access.py` | Typing-only import and the graph lock of the legacy path, which is never reached. |

## Not ported, and why

- `tests/test_identity_runner_result.py`: tests DramaClaw's Celery task runner (`task_backend/runners/identity.py`);
  ArcReel runs the planner from its own task, covered by the adapter's tests.
- Cognee graph search (legacy path): ArcReel projects have no knowledge graph.

## Run the donor tests

    uv run python -m pytest vendor/dramaclaw/tests -q

At port time: 113 passed.

## Assembly (ADR-0170): what is and is not taken from DramaClaw

DramaClaw runs **whole** from its release images (`assembly/deploy/dramaclaw/`); nothing of it is copied into our code.

**Why not ported: the Hermes toolset** (`.hermes/plugins/dramaclaw/__init__.py`, ~2 400 lines). It is the tool layer of
DramaClaw's built-in chat agent (Hermes): each tool is one REST call wrapped for an LLM — results come back as JSON
strings with chat hints in Chinese, UI render specs and truncated lists, and it needs Hermes' `tools.registry` shim to
load. Our connector is a program, not an agent, so it calls the same REST endpoints directly and reads JSON; the
toolset stays the reference for which endpoint and arguments each step uses (and for the error codes it recognises,
e.g. `voice_prereq_required`). DramaClaw's own agent keeps using it inside DramaClaw.

**Approved donor changes (GOAL rule 1)**, made only in a rebuilt image from the pinned checkout and listed here when done:
- Vietnamese interface (`frontend/src/i18n/index.ts` `SUPPORTED`, header switcher, `public/locales/vi/translation.json`).
- Inline media relay option (`storage/media_relay.py`: a provider returning a `data:` URI).

## Hermes toolset and playbooks (assembly connector, 2026-11-23)

- Donor: DramaClaw @ b299bfd (`.hermes/plugins/dramaclaw/`, `.hermes/skills/dramaclaw/`, `tests/test_hermes_dramaclaw_plugin.py`),
  copied unchanged to `vendor/dramaclaw/hermes/` (the test's plugin path adjusted to the new layout only).
- Loader: `assembly/connector/dramaclaw_tools.py` ports the registry shim and plugin loader of
  `src/novelvideo/chat/dramaclaw_mcp.py` (DramaClaw's own bridge for external agents), minus the MCP stdio server.
- Auth: DramaClaw's CE owner mode (`DRAMACLAW_CE_OWNER=1`, loopback `DRAMACLAW_API_URL`), which the donor documents for
  external clients on the same machine.
- The connector follows the skill's playbooks (`init.md`, `episode.md`, `resume.md`, `references/pipeline-details.md`)
  in the playbooks' "auto-advance" mode: one write task per round, rounds driven by `pipeline/status.next_step`.
- Donor gap (not changed): Custom mode cannot map `DC-character-builder-LLM` (`CHARACTER_BUILD_MODEL`) because
  `frontend/src/lib/feature-models.ts` lists no `CHARACTER_BUILD` feature; character extraction then fails with
  "No available channel". Handled by configuration: `CHARACTER_BUILD_MODEL=DC-scene-builder-LLM` in
  `assembly/deploy/dramaclaw/override.yml` (the backend reads the env name first, `config.get_newapi_text_model_name`).
- Donor facts found by film 1 (not changed): the rewrite task type is `content_rewrite` (the Hermes references say
  `content_rewriter`); generated prose is zh or en only (`utils/source_language.py`), so the connector never calls
  `rewrite/generate` for Vietnamese stories and the script is cut from the raw Vietnamese text.
