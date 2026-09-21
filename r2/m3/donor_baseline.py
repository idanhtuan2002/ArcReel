"""Content-addressed drift detection for M3's vendored donor surface (R2-DEC-031).

``compute_vendor_tree_digest`` is deliberately pure Python (no git subprocess):
it must work identically whether the vendored files are committed, staged, or
freshly copied, and must not depend on the caller's git index state.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# Install-time/build-time artifacts that never belong to the donor's own
# source tree (see .gitignore's vendor/**/ entries) -- excluded explicitly so
# this digest is stable regardless of whether `npm install`/a render already
# ran in this same checkout before the check does.
_EXCLUDED_DIR_NAMES = frozenset({"node_modules", ".remotion", "out"})


def _is_excluded(path: Path, *, root: Path) -> bool:
    relative_parts = path.relative_to(root).parts
    return any(part in _EXCLUDED_DIR_NAMES for part in relative_parts)


def compute_vendor_tree_digest(root: Path) -> str:
    """SHA-256 over every file's ``relative_path:sha256(content)`` line, sorted
    by path. Two directory trees with identical file paths and byte content
    always produce the same digest, regardless of file mtimes/permissions or
    which repository they live in. Skips install-time artifacts
    (``node_modules/``, ``.remotion/``, ``out/``) so the digest reflects only
    the donor's own vendored source, not whatever a prior `npm install` or
    render left behind in the same checkout.
    """
    entries = [
        f"{path.relative_to(root).as_posix()}:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        for path in sorted(root.rglob("*"))
        if path.is_file() and not _is_excluded(path, root=root)
    ]
    return hashlib.sha256("\n".join(entries).encode()).hexdigest()


__all__ = ["compute_vendor_tree_digest"]
