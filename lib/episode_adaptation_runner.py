"""Run one episode adaptation through the project's text model (ADR-0114); see :mod:`lib.episode_adaptation`."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from lib.episode_adaptation import (
    ADAPTATIONS_DIR,
    MAX_ATTEMPTS,
    AdaptationError,
    EpisodeAdaptationDraft,
    adaptation_record_relpath,
    adaptation_text_relpath,
    build_prompt,
    check_adaptation,
    read_inputs,
    render_script,
    screen_seconds,
)
from lib.episode_paths import episode_source_relpath
from lib.json_io import atomic_write_bytes, atomic_write_json
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult

type Generate = Callable[[TextGenerationRequest], Awaitable[TextGenerationResult]]


async def adapt_episode(project_path: Path, project: Mapping[str, Any], episode: int, *, generate: Generate) -> dict:
    """Adapt ``episode`` and write its script and record; raises :class:`AdaptationError` when no draft passes."""
    inputs = read_inputs(project_path, project, episode)
    attempts: list[dict[str, Any]] = []
    problems: list[str] | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        result = await generate(
            TextGenerationRequest(prompt=build_prompt(inputs, problems), response_schema=EpisodeAdaptationDraft)
        )
        try:
            draft = EpisodeAdaptationDraft.model_validate(json.loads(result.text))
        except (ValueError, ValidationError) as error:
            problems = [f"the answer is not valid JSON for the schema: {str(error)[:300]}"]
            attempts.append({"attempt": attempt, "problems": problems})
            continue
        problems = check_adaptation(draft, inputs)
        attempts.append({"attempt": attempt, "problems": problems})
        if problems:
            continue
        script = render_script(draft, inputs.mode)
        data = script.encode("utf-8")
        record = {
            "schema": "r2.episode-adaptation.v1",
            "episode": episode,
            "mode": inputs.mode,
            "basis": inputs.basis(),
            "source_relpath": episode_source_relpath(episode),
            "text_relpath": adaptation_text_relpath(episode),
            "text_digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            "spoken_seconds": round(screen_seconds(draft, inputs), 1),
            "target_seconds": inputs.target_seconds,
            "draft": draft.model_dump(mode="json"),
            "attempts": attempts,
        }
        directory = project_path / ADAPTATIONS_DIR
        directory.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(project_path / adaptation_text_relpath(episode), data)
        atomic_write_json(project_path / adaptation_record_relpath(episode), record)
        return {"episode": episode, "spoken_seconds": record["spoken_seconds"], "attempts": attempt}
    raise AdaptationError(
        f"episode {episode} adaptation failed its checks after {MAX_ATTEMPTS} attempts: " + "; ".join(problems or [])
    )


__all__ = ["Generate", "adapt_episode"]
