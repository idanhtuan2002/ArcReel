"""A rework that would review a byte-identical final is recognised before the stage reruns."""

from __future__ import annotations

from server.production_run.quality_adapter import _unchanged_since_last_generation


def _final(root, generation: int, data: bytes):
    path = root / "production" / "automation" / "run" / f"g{generation}" / "episode_1" / "episode_1.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    return path


def test_an_identical_final_in_the_previous_generation_is_unchanged(tmp_path):
    _final(tmp_path, 1, b"same")

    assert _unchanged_since_last_generation(_final(tmp_path, 2, b"same"))


def test_a_different_final_or_the_first_generation_is_not_unchanged(tmp_path):
    first = _final(tmp_path, 1, b"before")

    assert not _unchanged_since_last_generation(first)
    assert not _unchanged_since_last_generation(_final(tmp_path, 2, b"after"))
