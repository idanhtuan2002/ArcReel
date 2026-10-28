"""Asset measurement reads only regular files beneath the project root, bounded and without following links."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from server.services.quality_packaging import _identity, _measure

pytestmark = pytest.mark.skipif(os.name != "posix", reason="no-follow directory-relative opens are POSIX")


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "assets").mkdir(parents=True)
    return root


def test_a_regular_file_is_hashed_with_its_inode_identity(tmp_path: Path) -> None:
    root = _root(tmp_path)
    target = root / "assets" / "thumb.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    measured = _measure(root, "assets/thumb.png", "image/png", 1 << 20)
    assert measured is not None
    assert measured.asset.content_digest == "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
    assert (measured.asset.byte_size, measured.asset.media_type) == (108, "image/png")
    assert measured.identity == _identity(str(target))


@pytest.mark.parametrize("link", ["final", "ancestor"])
def test_final_and_ancestor_symlinks_are_never_followed(tmp_path: Path, link: str) -> None:
    root = _root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    if link == "final":
        (root / "assets" / "secret.txt").symlink_to(outside / "secret.txt")
        source = "assets/secret.txt"
    else:
        (root / "linked").symlink_to(outside, target_is_directory=True)
        source = "linked/secret.txt"
    assert _measure(root, source, "text/plain", 1 << 20) is None


@pytest.mark.parametrize(
    "source", ["../outside.txt", "/etc/hostname", "assets/./x", "assets//x", "assets/x/", "./assets/x", ""]
)
def test_unsafe_or_non_canonical_paths_are_refused_even_when_the_target_exists(tmp_path: Path, source: str) -> None:
    root = _root(tmp_path)
    (root / "assets" / "x").write_text("present", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    assert _measure(root, "assets/x", "text/plain", 1 << 20) is not None
    assert _measure(root, source, "text/plain", 1 << 20) is None


def test_a_file_rewritten_while_it_is_read_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from server.services import quality_packaging

    root = _root(tmp_path)
    target = root / "assets" / "x"
    target.write_bytes(b"a" * 4096)
    real_fdopen = os.fdopen

    class Rewriting:
        def __init__(self, handle) -> None:
            self.handle = handle

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, *exc: object) -> None:
            self.handle.__exit__(*exc)

        def fileno(self) -> int:
            return self.handle.fileno()

        def read(self, size: int = -1) -> bytes:
            chunk = self.handle.read(size)
            with target.open("r+b") as writer:
                writer.write(b"b" * 16)
            return chunk

    monkeypatch.setattr(quality_packaging.os, "fdopen", lambda fd, mode, **kw: Rewriting(real_fdopen(fd, mode, **kw)))
    assert _measure(root, "assets/x", "text/plain", 1 << 20) is None


def test_reads_never_fetch_more_than_the_limit_plus_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from server.services import quality_packaging

    root = _root(tmp_path)
    (root / "assets" / "big.txt").write_bytes(b"a" * (3 << 20))
    requested: list[int] = []
    real_fdopen = os.fdopen

    class Spy:
        def __init__(self, handle) -> None:
            self.handle = handle

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, *exc: object) -> None:
            self.handle.__exit__(*exc)

        def fileno(self) -> int:
            return self.handle.fileno()

        def read(self, size: int = -1) -> bytes:
            requested.append(size)
            return self.handle.read(size)

    monkeypatch.setattr(quality_packaging.os, "fdopen", lambda fd, mode, **kw: Spy(real_fdopen(fd, mode, **kw)))
    measured = _measure(root, "assets/big.txt", "text/plain", 1000)
    assert measured is not None
    assert measured.asset.byte_size == 1001
    assert sum(requested) <= 1001


def test_a_fifo_is_refused_without_blocking(tmp_path: Path) -> None:
    root = _root(tmp_path)
    os.mkfifo(root / "assets" / "pipe")
    assert _measure(root, "assets/pipe", "text/plain", 1 << 20) is None


def test_more_bytes_than_the_limit_never_match_a_declaration(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "assets" / "big.txt").write_bytes(b"a" * 4096)
    measured = _measure(root, "assets/big.txt", "text/plain", 1024)
    assert measured is not None
    assert measured.asset.byte_size == 1025
    assert measured.asset.content_digest == "sha256:" + "0" * 64


def test_utf8_is_validated_across_chunk_and_prefix_boundaries(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "assets" / "ok.srt").write_bytes(b"a" * 63 + "漢".encode())
    (root / "assets" / "bad.srt").write_bytes(b"a" * 64 + b"\xff\xfe")
    (root / "assets" / "cut.srt").write_bytes(b"a" * 10 + "漢".encode()[:2])
    measured = {
        name: _measure(root, f"assets/{name}", "application/x-subrip", 1 << 20)
        for name in ("ok.srt", "bad.srt", "cut.srt")
    }
    assert {name: m.asset.media_type for name, m in measured.items() if m is not None} == {
        "ok.srt": "application/x-subrip",
        "bad.srt": "application/octet-stream",
        "cut.srt": "application/octet-stream",
    }


def test_an_ancestor_swapped_for_a_link_between_checks_is_never_traversed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from server.services import quality_packaging

    root = _root(tmp_path)
    (root / "assets" / "x").write_text("inside", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x").write_text("outside", encoding="utf-8")
    real_open = os.open

    def swapping(path, flags, mode=0o777, *, dir_fd=None):
        if path == "assets" and dir_fd is not None:
            shutil.rmtree(root / "assets")
            (root / "assets").symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(quality_packaging.os, "open", swapping)
    assert _measure(root, "assets/x", "text/plain", 1 << 20) is None


def test_a_measurement_past_its_deadline_stops_itself(tmp_path: Path) -> None:
    import time

    from server.services.quality_packaging import MeasurementExpiredError

    root = _root(tmp_path)
    (root / "assets" / "x").write_bytes(b"a" * 4096)
    with pytest.raises(MeasurementExpiredError):
        _measure(root, "assets/x", "text/plain", 1 << 20, time.monotonic() - 1)


def test_the_asset_worker_stops_before_the_next_asset_once_expired(tmp_path: Path) -> None:
    import time

    from r2.contracts import quality as q
    from server.services.quality_packaging import MeasurementExpiredError, PackagingCheckService
    from tests.unit.r2.quality.test_packaging_check import all_rules_constraints, clean_body, sealed

    calls: list[str] = []

    def measure(_root, source_ref, *_args):
        calls.append(source_ref)
        time.sleep(0.05)

    constraints = all_rules_constraints()
    body = clean_body()
    body["assets"].append(body["assets"][0] | {"role": "thumbnail", "source_ref": "t.png", "media_type": "image/png"})
    candidate = sealed(body, constraints)
    service = PackagingCheckService(sessions=None, project_root=tmp_path, clock=time.time, measure=measure)
    with pytest.raises(MeasurementExpiredError):
        service._assets(
            candidate, q.PlatformConstraintSnapshot.model_validate(constraints), ("m", "d"), time.monotonic() + 0.01
        )
    assert calls == ["masters/final.mp4"]
