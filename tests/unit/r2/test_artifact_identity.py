"""Pure artifact identity uses the legacy wire kernel without a host initializer."""

from __future__ import annotations

import pytest

from r2.artifact_identity import (
    ArtifactKeyParts,
    decode_artifact_key_parts,
    decode_episode_video_key,
    encode_artifact_key_parts,
    episode_video_key,
    validate_m3_target_ref,
)

WIRE_VECTORS = [
    {"kind": "episode_video", "components": [3, "A"], "encoded": "artifact-key-v1:WyJlcGlzb2RlX3ZpZGVvIiwzLCJBIl0"},
    {
        "kind": "episode_video",
        "components": [12, "unit:/3"],
        "encoded": "artifact-key-v1:WyJlcGlzb2RlX3ZpZGVvIiwxMiwidW5pdDovMyJd",
    },
    {
        "kind": "unknown-future-kind",
        "components": ["中文", 1],
        "encoded": "artifact-key-v1:WyJ1bmtub3duLWZ1dHVyZS1raW5kIiwi5Lit5paHIiwxXQ",
    },
]


@pytest.mark.parametrize("row", WIRE_VECTORS)
def test_wire_bytes_match_pre_extraction_vectors(row) -> None:
    assert encode_artifact_key_parts(row["kind"], row["components"]) == row["encoded"]
    assert decode_artifact_key_parts(row["encoded"]) == ArtifactKeyParts(row["kind"], tuple(row["components"]))


def test_legacy_codec_names_are_the_same_implementation() -> None:
    from lib import artifact_manifest as legacy

    assert legacy.encode_artifact_key_parts is encode_artifact_key_parts
    assert legacy.decode_artifact_key_parts is decode_artifact_key_parts
    assert legacy.ArtifactKeyParts is ArtifactKeyParts


@pytest.mark.parametrize("target", ["A", "unit:/3", "中文", "Hiếu", " spaced "])
def test_video_wire_matches_existing_factory_without_narrowing_generic_ids(target: str) -> None:
    from lib.artifact_manifest import ArtifactKey

    key = episode_video_key(3, target)
    assert key == ArtifactKey.episode_video(3, target).encode()
    assert decode_episode_video_key(key) == (3, target)


@pytest.mark.parametrize("value", ["", "..", ".", "../A", "A:B", "A/B", "A\\B", "A\x00B"])
def test_target_ref_preserves_existing_safe_filename_refusal(value: str) -> None:
    with pytest.raises(ValueError, match="target_ref must be one safe filename component"):
        validate_m3_target_ref(value)


def test_legacy_target_validator_is_the_same_leaf() -> None:
    from r2.m3.host_integration import validate_m3_target_ref as legacy

    assert legacy is validate_m3_target_ref
    assert validate_m3_target_ref("A") == "A"


def test_new_decoder_requires_canonical_video_key_and_valid_episode() -> None:
    with pytest.raises(ValueError, match="not canonical"):
        decode_episode_video_key(episode_video_key(3, "A") + "=")
    with pytest.raises(ValueError, match="not an episode video"):
        decode_episode_video_key(encode_artifact_key_parts("episode-audio", [3, "A"]))
    with pytest.raises(ValueError, match="invalid components"):
        decode_episode_video_key(encode_artifact_key_parts("episode-video", [True, "A"]))
    with pytest.raises(ValueError, match="positive integer"):
        episode_video_key(0, "A")
