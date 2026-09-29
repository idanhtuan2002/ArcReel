"""The shared strict M8 evidence fold (plan Task A1.4)."""

from __future__ import annotations

import copy

from scripts.r2.verify_m8_evidence import verify_m8_evidence

HEAD = "c" * 40
SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "tested_head", "commands", "required_skips", "material_unknowns", "artifacts"],
    "properties": {
        "status": {"type": "string"},
        "tested_head": {"type": "string"},
        "commands": {"type": "array"},
        "required_skips": {"type": "array"},
        "material_unknowns": {"type": "array"},
        "artifacts": {"type": "array"},
    },
}
DOCUMENT: dict[str, object] = {
    "status": "M8_A_CANDIDATE",
    "tested_head": HEAD,
    "commands": [{"command": "pytest", "exit": 0}],
    "required_skips": [],
    "material_unknowns": [],
    "artifacts": [{"path": "a.json", "sha256": "a" * 64}],
}


def _with(**overrides: object) -> dict[str, object]:
    return copy.deepcopy(DOCUMENT) | overrides


def test_a_complete_document_passes() -> None:
    assert verify_m8_evidence(DOCUMENT, SCHEMA, HEAD) == []


def test_unknown_fields_are_rejected() -> None:
    assert verify_m8_evidence(_with(extra=True), SCHEMA, HEAD)


def test_missing_artifacts_are_rejected() -> None:
    assert verify_m8_evidence(_with(artifacts=[]), SCHEMA, HEAD)


def test_a_nonzero_exit_is_rejected() -> None:
    assert verify_m8_evidence(_with(commands=[{"command": "pytest", "exit": 1}]), SCHEMA, HEAD)


def test_skips_and_unknowns_are_rejected() -> None:
    assert verify_m8_evidence(_with(required_skips=["pg"]), SCHEMA, HEAD)
    assert verify_m8_evidence(_with(material_unknowns=["timing"]), SCHEMA, HEAD)


def test_a_different_tested_head_is_rejected() -> None:
    assert verify_m8_evidence(DOCUMENT, SCHEMA, "d" * 40)


def test_problems_are_sorted() -> None:
    problems = verify_m8_evidence(_with(required_skips=["pg"], artifacts=[]), SCHEMA, "d" * 40)

    assert problems == sorted(problems)
    assert len(problems) == 3
