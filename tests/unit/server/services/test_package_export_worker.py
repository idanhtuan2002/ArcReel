"""The export archive is byte-deterministic, fixed in every ZipInfo field and refuses drifted members."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from server.services.package_export_worker import MEMBER_MODE, ZIP_EPOCH, BundleMember, ExportBuildError, build_archive

MANIFEST = b'{"schema_id":"m10.export-manifest.v1"}'
# Frozen: a change is an archive-format change and needs a reviewed amendment.
GOLDEN = "sha256:99ff4053bdedabf824dc89031201703b2c6a875ab619e5bfc3a777d7a567dbc1"


def _member(root: Path, path: str, data: bytes) -> BundleMember:
    source = root / path.replace("/", "_")
    source.write_bytes(data)
    return BundleMember(path, source, "sha256:" + hashlib.sha256(data).hexdigest(), len(data))


def _members(root: Path) -> list[BundleMember]:
    root.mkdir(parents=True, exist_ok=True)
    return [
        _member(root, "video/output.mp4", b"\x00\x00\x00\x18ftypisom" + b"v" * 64),
        _member(root, "metadata/metadata.json", b'{"title":"A history of the river"}'),
        _member(root, "captions/en.srt", "1\n00:00:00,000 --> 00:00:01,000\nRiver 漢\n".encode()),
    ]


def test_two_clean_roots_build_byte_identical_archives(tmp_path: Path) -> None:
    first = build_archive(tmp_path / "a.zip", list(reversed(_members(tmp_path / "one"))), MANIFEST)
    second = build_archive(tmp_path / "b.zip", _members(tmp_path / "two"), MANIFEST)
    assert first == second
    assert (tmp_path / "a.zip").read_bytes() == (tmp_path / "b.zip").read_bytes()
    assert first == "sha256:" + hashlib.sha256((tmp_path / "a.zip").read_bytes()).hexdigest()


def test_the_archive_format_is_frozen(tmp_path: Path) -> None:
    assert build_archive(tmp_path / "a.zip", _members(tmp_path / "src"), MANIFEST) == GOLDEN


def test_every_member_has_the_fixed_fields_in_sorted_order(tmp_path: Path) -> None:
    build_archive(tmp_path / "a.zip", _members(tmp_path / "src"), MANIFEST)
    with zipfile.ZipFile(tmp_path / "a.zip") as archive:
        infos = archive.infolist()
        assert [i.filename for i in infos] == [
            "captions/en.srt",
            "manifest.json",
            "metadata/metadata.json",
            "video/output.mp4",
        ]
        for info in infos:
            assert (info.compress_type, info.date_time, info.create_system) == (zipfile.ZIP_STORED, ZIP_EPOCH, 3)
            assert (info.external_attr >> 16, info.flag_bits, info.extra, info.comment) == (MEMBER_MODE, 0, b"", b"")
        assert archive.comment == b""
        assert archive.read("manifest.json") == MANIFEST


@pytest.mark.parametrize("change", ["digest", "longer", "shorter"])
def test_a_member_whose_bytes_drift_from_the_manifest_is_refused(tmp_path: Path, change: str) -> None:
    members = _members(tmp_path / "src")
    member = members[0]
    if change == "digest":
        members[0] = BundleMember(member.path, member.source, "sha256:" + "0" * 64, member.byte_size)
    elif change == "longer":
        member.source.write_bytes(member.source.read_bytes() + b"x")
    else:
        members[0] = BundleMember(member.path, member.source, member.content_digest, member.byte_size + 1)
    with pytest.raises(ExportBuildError):
        build_archive(tmp_path / "a.zip", members, MANIFEST)


@pytest.mark.parametrize("path", ["../escape", "/abs", "dir/", "vidéo.mp4", "manifest.json"])
def test_unsafe_or_reserved_paths_are_refused(tmp_path: Path, path: str) -> None:
    members = _members(tmp_path / "src")
    members.append(_member(tmp_path / "src", path if path != "/abs" else "abs", b"x"))
    members[-1] = BundleMember(path, members[-1].source, members[-1].content_digest, members[-1].byte_size)
    with pytest.raises(ExportBuildError):
        build_archive(tmp_path / "a.zip", members, MANIFEST)


def test_an_existing_destination_is_never_overwritten(tmp_path: Path) -> None:
    (tmp_path / "a.zip").write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        build_archive(tmp_path / "a.zip", _members(tmp_path / "src"), MANIFEST)
    assert (tmp_path / "a.zip").read_bytes() == b"keep"


@pytest.mark.parametrize(
    "path", ["Video/output.mp4", "video//output.mp4", "video/./output.mp4", "video\\output.mp4", "a:b", "a\x00b", "a b"]
)
def test_the_worker_boundary_enforces_the_full_export_grammar(tmp_path: Path, path: str) -> None:
    members = _members(tmp_path / "src")
    members.append(BundleMember(path, members[0].source, members[0].content_digest, members[0].byte_size))
    with pytest.raises(ExportBuildError):
        build_archive(tmp_path / "a.zip", members, MANIFEST)


def test_case_colliding_members_are_refused(tmp_path: Path) -> None:
    from server.services.package_export_worker import validate_path

    validate_path("assets/a.txt")
    members = _members(tmp_path / "src")
    members.append(BundleMember("captions/en.srt.", members[2].source, members[2].content_digest, members[2].byte_size))
    members.append(BundleMember("captions/en.srt.", members[2].source, members[2].content_digest, members[2].byte_size))
    with pytest.raises(ExportBuildError):
        build_archive(tmp_path / "a.zip", members, MANIFEST)


def test_the_preflight_size_is_the_exact_archive_size(tmp_path: Path) -> None:
    from server.services.package_export_worker import archive_size

    members = _members(tmp_path / "src")
    build_archive(tmp_path / "a.zip", members, MANIFEST)
    assert archive_size([(m.path, m.byte_size) for m in members], len(MANIFEST)) == (tmp_path / "a.zip").stat().st_size


@pytest.mark.parametrize("sizes", [[("video/output.mp4", 2_100_000_000)], [("a", 1_500_000_000), ("b", 700_000_000)]])
def test_the_no_zip64_envelope_is_refused_before_any_copy(sizes: list[tuple[str, int]]) -> None:
    from server.services.package_export_worker import ExportEnvelopeError, archive_size

    with pytest.raises(ExportEnvelopeError):
        archive_size(sizes, 1024)
