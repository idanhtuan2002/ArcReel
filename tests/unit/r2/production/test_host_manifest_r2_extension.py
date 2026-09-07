import json

import pytest

from lib.artifact_manifest import (
    MANIFEST_FILENAME,
    ArtifactKey,
    ArtifactManifestEntry,
    ArtifactManifestError,
    ProjectArtifactManifestAdapter,
)


def key() -> ArtifactKey:
    return ArtifactKey.episode_video(1, "SH1")


def test_r2_envelope_round_trips_through_real_manifest(tmp_path):
    adapter = ProjectArtifactManifestAdapter(tmp_path)
    entry = ArtifactManifestEntry(
        artifact_path="current.mp4",
        basis_digest="sha256-v1:" + ("a" * 64),
        r2={"metadata_schema_version": "1", "probe": {"value": 7}},
    )

    assert adapter.put_entry(key(), entry) is True
    assert ProjectArtifactManifestAdapter(tmp_path).get_entry(key()) == entry


def test_legacy_entry_serialization_omits_r2_key(tmp_path):
    adapter = ProjectArtifactManifestAdapter(tmp_path)
    entry = ArtifactManifestEntry(
        artifact_path="current.mp4",
        basis_digest="sha256-v1:" + ("a" * 64),
    )

    assert adapter.put_entry(key(), entry) is True
    payload = json.loads((tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    encoded = payload["entries"][key().encode()]

    assert encoded == {
        "artifact_path": "current.mp4",
        "basis_digest": "sha256-v1:" + ("a" * 64),
    }


def test_r2_envelope_accepts_malformed_inner_shape_for_r2_fail_closed_validation(tmp_path):
    adapter = ProjectArtifactManifestAdapter(tmp_path)
    entry = ArtifactManifestEntry(
        artifact_path="current.mp4",
        basis_digest="sha256-v1:" + ("a" * 64),
        r2="malformed-r2-envelope",
    )

    assert adapter.put_entry(key(), entry) is True
    assert ProjectArtifactManifestAdapter(tmp_path).get_entry(key()).r2 == "malformed-r2-envelope"


def test_unknown_non_r2_manifest_entry_field_remains_rejected(tmp_path):
    adapter = ProjectArtifactManifestAdapter(tmp_path)
    assert adapter.put_entry(
        key(),
        ArtifactManifestEntry(
            artifact_path="current.mp4",
            basis_digest="sha256-v1:" + ("a" * 64),
        ),
    )

    path = tmp_path / MANIFEST_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["entries"][key().encode()]["unexpected"] = 1
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ArtifactManifestError):
        ProjectArtifactManifestAdapter(tmp_path).get_entry(key())
