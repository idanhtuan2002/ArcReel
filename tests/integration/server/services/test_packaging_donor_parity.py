"""Same-fixture M10-B donor parity: pinned Kalinga seo_lint and OpenMontage ExportBundle against the M10 seams.

Donor sources come only from the digest-checked fixture and run inside this test; no product path imports them.
Rows, exclusions and winning rules are frozen in `R2_M10_B6_DONOR_BASELINE.json`.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import statistics
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, get_args

import pytest

from r2.contracts import quality as q
from r2.quality.packaging_check import check_package
from server.services.package_export import member_path, metadata_document
from server.services.package_export_worker import BundleMember, build_archive
from tests.unit.r2.quality.test_packaging_check import all_rules_constraints, clean_body, facts, sealed

ROOT = Path(__file__).resolve().parents[4]
BASELINE = json.loads((ROOT / "docs" / "r2" / "evidence" / "R2_M10_B6_DONOR_BASELINE.json").read_text("utf-8"))
TOPIC = "river"
OVERHEAD_MS = 1500


class _ToolResult:
    def __init__(self, success: bool, data: dict[str, Any] | None = None, error: str | None = None, **_: Any) -> None:
        self.success, self.data, self.error = success, data or {}, error


class _Channel:
    seo: ClassVar[dict[str, list[str]]] = {"title_must_include": ["{topic}"], "description_must_include": ["{topic}"]}


class _Config:
    @staticmethod
    def channel() -> _Channel:
        return _Channel()


@pytest.fixture(scope="module")
def donors() -> Iterator[dict[str, Any]]:
    # OpenMontage validates its publish_log against its own schema package, which is outside the measured rows.
    import sys
    import types

    schemas = types.ModuleType("schemas")
    artifacts = types.ModuleType("schemas.artifacts")
    artifacts.validate_artifact = lambda _kind, _value: None
    previous = {name: sys.modules.get(name) for name in ("schemas", "schemas.artifacts")}
    sys.modules["schemas"], sys.modules["schemas.artifacts"] = schemas, artifacts
    try:
        yield _load_donors()
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _load_donors() -> dict[str, Any]:
    fixture = ROOT / BASELINE["donor_fixture"]["path"]
    raw = fixture.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == BASELINE["donor_fixture"]["sha256"]
    pinned = json.loads(raw)
    namespaces: dict[str, Any] = {}
    for key, donor in pinned["donors"].items():
        assert donor["commit_sha"] == BASELINE["donors"][key]["commit_sha"]
        assert donor["files"] == BASELINE["donors"][key]["blob_sha256"]
        namespace: dict[str, Any] = {
            "json": json,
            "re": re,
            "Path": Path,
            "shutil": shutil,
            "datetime": datetime,
            "timezone": timezone,
            "Any": Any,
            "config": _Config,
            "ToolResult": _ToolResult,
        }
        for function in donor["functions"]:
            source = function["source"]
            assert hashlib.sha256(source.encode("utf-8")).hexdigest() == function["sha256"]
            exec(compile(_dedent(source), function["path"], "exec"), namespace)
        namespaces[key] = namespace
    return namespaces


def _dedent(source: str) -> str:
    lines = source.splitlines(keepends=True)
    indent = min(len(line) - len(line.lstrip()) for line in lines if line.strip())
    return "".join(line[indent:] if line.strip() else line for line in lines)


class _Bundle:
    """The donor methods bound to an instance, standing in for the BaseTool subclass they came from."""

    def __init__(self, namespace: dict[str, Any]) -> None:
        self._format_chapter_time = namespace["_format_chapter_time"].__func__
        self._namespace = namespace

    def _chapter_lines(self, chapters):
        return self._namespace["_chapter_lines"](self, chapters)

    def execute(self, inputs):
        return self._namespace["execute"](self, inputs)


# ---------------------------------------------------------------- Kalinga seo_lint


def _kalinga_constraints() -> dict[str, Any]:
    """The M10 snapshot carrying the donor channel's SEO policy."""
    data = all_rules_constraints()
    return data | {
        "title_max_chars": 80,
        "title_required_terms": [TOPIC],
        "description_required_terms": [TOPIC],
        "plain_text_only": True,
        "description_min_chars": 120,
        "min_hashtags": 3,
        "max_hashtags": 5,
        "min_tags": 12,
        "max_tags": 30,
        "required_locales": [],
    }


def _clean_metadata() -> dict[str, Any]:
    body = clean_body()
    body.update(
        title="A history of the river valley",
        description="How the river shaped the valley over ten thousand years, from glaciers to farms, towns and the "
        "delta we see today, told in five chapters.",
        tags=[f"river history {n}" for n in range(12)],
        hashtags=["#river", "#history", "#valley"],
        localization_variants=[],
        variant_groups=[],
    )
    return body


