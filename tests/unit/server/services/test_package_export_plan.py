"""Export planning admits the operational envelope first and never lets two members share a path."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from r2.contracts import packaging as p
from r2.contracts.advanced_creative import PackagingCandidate
from r2.quality.errors import ExportIntegrityFailedError, OperationalEnvelopeExceededError
from server.services.package_export import MAX_EXPORT_MEMBERS, PackageEvidence, plan_export
from server.services.package_export_worker import MAX_MEMBER_BYTES
from tests.unit.r2.contracts.test_packaging import candidate_data, selection_data


def _plan(**changes: Any):
    candidate = PackagingCandidate.model_validate(candidate_data() | changes)
    selection = p.PackageSelection.model_validate(selection_data())
    evidence = PackageEvidence(candidate, None, None, None)
    return plan_export(selection, evidence, "sha256:" + "b" * 64)


def _localized(locale: str) -> dict[str, Any]:
    return {"locale": locale, "title": "t", "description": "d", "tags": [], "hashtags": [], "chapters": []}


def test_a_clean_plan_lists_the_video_and_the_primary_metadata() -> None:
    plan = _plan()
    paths = [entry.path for entry in plan.manifest.entries]
    assert {"video/output.mp4", "metadata/metadata.json", "metadata/en.json"} <= set(paths)
    assert plan.archive_bytes > sum(entry.byte_size for entry in plan.manifest.entries)


@pytest.mark.parametrize("size", [MAX_MEMBER_BYTES + 1, 2**31 - 1])
def test_an_oversized_member_is_an_envelope_refusal_not_integrity(size: int) -> None:
    asset = candidate_data()["assets"][0] | {"byte_size": size}
    with pytest.raises(OperationalEnvelopeExceededError):
        _plan(assets=[asset])


def test_two_large_members_over_the_archive_cap_are_an_envelope_refusal() -> None:
    first = candidate_data()["assets"][0] | {"byte_size": 1_200_000_000}
    second = first | {"role": "poster", "media_type": "image/png"}
    with pytest.raises(OperationalEnvelopeExceededError):
        _plan(assets=[first, second])


def test_more_members_than_the_worker_config_admits_is_an_envelope_refusal() -> None:
    locales = [_localized(f"l{index}") for index in range(MAX_EXPORT_MEMBERS)]
    with pytest.raises(OperationalEnvelopeExceededError):
        _plan(localization_variants=locales)


@pytest.mark.parametrize("locales", [["en", "EN"], ["metadata"], ["e n", "e-n"]])
def test_colliding_document_paths_are_refused(locales: list[str]) -> None:
    with pytest.raises(ExportIntegrityFailedError):
        _plan(localization_variants=[_localized(locale) for locale in locales])


def test_a_same_size_rewrite_with_a_restored_mtime_changes_the_generation(tmp_path: Path) -> None:
    from server.services.package_export import published_generation

    target = tmp_path / "a.zip"
    target.write_bytes(b"abcd")
    store = os.open(tmp_path, os.O_RDONLY)
    try:
        before = published_generation(store, "a.zip")
        stat = target.stat()
        target.write_bytes(b"abce")
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert published_generation(store, "a.zip") != before
    finally:
        os.close(store)


def test_a_worker_config_over_its_bound_is_refused_before_any_copy() -> None:
    from dataclasses import dataclass

    from server.services.package_export import admit_worker_config

    @dataclass
    class FakeWork:
        path: Path

    locales = [_localized(f"l{index}") for index in range(MAX_EXPORT_MEMBERS - 2)]
    plan = _plan(localization_variants=locales)
    admit_worker_config(FakeWork(Path("/p")), plan)
    with pytest.raises(OperationalEnvelopeExceededError):
        admit_worker_config(FakeWork(Path("/" + "x" * 1000)), plan)
