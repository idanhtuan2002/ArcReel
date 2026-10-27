"""Probe snapshots bind bounded regular bytes beneath an anchored project root."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import pytest

from r2.quality.errors import OperationalEnvelopeExceededError, RequiredEvidenceMissingError


def inputs():
    try:
        return importlib.import_module("server.services.quality_probe_inputs")
    except ModuleNotFoundError:
        pytest.fail("Anchored probe snapshots are unavailable")


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


@pytest.fixture
def media_paths(tmp_path: Path):
    project, scratch = (tmp_path / "project", tmp_path / "scratch")
    project.mkdir(mode=448)
    scratch.mkdir(mode=448)
    source = project / "master.mp4"
    source.write_bytes(b"measured-master")
    return (project, scratch, source)


def test_snapshot_is_readonly_hash_bound_and_removed_after_context(media_paths) -> None:
    project, scratch, source = media_paths
    expected = digest(source.read_bytes())
    with inputs().verified_probe_file(
        project_root=project, object_ref=str(source), expected_digest=expected, directory=scratch
    ) as snapshot:
        path = snapshot.path
        assert path.read_bytes() == b"measured-master"
        assert snapshot.digest == expected
        assert snapshot.size_bytes == len(b"measured-master")
        assert path.stat().st_mode & 511 == 256
        source.write_bytes(b"new-master")
        assert path.read_bytes() == b"measured-master"
    assert not path.exists()
    assert source.read_bytes() == b"new-master"
    assert list(scratch.iterdir()) == []


@pytest.mark.parametrize(
    "case", ["relative", "parent", "foreign", "leaf_symlink", "parent_symlink", "fifo", "directory"]
)
def test_unsafe_or_special_source_is_refused_without_leaving_a_snapshot(media_paths, case: str) -> None:
    import os

    project, scratch, source = media_paths
    outside = project.parent / "outside.mp4"
    outside.write_bytes(b"measured-master")
    if case == "relative":
        ref = "master.mp4"
    elif case == "parent":
        ref = str(project / ".." / "outside.mp4")
    elif case == "foreign":
        ref = str(outside)
    elif case == "leaf_symlink":
        linked = project / "linked.mp4"
        linked.symlink_to(source)
        ref = str(linked)
    elif case == "parent_symlink":
        parent = project / "linked"
        parent.symlink_to(project, target_is_directory=True)
        ref = str(parent / "master.mp4")
    elif case == "fifo":
        fifo = project / "pipe.mp4"
        os.mkfifo(fifo)
        ref = str(fifo)
    else:
        ref = str(project)
    with (
        pytest.raises(RequiredEvidenceMissingError),
        inputs().verified_probe_file(
            project_root=project, object_ref=ref, expected_digest=digest(b"measured-master"), directory=scratch
        ),
    ):
        pytest.fail("unsafe source was admitted")
    assert list(scratch.iterdir()) == []


def test_wrong_hash_and_oversized_input_leave_no_partial_copy(media_paths) -> None:
    project, scratch, source = media_paths
    with (
        pytest.raises(RequiredEvidenceMissingError),
        inputs().verified_probe_file(
            project_root=project, object_ref=str(source), expected_digest=digest(b"wrong"), directory=scratch
        ),
    ):
        pytest.fail("changed bytes admitted")
    with (
        pytest.raises(OperationalEnvelopeExceededError),
        inputs().verified_probe_file(
            project_root=project,
            object_ref=str(source),
            expected_digest=digest(source.read_bytes()),
            directory=scratch,
            max_bytes=3,
        ),
    ):
        pytest.fail("oversized bytes admitted")
    assert list(scratch.iterdir()) == []


def test_snapshot_directory_must_be_private_and_never_a_symlink(media_paths) -> None:
    project, scratch, source = media_paths
    expected = digest(source.read_bytes())
    scratch.chmod(493)
    with (
        pytest.raises(RequiredEvidenceMissingError),
        inputs().verified_probe_file(
            project_root=project, object_ref=str(source), expected_digest=expected, directory=scratch
        ),
    ):
        pytest.fail("nonprivate scratch admitted")
    scratch.chmod(448)
    linked = scratch.parent / "scratch-link"
    linked.symlink_to(scratch, target_is_directory=True)
    with (
        pytest.raises(RequiredEvidenceMissingError),
        inputs().verified_probe_file(
            project_root=project, object_ref=str(source), expected_digest=expected, directory=linked
        ),
    ):
        pytest.fail("symlinked scratch admitted")


def test_file_growing_after_initial_stat_is_stopped_at_the_read_ceiling(media_paths, monkeypatch) -> None:
    import os

    project, scratch, source = media_paths
    original_read = os.read
    identity = source.stat().st_ino
    grew = False

    def growing_read(descriptor: int, count: int) -> bytes:
        nonlocal grew
        chunk = original_read(descriptor, count)
        if chunk and not grew and os.fstat(descriptor).st_ino == identity:
            grew = True
            with source.open("ab") as handle:
                handle.write(b"x" * 32)
        return chunk

    monkeypatch.setattr(os, "read", growing_read)
    with (
        pytest.raises(OperationalEnvelopeExceededError),
        inputs().verified_probe_file(
            project_root=project,
            object_ref=str(source),
            expected_digest=digest(b"measured-master"),
            directory=scratch,
            max_bytes=16,
        ),
    ):
        pytest.fail("growing input was admitted")
    assert grew
    assert list(scratch.iterdir()) == []


def test_source_replaced_mid_copy_never_substitutes_unverified_bytes(media_paths, monkeypatch) -> None:
    import os

    project, scratch, source = media_paths
    original_read = os.read
    identity = source.stat().st_ino
    replaced = False

    def replacing_read(descriptor: int, count: int) -> bytes:
        nonlocal replaced
        chunk = original_read(descriptor, count)
        if chunk and not replaced and os.fstat(descriptor).st_ino == identity:
            replaced = True
            source.unlink()
            source.write_bytes(b"replacement")
        return chunk

    monkeypatch.setattr(os, "read", replacing_read)
    with inputs().verified_probe_file(
        project_root=project, object_ref=str(source), expected_digest=digest(b"measured-master"), directory=scratch
    ) as snapshot:
        assert snapshot.path.read_bytes() == b"measured-master"
    assert replaced
    assert source.read_bytes() == b"replacement"
    assert list(scratch.iterdir()) == []


async def test_existing_verified_snapshot_and_new_snapshot_match_on_the_same_bytes(media_paths) -> None:
    from server.services.format_render import verified_snapshot

    project, scratch, source = media_paths
    expected = digest(source.read_bytes())
    legacy_directory = scratch.parent / "legacy"
    async with verified_snapshot(source, expected, legacy_directory) as legacy:
        legacy_bytes = legacy.read_bytes()
    assert not legacy.exists()
    with inputs().verified_probe_file(
        project_root=project, object_ref=str(source), expected_digest=expected, directory=scratch
    ) as current:
        assert current.path.read_bytes() == legacy_bytes
        assert current.digest == expected


def bound_request(recipe: object, master: Path, *, caption_digest: str | None = None):
    from r2.quality.digests import compute_digest
    from r2.quality.ports import ProbeRequest
    from tests.unit.r2.quality.test_probes import probe_request_data, recipe_config

    config = recipe_config(recipe) if isinstance(recipe, str) else recipe
    from r2.quality.probes import policy_digest

    data = probe_request_data(config)
    primary = config.primary_tool()
    data["rule"].update(tool_identity=primary.name, tool_version_constraint="==" + primary.version)
    if config.reference_policy is not None:
        data["profile"]["policy"].update(
            reference_eligibility_policy_id=config.reference_policy.policy_id,
            reference_eligibility_policy_digest=policy_digest(config.reference_policy),
        )
    data["profile"]["policy_digest"] = compute_digest("m10.quality-policy.v1", data["profile"]["policy"])
    data["profile"]["profile_digest"] = compute_digest("m10.quality-profile.v1", data["profile"])
    subject = data["subject"].model_dump(mode="json")
    content = hashlib.sha256(master.read_bytes()).hexdigest()
    subject["master_binding"]["root"].update(object_ref=str(master), content_digest=content)
    subject["master_binding_digest"] = compute_digest("m10.master-binding.v1", subject["master_binding"])
    subject.update(artifact_ref=str(master), artifact_digest="sha256:" + content, caption_digest=caption_digest)
    data["subject"] = subject
    return (config, ProbeRequest.model_validate(data))


def binding(role: str, name: str, relative_path: str, content: bytes, *, project_name: str | None = None):
    from r2.quality.probes import ProbeInputBinding
    from tests.unit.r2.quality.test_quality_ports import probe_data

    scope = probe_data()
    return ProbeInputBinding(
        schema_id="m10.probe-input-binding.v1",
        user_id=scope["user_id"],
        project_name=project_name or scope["project_name"],
        role=role,
        name=name,
        relative_path=relative_path,
        content_digest=digest(content),
    )


def catalog(config, *bindings):
    from r2.quality.probes import ProbeCatalog

    return ProbeCatalog(schema_id="m10.probe-catalog.v1", configs=(config,), bindings=bindings)


async def test_combined_inputs_bind_master_and_catalog_scoped_companion_bytes(media_paths) -> None:
    project, _, source = media_paths
    (project / "refs").mkdir()
    (project / "refs" / "source.mp4").write_bytes(b"reference-bytes")
    config, request = bound_request("REFERENCE_VMAF", source)
    bound = catalog(config, binding("REFERENCE", "approved-source", "refs/source.mp4", b"reference-bytes"))
    async with inputs().snapshot_probe_inputs(request, project_root=project, catalog=bound) as admitted:
        assert admitted.config == config
        assert admitted.target.path.read_bytes() == b"measured-master"
        assert admitted.reference is not None
        assert admitted.reference.path.read_bytes() == b"reference-bytes"
        assert admitted.caption is None
        assert admitted.input_digests == (digest(b"measured-master"), digest(b"reference-bytes"))
        directory = admitted.target.path.parent
        assert directory.stat().st_mode & 511 == 448
        (project / "refs" / "source.mp4").write_bytes(b"replaced")
        assert admitted.reference.path.read_bytes() == b"reference-bytes"
    assert not directory.exists()


async def test_caption_binding_must_match_the_subject_caption_digest(media_paths) -> None:
    from r2.quality.errors import RequiredEvidenceMissingError

    project, _, source = media_paths
    (project / "captions.srt").write_bytes(b"1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    caption = binding("CAPTION", "captions", "captions.srt", (project / "captions.srt").read_bytes())
    config, request = bound_request("CAPTIONS", source, caption_digest=caption.content_digest)
    async with inputs().snapshot_probe_inputs(request, project_root=project, catalog=catalog(config, caption)) as got:
        assert got.input_digests == (digest(source.read_bytes()), caption.content_digest)
        assert got.reference is None
    _, missing = bound_request("CAPTIONS", source, caption_digest=None)
    _, foreign = bound_request("CAPTIONS", source, caption_digest=digest(b"other captions"))
    for unbound in (missing, foreign):
        with pytest.raises(RequiredEvidenceMissingError):
            async with inputs().snapshot_probe_inputs(unbound, project_root=project, catalog=catalog(config, caption)):
                pytest.fail("unbound caption admitted")


@pytest.mark.parametrize("case", ["absent", "changed", "foreign_scope", "symlink", "special"])
async def test_invalid_named_reference_is_reference_invalid_and_leaves_no_copy(media_paths, case: str) -> None:
    import os

    from r2.quality.errors import ReferenceInvalidError

    project, _, source = media_paths
    (project / "refs").mkdir()
    reference = project / "refs" / "source.mp4"
    reference.write_bytes(b"reference-bytes")
    config, request = bound_request("REFERENCE_VMAF", source)
    entry = binding("REFERENCE", "approved-source", "refs/source.mp4", b"reference-bytes")
    if case == "absent":
        reference.unlink()
    elif case == "changed":
        reference.write_bytes(b"changed")
    elif case == "foreign_scope":
        entry = binding("REFERENCE", "approved-source", "refs/source.mp4", b"reference-bytes", project_name="other")
    elif case == "symlink":
        (project / "outside.mp4").write_bytes(b"reference-bytes")
        reference.unlink()
        reference.symlink_to(project / "outside.mp4")
    else:
        reference.unlink()
        os.mkfifo(reference)
    seen: list[Path] = []
    original = inputs().tempfile.mkdtemp

    def tracked(*args, **kwargs):
        seen.append(Path(original(*args, **kwargs)))
        return str(seen[-1])

    import unittest.mock

    with unittest.mock.patch.object(inputs().tempfile, "mkdtemp", tracked), pytest.raises(ReferenceInvalidError):
        async with inputs().snapshot_probe_inputs(request, project_root=project, catalog=catalog(config, entry)):
            pytest.fail("invalid reference admitted")
    assert (case == "foreign_scope") == (not seen)
    assert not any(path.exists() for path in seen)


async def test_master_digest_mismatch_and_combined_byte_ceiling_fail_closed(media_paths) -> None:
    from r2.quality.errors import OperationalEnvelopeExceededError, RequiredEvidenceMissingError

    project, _, source = media_paths
    config, request = bound_request("DECODE", source)
    source.write_bytes(b"replacement-master")
    with pytest.raises(RequiredEvidenceMissingError):
        async with inputs().snapshot_probe_inputs(request, project_root=project, catalog=catalog(config)):
            pytest.fail("changed master admitted")
    import os

    # Sparse sources keep the ceiling fixtures from occupying memory-backed temporary storage.
    big = b"\0" * 67108864
    reference = project / "refs" / "source.mp4"
    reference.parent.mkdir()
    try:
        for path in (source, reference):
            path.write_bytes(b"")
            os.truncate(path, 67108864)
        config, request = bound_request("REFERENCE_VMAF", source)
        entry = binding("REFERENCE", "approved-source", "refs/source.mp4", big)
        async with inputs().snapshot_probe_inputs(request, project_root=project, catalog=catalog(config, entry)) as got:
            assert got.reference is not None
            assert got.target.size_bytes + got.reference.size_bytes == 134217728
        os.truncate(reference, 67108865)
        entry = binding("REFERENCE", "approved-source", "refs/source.mp4", big + b"\0")
        with pytest.raises(OperationalEnvelopeExceededError):
            async with inputs().snapshot_probe_inputs(request, project_root=project, catalog=catalog(config, entry)):
                pytest.fail("combined ceiling exceeded")
    finally:
        source.unlink(missing_ok=True)
        reference.unlink(missing_ok=True)


def test_catalog_bindings_reject_escaping_paths_and_ambiguous_scope() -> None:
    from pydantic import ValidationError

    from tests.unit.r2.quality.test_probes import recipe_config

    for path in ("/abs/ref.mp4", "../ref.mp4", "refs/../ref.mp4", "refs//ref.mp4", ".hidden", "refs/"):
        with pytest.raises(ValidationError):
            binding("REFERENCE", "approved-source", path, b"x")
    entry = binding("REFERENCE", "approved-source", "a.mp4", b"x")
    with pytest.raises(ValidationError):
        catalog(recipe_config("REFERENCE_VMAF"), entry, binding("REFERENCE", "approved-source", "b.mp4", b"y"))