DEFECTS = {
    "kalinga_title_length": ({"title": "river " * 20}, "TITLE_TOO_LONG"),
    "kalinga_title_terms": ({"title": "A history of the valley"}, "TITLE_TERM_MISSING"),
    "kalinga_description_terms": (
        {
            "description": "How the valley was shaped over ten thousand years, from glaciers to farms and towns, told "
            "in five chapters with maps and archive footage."
        },
        "DESCRIPTION_TERM_MISSING",
    ),
    "kalinga_plain_text": ({"title": "A **river** history"}, "MARKDOWN_NOT_ALLOWED"),
    "kalinga_description_min": ({"description": "The river, briefly."}, "DESCRIPTION_TOO_SHORT"),
    "kalinga_hashtag_count": ({"hashtags": ["#river"]}, "HASHTAG_COUNT_OUT_OF_BOUNDS"),
    "kalinga_tag_min": ({"tags": ["river", "history"]}, "TAG_COUNT_OUT_OF_BOUNDS"),
}


def _donor_issues(donors, tmp_path: Path, metadata: dict[str, Any] | None) -> list[str]:
    folder = tmp_path / "kalinga"
    folder.mkdir(exist_ok=True)
    seo = folder / "seo.json"
    seo.unlink(missing_ok=True)
    if metadata is not None:
        keys = ("title", "description", "tags", "hashtags")
        seo.write_text(json.dumps({key: metadata[key] for key in keys}), encoding="utf-8")
    return donors["kalinga"]["seo_lint"](folder, TOPIC)


def _m10_codes(metadata: dict[str, Any]) -> set[str]:
    constraints = _kalinga_constraints()
    candidate = sealed(metadata, constraints)
    result = check_package(candidate, q.PlatformConstraintSnapshot.model_validate(constraints), facts(candidate))
    return {f.code for f in result.failures}


def test_a_clean_package_passes_both_the_donor_and_m10(donors, tmp_path: Path) -> None:
    metadata = _clean_metadata()
    assert _donor_issues(donors, tmp_path, metadata) == []
    assert _m10_codes(metadata) == set()


@pytest.mark.parametrize("behavior", sorted(DEFECTS))
def test_every_donor_seo_finding_is_detected_by_its_m10_rule(donors, tmp_path: Path, behavior: str) -> None:
    change, code = DEFECTS[behavior]
    metadata = _clean_metadata() | change
    assert _donor_issues(donors, tmp_path, metadata), behavior
    assert code in _m10_codes(metadata)
    first, second = _m10_codes(metadata), _m10_codes(metadata)
    assert first == second


def test_missing_metadata_is_a_donor_issue_and_cannot_even_be_constructed_in_m10(donors, tmp_path: Path) -> None:
    from pydantic import ValidationError

    from r2.contracts.advanced_creative import PackagingCandidate

    assert _donor_issues(donors, tmp_path, None) == ["seo.json missing"]
    body = _clean_metadata()
    body.pop("title")
    with pytest.raises(ValidationError):
        PackagingCandidate.model_validate(body)


def test_the_m10_check_stays_within_the_frozen_performance_rule(donors, tmp_path: Path) -> None:
    metadata = _clean_metadata() | DEFECTS["kalinga_title_terms"][0]
    donor_ms, m10_ms = [], []
    for _ in range(9):
        started = time.perf_counter()
        _donor_issues(donors, tmp_path, metadata)
        donor_ms.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        _m10_codes(metadata)
        m10_ms.append((time.perf_counter() - started) * 1000)
    assert statistics.median(m10_ms) <= statistics.median(donor_ms) + OVERHEAD_MS


# ---------------------------------------------------------------- OpenMontage ExportBundle


def _inputs(tmp_path: Path, **changes: Any) -> dict[str, Any]:
    video = tmp_path / "render" / "final.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"v" * 64)
    thumbnail = tmp_path / "render" / "thumb.png"
    thumbnail.write_bytes(b"\x89PNG\r\n\x1a\n" + b"t" * 32)
    inputs = {
        "video_path": str(video),
        "title": "A history of the river valley",
        "description": "How the river shaped the valley.",
        "tags": ["river"],
        "hashtags": ["#river"],
        "chapters": [{"start_seconds": 0, "title": "Source"}],
        "thumbnail_path": str(thumbnail),
        "export_dir": str(tmp_path / "donor-export"),
        "project_name": "demo",
    }
    return inputs | changes


def test_a_missing_video_is_refused_by_both(donors, tmp_path: Path) -> None:
    result = _Bundle(donors["openmontage"]).execute(_inputs(tmp_path, video_path=str(tmp_path / "absent.mp4")))
    assert result.success is False
    body = clean_body() | {"assets": []}
    codes = {f.code for f in check_package(*_checked(body)).failures}
    assert "REQUIRED_ASSET_MISSING" in codes


def test_a_declared_optional_asset_that_is_missing_is_refused_by_both(donors, tmp_path: Path) -> None:
    result = _Bundle(donors["openmontage"]).execute(_inputs(tmp_path, thumbnail_path=str(tmp_path / "absent.png")))
    assert result.success is False
    body = clean_body()
    body["assets"].append(
        body["assets"][0]
        | {"role": "thumbnail", "variant_id": None, "media_type": "image/png", "constraint_rule_id": "asset-thumbnail"}
    )
    candidate, snapshot, verified = _checked(body)
    without_thumbnail = type(verified)(
        **(verified.__dict__ | {"assets": {("video", None): verified.assets[("video", None)]}})
    )
    codes = {f.code for f in check_package(candidate, snapshot, without_thumbnail).failures}
    assert "ASSET_NOT_VERIFIED" in codes


