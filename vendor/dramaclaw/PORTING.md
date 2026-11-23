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
