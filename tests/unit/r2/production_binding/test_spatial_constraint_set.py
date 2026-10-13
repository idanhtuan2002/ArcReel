"""A typed spatial constraint set: frozen digest vector and fail-closed server derivation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from r2.contracts.spatial_constraint import SpatialConstraintSetV1
from r2.production_binding.spatial_set import (
    SpatialConstraintError,
    derive_spatial_constraint_set,
    spatial_constraint_set_digest,
    spatial_constraint_set_id,
)
from tests.unit.r2.production_binding import spatial_constraint_fixture as fixture

VECTOR = json.loads(
    (Path(__file__).resolve().parents[3] / "fixtures" / "r2" / "m8c_spatial_constraint_set_vector.json").read_text(
        encoding="utf-8"
    )
)


def _derive(selected: list[str], **overrides: Any) -> SpatialConstraintSetV1:
    values: dict[str, Any] = {
        "user_id": fixture.USER,
        "project_name": fixture.PROJECT,
        "binding_id": fixture.BINDING_ID,
        "revision": fixture.revision(),
        "selected_assertion_ids": selected,
        "pair_id": fixture.PAIR_ID,
        "pair_version": 1,
        "pair_decision_digest": fixture.PAIR_DECISION_DIGEST,
        "ordered_sources": fixture.sources(),
    }
    values.update(overrides)
    return derive_spatial_constraint_set(**values)


def _selected() -> list[str]:
    ids = fixture.visible_ids_by_subject()
    return [ids[subject] for subject in VECTOR["selected_subjects"]]


def test_derivation_reproduces_the_frozen_vector() -> None:
    derived = _derive(_selected())

    assert derived.model_dump(mode="json") == VECTOR["body"]
    assert spatial_constraint_set_digest(VECTOR["body"]) == VECTOR["digest"]
    assert spatial_constraint_set_id(VECTOR["digest"]) == VECTOR["set_id"]
    assert [c.relation_kind for c in derived.constraints] == [
        "PRESERVE_ON_WALL",
        "PRESERVE_ON_WALL",
        "SHARED_SIDE_ANCHOR",
    ]
    assert {w.evidence_class.value for w in derived.coverage_warnings} == {"INFERRED", "GAP"}


def test_any_body_change_changes_the_digest() -> None:
    changed = deepcopy(VECTOR["body"])
    changed["constraints"][0]["subject_ref"] = "green cabinet"

    assert spatial_constraint_set_digest(changed) != VECTOR["digest"]


def test_selection_order_is_part_of_the_set() -> None:
    reordered = list(reversed(_selected()))

    assert spatial_constraint_set_digest(_derive(reordered).model_dump(mode="json")) != VECTOR["digest"]


@pytest.mark.parametrize("selection", [[], ["spatial:unknown"]], ids=["empty", "unknown"])
def test_an_empty_or_unknown_selection_is_refused(selection: list[str]) -> None:
    with pytest.raises(SpatialConstraintError):
        _derive(selection)


def test_a_duplicate_selection_is_refused() -> None:
    first = _selected()[0]
    with pytest.raises(SpatialConstraintError, match="distinct"):
        _derive([first, first])


def test_inferred_and_gap_rows_cannot_be_selected() -> None:
    payload = fixture.revision().payload
    for assertion in payload.spatial.assertions:
        if assertion.evidence_class.value in {"INFERRED", "GAP"}:
            with pytest.raises(SpatialConstraintError, match="not VISIBLE"):
                _derive([assertion.assertion_id])


def test_a_tampered_revision_is_refused() -> None:
    revision = fixture.revision()
    tampered = revision.model_copy(update={"payload_digest": "sha256:" + "0" * 64})

    with pytest.raises(SpatialConstraintError, match="digest"):
        _derive(_selected(), revision=tampered)


def test_sources_that_do_not_match_the_spans_are_refused() -> None:
    master, reverse = fixture.sources()
    foreign = master.model_copy(update={"frame_content_digest": "sha256:" + "9" * 64})

    with pytest.raises(SpatialConstraintError, match="does not resolve"):
        _derive(_selected(), ordered_sources=(foreign, reverse))


def test_sources_must_be_master_then_reverse() -> None:
    master, reverse = fixture.sources()

    with pytest.raises(SpatialConstraintError):
        _derive(_selected(), ordered_sources=(reverse, master))


def test_a_shared_side_anchor_needs_both_views() -> None:
    body = deepcopy(VECTOR["body"])
    anchor = body["constraints"][2]
    anchor["source_spans"] = anchor["source_spans"][:1]

    with pytest.raises(ValidationError, match="both views"):
        SpatialConstraintSetV1.model_validate(body)


@pytest.mark.parametrize(("kind", "wall"), [("PRESERVE_ON_WALL", "left"), ("SHARED_SIDE_ANCHOR", "front")])
def test_a_relation_kind_applies_only_to_its_walls(kind: str, wall: str) -> None:
    body = deepcopy(VECTOR["body"])
    body["constraints"][0].update(relation_kind=kind, wall=wall)

    with pytest.raises(ValidationError):
        SpatialConstraintSetV1.model_validate(body)