def _checked(body: dict[str, Any]):
    constraints = all_rules_constraints()
    candidate = sealed(body, constraints)
    return candidate, q.PlatformConstraintSnapshot.model_validate(constraints), facts(candidate)


def test_the_bundle_layout_matches_the_donor_for_video_metadata_and_thumbnail(donors, tmp_path: Path) -> None:
    result = _Bundle(donors["openmontage"]).execute(_inputs(tmp_path))
    assert result.success is True
    export_root = Path(_inputs(tmp_path)["export_dir"])
    donor_paths = {Path(path).relative_to(export_root).as_posix() for path in result.data["files_written"]}
    m10_paths = {
        member_path("video", None, "video/mp4"),
        member_path("thumbnail", None, "image/png"),
        "metadata/metadata.json",
    }
    assert m10_paths <= donor_paths


def test_the_metadata_document_covers_every_donor_metadata_field(donors, tmp_path: Path) -> None:
    from r2.contracts.advanced_creative import PackagingCandidate

    result = _Bundle(donors["openmontage"]).execute(_inputs(tmp_path))
    donor_metadata = json.loads(
        (Path(_inputs(tmp_path)["export_dir"]) / "metadata" / "metadata.json").read_text("utf-8")
    )
    ours = metadata_document(PackagingCandidate.model_validate(_checked(clean_body())[0].model_dump(mode="python")), {})
    assert result.success is True
    assert set(donor_metadata) <= set(ours)


def test_the_donor_bundle_is_not_byte_stable_and_the_m10_archive_is(donors, tmp_path: Path) -> None:
    bundle = _Bundle(donors["openmontage"])
    first = bundle.execute(_inputs(tmp_path / "a")).data["publish_log"]["entries"][0]["timestamp"]
    time.sleep(0.01)
    second = bundle.execute(_inputs(tmp_path / "b")).data["publish_log"]["entries"][0]["timestamp"]
    assert first != second
    payload = b"\x00\x00\x00\x18ftypisom" + b"v" * 64
    source = tmp_path / "video.bin"
    source.write_bytes(payload)
    member = BundleMember("video/output.mp4", source, "sha256:" + hashlib.sha256(payload).hexdigest(), len(payload))
    digests = {build_archive(tmp_path / f"{n}.zip", [member], b"{}") for n in range(2)}
    assert len(digests) == 1


def test_both_export_locally_without_uploading(donors, tmp_path: Path) -> None:
    result = _Bundle(donors["openmontage"]).execute(_inputs(tmp_path))
    assert result.data["publish_log"]["entries"][0]["status"] == "exported"
    from r2.contracts import packaging as p

    assert get_args(p.ExportBundleReceipt.model_fields["status"].annotation) == ("EXPORTED",)


async def test_the_confined_export_stays_within_the_frozen_performance_rule(donors, tmp_path: Path) -> None:
    import os

    from r2.contracts import packaging as p
    from r2.contracts.advanced_creative import PackagingCandidate
    from server.services.package_export import (
        PackageEvidence,
        PackageExportService,
        WorkDirectory,
        builder_identity_digest,
        open_export_store,
        plan_export,
        snapshot_assets,
    )
    from tests.unit.r2.contracts.test_packaging import candidate_data, selection_data

    root = tmp_path / "project"
    (root / "masters").mkdir(parents=True)
    payload = b"\x00\x00\x00\x18ftypisom" + b"v" * 4096
    (root / "masters" / "final.mp4").write_bytes(payload)
    asset = candidate_data()["assets"][0] | {
        "content_digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "byte_size": len(payload),
    }
    candidate = PackagingCandidate.model_validate(candidate_data() | {"assets": [asset]})
    selection = p.PackageSelection.model_validate(selection_data())
    service = PackageExportService(sessions=None, grant_reader=None, project_root=root, interactive_token=None)
    m10_ms, donor_ms = [], []
    for attempt in range(3):
        plan = plan_export(selection, PackageEvidence(candidate, None, None, None), builder_identity_digest())
        store = open_export_store(root)
        work = WorkDirectory(store, root)
        try:
            members = snapshot_assets(root, work, plan)
            started = time.perf_counter()
            digest = await service._build_and_publish(f"perf-{attempt}", plan, members, store, work)
            assert (root / "exports" / f"{digest.removeprefix('sha256:')}.zip").is_file()
            m10_ms.append((time.perf_counter() - started) * 1000)
        finally:
            work.close()
            os.close(store)
        started = time.perf_counter()
        _Bundle(donors["openmontage"]).execute(_inputs(tmp_path / f"donor-{attempt}"))
        donor_ms.append((time.perf_counter() - started) * 1000)
    assert statistics.median(m10_ms) <= statistics.median(donor_ms) + OVERHEAD_MS, (m10_ms, donor_ms)
