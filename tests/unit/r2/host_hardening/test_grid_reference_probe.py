"""H6 grid reference probe preserves declared field states without source writes."""

from __future__ import annotations

import json

import pytest

from lib.grid.models import GridGeneration
from r2.host_hardening.grid_reference_probe import GridProbeError, GridReference, inspect_grid_references


def _grid_record() -> dict:
    grid = GridGeneration.create(
        episode=1,
        script_file="scripts/episode_1.json",
        scene_ids=["scene-1"],
        rows=1,
        cols=1,
        grid_size="1x1",
        provider="fixture",
        model="fixture",
        video_aspect_ratio="9:16",
    )
    return grid.to_dict()


def _inspect(record: dict, *, max_bytes: int = 4096):
    payload = json.dumps(record).encode()
    return inspect_grid_references(payload, expected_grid_id=record["id"], max_bytes=max_bytes)


def test_grid_probe_extracts_current_writer_fields_without_assigning_liveness() -> None:
    record = _grid_record()
    record["status"] = "completed"
    record["grid_image_path"] = f"grids/{record['id']}.png"
    record["frame_chain"][0]["image_path"] = "storyboards/scene-1.png"
    record["reference_images"] = [{"path": "characters/hero.png", "name": "hero", "ref_type": "character"}]
    record["split_at"] = "2026-09-26T00:00:00+00:00"

    result = _inspect(record)

    assert result.grid_id == record["id"]
    assert result.status == "completed"
    assert result.split_at == "2026-09-26T00:00:00+00:00"
    assert result.split_at_present
    assert result.frame_chain_present
    assert result.reference_images_state == "LIST"
    assert result.references == (
        GridReference("script_file", "scripts/episode_1.json", True),
        GridReference("grid_image_path", record["grid_image_path"], True),
        GridReference("frame_chain[0].image_path", "storyboards/scene-1.png", True),
        GridReference("reference_images[0].path", "characters/hero.png", True),
    )


def test_grid_probe_preserves_absent_null_and_legacy_splitting_states() -> None:
    record = _grid_record()
    record["status"] = "splitting"
    del record["grid_image_path"]
    del record["split_at"]
    del record["frame_chain"][0]["image_path"]
    del record["reference_images"]

    result = _inspect(record)

    assert result.status == "splitting"
    assert not result.split_at_present
    assert result.split_at is None
    assert result.reference_images_state == "ABSENT"
    assert result.references == (
        GridReference("script_file", "scripts/episode_1.json", True),
        GridReference("grid_image_path", None, False),
        GridReference("frame_chain[0].image_path", None, False),
    )

    record["grid_image_path"] = None
    record["reference_images"] = None
    result = _inspect(record)
    assert result.reference_images_state == "NULL"
    assert result.references[1] == GridReference("grid_image_path", None, True)


@pytest.mark.parametrize("payload", [b"{", b"\xff", b'{"id":"a","id":"b"}'])
def test_grid_probe_rejects_malformed_json_with_sanitized_error(payload: bytes) -> None:
    with pytest.raises(GridProbeError) as error:
        inspect_grid_references(payload, expected_grid_id="grid_000000000001", max_bytes=4096)

    assert error.value.code == "INVALID_RECORD"
    assert str(error.value) == "INVALID_RECORD"


@pytest.mark.parametrize("location", ["root", "frame", "reference"])
def test_grid_probe_rejects_unknown_keys_in_declared_schema(location: str) -> None:
    record = _grid_record()
    if location == "root":
        record["future_path"] = "secret.txt"
    elif location == "frame":
        record["frame_chain"][0]["future_path"] = "secret.txt"
    else:
        record["reference_images"] = [{"path": "a.png", "name": "a", "ref_type": "scene", "future_path": "x"}]

    with pytest.raises(GridProbeError) as error:
        _inspect(record)

    assert error.value.code == "SCHEMA_UNSUPPORTED"
    assert "secret" not in str(error.value)


def test_grid_probe_rejects_wrong_identity_and_invalid_nested_path_type() -> None:
    record = _grid_record()
    payload = json.dumps(record).encode()

    with pytest.raises(GridProbeError) as identity_error:
        inspect_grid_references(payload, expected_grid_id="grid_000000000001", max_bytes=4096)
    assert identity_error.value.code == "IDENTITY_MISMATCH"

    record["frame_chain"][0]["image_path"] = 12
    with pytest.raises(GridProbeError) as type_error:
        _inspect(record)
    assert type_error.value.code == "INVALID_RECORD"


def test_grid_probe_enforces_input_limit_before_json_decode() -> None:
    record = _grid_record()
    with pytest.raises(GridProbeError) as error:
        _inspect(record, max_bytes=5)

    assert error.value.code == "LIMIT_EXCEEDED"
