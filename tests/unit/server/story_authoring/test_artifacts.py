from __future__ import annotations

import os
from pathlib import Path

import pytest

from server.story_authoring.artifacts import (
    BLOB_ROOT,
    BlobCorrupt,
    BlobMissing,
    StoryBlobStore,
    UnsafeBlobPath,
    content_digest,
)

TEXT = "Minh mở cửa căn nhà cũ.".encode()


def test_content_is_stored_once_by_digest_and_read_back_exactly(tmp_path: Path):
    store = StoryBlobStore(tmp_path)

    digest = store.put(TEXT)

    assert digest == content_digest(TEXT)
    assert store.put(TEXT) == digest
    assert store.read_exact(digest) == TEXT
    assert store.exists(digest)
    assert store.list_digests() == (digest,)
    path = tmp_path / BLOB_ROOT / digest[7:9] / digest[7:]
    assert path.read_bytes() == TEXT


def test_a_missing_blob_is_reported(tmp_path: Path):
    store = StoryBlobStore(tmp_path)
    with pytest.raises(BlobMissing):
        store.read_exact(content_digest(b"never stored"))
    assert not store.exists(content_digest(b"never stored"))


def test_tampered_content_is_detected_on_read_and_on_put(tmp_path: Path):
    store = StoryBlobStore(tmp_path)
    digest = store.put(TEXT)
    (tmp_path / BLOB_ROOT / digest[7:9] / digest[7:]).write_bytes(b"changed")

    with pytest.raises(BlobCorrupt):
        store.read_exact(digest)
    with pytest.raises(BlobCorrupt):
        store.put(TEXT)


@pytest.mark.parametrize(
    "digest",
    ["../../etc/passwd", "sha256:" + "A" * 64, "sha256:" + "0" * 63, "md5:" + "0" * 32, "sha256:../" + "0" * 61],
)
def test_only_well_formed_digests_name_a_path(tmp_path: Path, digest: str):
    with pytest.raises(UnsafeBlobPath):
        StoryBlobStore(tmp_path).read_exact(digest)


@pytest.mark.skipif(os.name != "posix", reason="symlink creation needs POSIX permissions")
def test_a_symlinked_blob_directory_is_refused(tmp_path: Path):
    project = tmp_path / "project"
    elsewhere = tmp_path / "elsewhere"
    project.mkdir()
    elsewhere.mkdir()
    (project / "story_authoring").symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(UnsafeBlobPath):
        StoryBlobStore(project).put(TEXT)
    assert list(elsewhere.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="symlink creation needs POSIX permissions")
def test_a_symlinked_blob_file_is_refused(tmp_path: Path):
    store = StoryBlobStore(tmp_path)
    digest = content_digest(TEXT)
    shard = tmp_path / BLOB_ROOT / digest[7:9]
    shard.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(TEXT)
    (shard / digest[7:]).symlink_to(outside)

    with pytest.raises(UnsafeBlobPath):
        store.read_exact(digest)
    assert not store.exists(digest)


def test_listing_ignores_temporary_and_foreign_files(tmp_path: Path):
    store = StoryBlobStore(tmp_path)
    digest = store.put(TEXT)
    shard = tmp_path / BLOB_ROOT / digest[7:9]
    (shard / ".rollback.123.tmp").write_bytes(b"partial")
    (tmp_path / BLOB_ROOT / "notes.txt").write_bytes(b"x")

    assert store.list_digests() == (digest,)
