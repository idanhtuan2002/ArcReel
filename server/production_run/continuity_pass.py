"""What MEDIA asks the continuity judge about one storyboard, and the episode's ``continuity.json`` (ADR-0134).

A segment's shot is read from its script item and the project's assets: the characters, scenes and props it names,
each with its asset sheet as a labelled reference, and the previous storyboard of the same scene (the one the
storyboard task itself took as its previous frame). The evidence file lists per segment the first verdict on the
version it judged, and, for a segment regenerated with the verdict's ``prompt_fix``, the second verdict and the
version kept.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.asset_derivatives import derivative_table
from lib.asset_types import ASSET_SPECS, resolve_asset_key
from lib.reference_catalog import split_derivative_reference
from lib.storyboard_sequence import get_storyboard_items, resolve_previous_storyboard_path
from server.production_run.continuity_judge import Shot, Verdict

SCHEMA = "r2.production-continuity.v1"
#: Reference sheets one question carries at most, characters first (the judge's request stays a few images).
MAX_REFERENCES = 5


def _names(value: object) -> list[str]:
    return [str(name) for name in value if isinstance(name, str) and name.strip()] if isinstance(value, list) else []


def _sheet(project: dict[str, Any], project_path: Path, asset_type: str, name: str) -> tuple[str, bytes] | None:
    """The sheet a shot's reference name points at: an asset's own, or for ``owner/derivative`` the derivative's
    sheet with the owner's description plus the derivative's change."""
    spec = ASSET_SPECS[asset_type]
    bucket = project.get(spec.bucket_key)
    owner_name, derivative_name = split_derivative_reference(name) if spec.supports_derivatives else (name, "")
    key = resolve_asset_key(bucket, owner_name) if isinstance(bucket, dict) else None
    entry = bucket.get(key) if isinstance(bucket, dict) and key is not None else None
    description = str(entry.get("description") or "").strip() if isinstance(entry, dict) else ""
    if derivative_name:
        table = derivative_table(entry)
        derivative_key = resolve_asset_key(table, derivative_name)
        entry = table.get(derivative_key) if derivative_key is not None else None
        change = str(entry.get("description") or "").strip() if isinstance(entry, dict) else ""
        description = f"{description} {change}".strip()
    relative = entry.get(spec.sheet_field) if isinstance(entry, dict) else None
    if not isinstance(relative, str) or not relative:
        return None
    path = (project_path / relative).resolve()
    if not path.is_relative_to(project_path.resolve()) or not path.is_file():
        return None
    description = description[:300]
    label = f"{asset_type}: {name}" + (f" - {description}" if description else "")
    return label, path.read_bytes()


def _framing(prompt: object) -> str:
    composition = prompt.get("composition") if isinstance(prompt, dict) else None
    shot_type = composition.get("shot_type") if isinstance(composition, dict) else None
    return shot_type if isinstance(shot_type, str) else ""


def _description(item: dict[str, Any]) -> str:
    prompt = item.get("image_prompt")
    scene = prompt.get("scene") if isinstance(prompt, dict) else prompt
    parts = [str(item.get("novel_text") or "").strip(), str(scene or "").strip()]
    return "\n".join(part for part in parts if part)


def shot_for(project: dict[str, Any], project_path: Path, script: dict[str, Any], unit: str) -> Shot | None:
    """The shot of ``unit`` in ``script``; ``None`` when the script has no such storyboard item."""
    items, id_field, char_field, scene_field, prop_field = get_storyboard_items(script)
    index = next(
        (i for i, item in enumerate(items) if isinstance(item, dict) and str(item.get(id_field)) == unit), None
    )
    if index is None:
        return None
    item = items[index]
    characters = _names(item.get(char_field)) if char_field else []
    scenes, props = _names(item.get(scene_field)), _names(item.get(prop_field))
    references = [
        sheet
        for asset_type, names in (("character", characters), ("scene", scenes), ("prop", props))
        for name in names
        if (sheet := _sheet(project, project_path, asset_type, name)) is not None
    ][:MAX_REFERENCES]
    previous_path = resolve_previous_storyboard_path(project_path, items, id_field, unit)
    previous_item = items[index - 1] if previous_path is not None and index > 0 else None
    return Shot(
        label=unit,
        description=_description(item),
        characters=tuple(characters),
        location=", ".join(scenes),
        props=tuple(props),
        framing=_framing(item.get("image_prompt")),
        references=tuple(references),
        previous_description=_description(previous_item) if isinstance(previous_item, dict) else "",
        previous_frame=previous_path.read_bytes() if previous_path is not None else None,
    )


def read_evidence(path: Path) -> dict[str, Any]:
    try:
        recorded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return recorded if isinstance(recorded, dict) else {}


def record(path: Path, *, identity: str, prompt_digest: str, unit: str, fields: dict[str, Any]) -> None:
    """Merge ``fields`` into ``unit``'s entry of the evidence file at ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    recorded = read_evidence(path)
    raw = recorded.get("segments")
    segments: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    entry = segments.get(unit)
    segments[unit] = {**(entry if isinstance(entry, dict) else {}), **fields}
    recorded.update(
        {"schema": SCHEMA, "judge_identity": identity, "judge_prompt_digest": prompt_digest, "segments": segments}
    )
    path.write_text(json.dumps(recorded, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def judged(version: int | None, verdict: Verdict | None) -> dict[str, Any]:
    return {"version": version, "verdict": verdict.as_json() if verdict is not None else None}


__all__ = ["MAX_REFERENCES", "SCHEMA", "judged", "read_evidence", "record", "shot_for"]
