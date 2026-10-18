"""Content-addressed, immutable storage of story-authoring content inside the project directory.

Every proposal revision, manifest and export is stored once under ``<project>/story_authoring/blobs/`` at a
path derived only from its sha256 digest, written atomically (same-directory temp file + ``os.replace``) and
verified against its digest on every read. A digest is the only input a caller supplies, so no path can be
injected; a symlink anywhere between the project directory and the blob refuses the operation. Content lives
under the projects root, which the deployment backup covers file by file.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path

from lib.json_io import atomic_write_bytes

BLOB_ROOT = Path("story_authoring") / "blobs"
_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")


class BlobStoreError(RuntimeError):
    pass


class BlobMissing(BlobStoreError):
    pass


class BlobCorrupt(BlobStoreError):
    pass


class UnsafeBlobPath(BlobStoreError):
    pass


def content_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class StoryBlobStore:
    def __init__(self, project_dir: Path) -> None:
        self._project_dir = Path(project_dir)

    def put(self, data: bytes) -> str:
        """Store ``data`` and return its digest; storing identical bytes again is a no-op."""
        digest = content_digest(data)
        path = self._path(digest, create_dirs=True)
        if self._exists_regular(path):
            if content_digest(path.read_bytes()) != digest:
                raise BlobCorrupt(f"stored content for {digest} does not match its digest")
            return digest
        atomic_write_bytes(path, data)
        return digest

    def read_exact(self, digest: str) -> bytes:
        path = self._path(digest, create_dirs=False)
        if not self._exists_regular(path):
            raise BlobMissing(digest)
        data = path.read_bytes()
        if content_digest(data) != digest:
            raise BlobCorrupt(f"stored content for {digest} does not match its digest")
        return data

    def exists(self, digest: str) -> bool:
        try:
            return self._exists_regular(self._path(digest, create_dirs=False))
        except UnsafeBlobPath:
            return False

    def list_digests(self) -> tuple[str, ...]:
        """Every stored digest, for orphan accounting; temp files and foreign names are ignored."""
        root = self._project_dir / BLOB_ROOT
        self._refuse_symlinks(root)
        if not root.is_dir():
            return ()
        found: list[str] = []
        for shard in sorted(root.iterdir()):
            if shard.is_symlink() or not shard.is_dir() or not re.fullmatch(r"[0-9a-f]{2}", shard.name):
                continue
            found.extend(
                "sha256:" + entry.name
                for entry in sorted(shard.iterdir())
                if re.fullmatch(r"[0-9a-f]{64}", entry.name) and entry.name.startswith(shard.name)
            )
        return tuple(found)

    def _path(self, digest: str, *, create_dirs: bool) -> Path:
        match = _DIGEST.match(digest)
        if match is None:
            raise UnsafeBlobPath(f"not a sha256 digest: {digest!r}")
        hex_digest = match.group(1)
        directory = self._project_dir / BLOB_ROOT / hex_digest[:2]
        if create_dirs:
            self._refuse_symlinks(directory)
            directory.mkdir(parents=True, exist_ok=True)
        path = directory / hex_digest
        self._refuse_symlinks(path)
        return path

    def _refuse_symlinks(self, path: Path) -> None:
        """Refuse when the project directory or any existing component below it is a symlink."""
        if self._project_dir.is_symlink():
            raise UnsafeBlobPath(f"project directory {self._project_dir} is a symlink")
        current = self._project_dir
        for part in path.relative_to(self._project_dir).parts:
            current = current / part
            if current.is_symlink():
                raise UnsafeBlobPath(f"{current} is a symlink")

    @staticmethod
    def _exists_regular(path: Path) -> bool:
        try:
            mode = os.lstat(path).st_mode
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(mode):
            raise UnsafeBlobPath(f"{path} is not a regular file")
        return True
