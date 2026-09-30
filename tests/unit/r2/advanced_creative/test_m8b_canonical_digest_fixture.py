"""The canonical-digest fixture the M8-B TypeScript port is tested against matches digests.py."""

from __future__ import annotations

import json
from pathlib import Path

from r2.advanced_creative.digests import canonical_json_bytes, digest_canonical, digest_payload
from r2.contracts.advanced_creative import CanvasCandidate, LineageBinding

FIXTURE = (
    Path(__file__).resolve().parents[4]
    / "frontend/src/features/creative-canvas/__fixtures__/canonical-digest.json"
)


def _fixture() -> dict[str, list[dict[str, str]]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_every_value_case_is_what_the_server_encodes() -> None:
    for case in _fixture()["values"]:
        value = json.loads(case["input"])
        assert canonical_json_bytes(value).decode("utf-8") == case["canonical"], case["name"]
        assert digest_canonical(value) == case["digest"], case["name"]


def test_every_payload_case_is_the_digest_the_server_recomputes() -> None:
    for case in _fixture()["payloads"]:
        payload = CanvasCandidate.model_validate(json.loads(case["payload"]))
        lineage = LineageBinding.model_validate(json.loads(case["lineage"]))
        assert digest_payload(payload, lineage) == case["digest"], case["name"]
