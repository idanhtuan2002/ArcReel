"""The approved final cut and its export copy (ADR-0090, O2a).

Gate C approves a ``COMPOSITE`` final whose direct dependencies are the shot masters it was
composed from, each recorded as a ``master:<shot_ref>`` snapshot. ``ApprovedMasterResolver``
resolves those refs from the shots' current approved masters, so the existing currency bridge
marks the final stale when a master changes. The export is a byte copy of the approved final in
``output/``; a deliverable is exportable only while the final is current and the copy's bytes
equal the approved bytes.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from pydantic import ValidationError

from lib.artifact_manifest import ArtifactKind, ProjectArtifactManifestAdapter
from r2.contracts.enums import ArtifactCurrencyStatus, ProductionMethod
from r2.production import (
    ArcReelArtifactManifestPort,
    DependencyResolverRegistry,
    DependencySnapshot,
    R2ArtifactBridge,
    R2ArtifactMetadata,
)
from r2.production.dependency_resolver import UnresolvedDependencyError

from .host_integration import GoldenAHostIntegration, safe_project_subdir, validate_m3_target_ref

COMPOSITE_CONTRACT_TYPE = "GoldenAComposite"
#: An audio track whose peak is at or below this level counts as silent (ADR-0092).
SILENCE_PEAK_DB = -60.0
MASTER_REF_PREFIX = "master:"
EXPORT_DIRNAME = "output"


class SourceMasterMismatchError(ValueError):
    """A composite names a shot master that is not that shot's current approved master."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_sha256(value: str) -> str:
    return value.removeprefix("sha256:").lower()


class ApprovedMasterResolver:
    """Resolve ``master:<shot_ref>`` to the shot's current approved master and its file bytes."""

    def __init__(self, host: GoldenAHostIntegration) -> None:
        self._host = host

    def supports(self, ref: str) -> bool:
        return ref.startswith(MASTER_REF_PREFIX)

    def resolve(self, ref: str) -> DependencySnapshot:
        shot_ref = ref.removeprefix(MASTER_REF_PREFIX)
        try:
            metadata = self._host.snapshot(shot_ref)
        except (KeyError, ValueError) as exc:
            raise UnresolvedDependencyError(ref) from exc
        if metadata.contract_ref.contract_type != "ShotSpec":
            raise UnresolvedDependencyError(ref)
        master = metadata.approved_master
        current = self._host.current_file_for(shot_ref)
        if master is None or not current.is_file():
            raise UnresolvedDependencyError(ref)
        digest = _selected_version_digest(self._host, shot_ref, master.host_version_ref, master.selected_candidate_id)
        if digest is None or sha256_file(current) != digest:
            raise UnresolvedDependencyError(ref)
        return DependencySnapshot(
            ref=ref,
            version=f"{master.selected_candidate_id}@{master.host_version_ref}",
            fingerprint=digest,
        )


def composite_dependencies(host: GoldenAHostIntegration, source_master_refs: Sequence[str]) -> list[DependencySnapshot]:
    """The final's direct dependencies, derived from the shot masters it names.

    Each source ref is ``<shot_ref>:<selected_candidate_id>:<host_version_ref>`` and must name
    the shot's current approved master; the snapshot carries the master file's own digest.
    """
    if not source_master_refs:
        raise SourceMasterMismatchError("a COMPOSITE final names no source shot masters")
    resolver = ApprovedMasterResolver(host)
    dependencies: list[DependencySnapshot] = []
    for source in source_master_refs:
        shot_ref, sep, rest = source.partition(":")
        candidate_id, sep2, version_ref = rest.rpartition(":")
        if not (shot_ref and sep and sep2 and candidate_id and version_ref):
            raise SourceMasterMismatchError(f"malformed source master ref {source!r}")
        try:
            snapshot = resolver.resolve(MASTER_REF_PREFIX + shot_ref)
        except UnresolvedDependencyError as exc:
            raise SourceMasterMismatchError(f"{shot_ref} has no approved master") from exc
        if snapshot.version != f"{candidate_id}@{version_ref}":
            raise SourceMasterMismatchError(f"{source!r} is not the current approved master of {shot_ref}")
        dependencies.append(snapshot)
    return dependencies


_MAX_VOLUME_RE = re.compile(r"max_volume:\s*(-?inf|-?\d+(?:\.\d+)?) dB")


def audio_peak_db(path: Path) -> float | None:
    """Peak level of the file's first audio stream in dB, or ``None`` when it has no audio stream.

    Raises ``ValueError`` when the file is not readable media.
    """
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        raise ValueError(f"{path.name} is not a readable media file")
    if not probe.stdout.strip():
        return None
    measured = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    match = _MAX_VOLUME_RE.search(measured.stderr) if measured.returncode == 0 else None
    if match is None:
        raise ValueError(f"ffmpeg reported no audio level for {path.name}")
    return float(match.group(1))


def audio_decision_holds(decision: str, path: Path) -> bool:
    """``MUTE``: no audio stream or a peak at or below ``SILENCE_PEAK_DB``; ``AUDIO``: a louder stream."""
    peak = audio_peak_db(path)
    silent = peak is None or peak <= SILENCE_PEAK_DB
    return silent if decision == "MUTE" else not silent


def export_relative_path(episode: int, target_ref: str) -> str:
    validate_m3_target_ref(target_ref)
    return f"{EXPORT_DIRNAME}/ep{episode}-{target_ref}.mp4"


@dataclass(frozen=True)
class ExportCopy:
    relative_path: str
    sha256: str


def write_export_copy(host: GoldenAHostIntegration, target_ref: str) -> ExportCopy:
    """Copy the approved final's bytes to ``output/`` atomically and return the copy's digest."""
    source = host.current_file_for(target_ref)
    approved = host.snapshot(target_ref).approved_master
    expected = (
        _approved_version_digest(host, target_ref, approved.host_version_ref, approved.selected_candidate_id)
        if approved is not None
        else None
    )
    if expected is None or sha256_file(source) != expected:
        raise ValueError("approved final differs from the selected version's bytes")
    relative = export_relative_path(host.episode, target_ref)
    destination = _export_path(host.project_dir, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out, source.open("rb") as src:
            shutil.copyfileobj(src, out, 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        if sha256_file(Path(temp_name)) != expected:
            raise ValueError("export copy differs from the approved final")
        os.replace(temp_name, destination)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    copied = sha256_file(destination)
    if copied != expected:
        raise OSError(f"export copy of {target_ref} does not match the approved final")
    return ExportCopy(relative_path=relative, sha256=copied)


@dataclass(frozen=True)
class Deliverable:
    episode: int
    target_ref: str
    artifact_key: str
    currency: str
    approved_sha256: str | None
    current_sha256: str | None
    export_relative_path: str
    export_sha256: str | None

    @property
    def exportable(self) -> bool:
        return (
            self.currency == ArtifactCurrencyStatus.CURRENT.value
            and self.approved_sha256 is not None
            and self.current_sha256 == self.approved_sha256
            and self.export_sha256 == self.approved_sha256
        )


def _file_digest(path: Path) -> str | None:
    return sha256_file(path) if path.is_file() and not path.is_symlink() else None


def _export_path(project_dir: Path, relative: str) -> Path:
    directory = safe_project_subdir(project_dir, EXPORT_DIRNAME)
    path = directory / Path(relative).name
    if path.is_symlink() or path.resolve().parent != directory.resolve():
        raise ValueError("export file must stay inside the project")
    return path


def _selected_version_digest(
    host: GoldenAHostIntegration,
    target_ref: str,
    host_version_ref: str,
    selected_candidate_id: str,
    expected_method: str | None = None,
) -> str | None:
    try:
        version = int(host_version_ref)
    except ValueError:
        return None
    if version <= 0 or str(version) != host_version_ref:
        return None
    versions = host.versions.get_versions("videos", target_ref)
    if versions["current_version"] != version:
        return None
    record = next((item for item in versions["versions"] if item["version"] == version), None)
    if record is None:
        return None
    method = record.get("method")
    shot_methods = {item.value for item in ProductionMethod if item is not ProductionMethod.COMPOSITE}
    if expected_method is None and method not in shot_methods:
        return None
    if expected_method is not None and method != expected_method:
        return None
    if selected_candidate_id != f"CAND-{target_ref}-V{version}":
        return None
    digest = record.get("output_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        return None
    return digest


def _approved_version_digest(
    host: GoldenAHostIntegration, target_ref: str, host_version_ref: str, selected_candidate_id: str
) -> str | None:
    return _selected_version_digest(host, target_ref, host_version_ref, selected_candidate_id, "COMPOSITE")


def current_deliverables(project_dir: Path) -> list[Deliverable]:
    """Every Gate C-approved composite final in the project, with currency and export state."""
    project_dir = Path(project_dir)
    entries = ProjectArtifactManifestAdapter(project_dir).snapshot_entries()
    port = ArcReelArtifactManifestPort(project_dir, native_currency=lambda _key: ArtifactCurrencyStatus.CURRENT)
    deliverables: list[Deliverable] = []
    for key, entry in sorted(entries.items(), key=lambda item: item[0].encode()):
        if key.kind is not ArtifactKind.EPISODE_VIDEO or entry.r2 is None:
            continue
        try:
            metadata = R2ArtifactMetadata.model_validate(entry.r2)
        except ValidationError:
            continue
        if metadata.contract_ref.contract_type != COMPOSITE_CONTRACT_TYPE or metadata.approved_master is None:
            continue
        episode, target_ref = int(key.components[0]), str(key.components[1])
        try:
            relative = export_relative_path(episode, target_ref)
        except ValueError:
            continue
        host = GoldenAHostIntegration(project_dir, resource_type="videos", episode=episode)
        bridge = R2ArtifactBridge(port, DependencyResolverRegistry([ApprovedMasterResolver(host)]))
        status = bridge.evaluate_currency(key.encode()).status
        try:
            current_digest = _file_digest(host.current_file_for(target_ref))
            export_digest = _file_digest(_export_path(project_dir, relative))
        except ValueError:
            current_digest = None
            export_digest = None
        deliverables.append(
            Deliverable(
                episode=episode,
                target_ref=target_ref,
                artifact_key=key.encode(),
                currency=status.value if status is not None else "LEGACY",
                approved_sha256=_approved_version_digest(
                    host,
                    target_ref,
                    metadata.approved_master.host_version_ref,
                    metadata.approved_master.selected_candidate_id,
                ),
                current_sha256=current_digest,
                export_relative_path=relative,
                export_sha256=export_digest,
            )
        )
    return deliverables


def exportable_deliverable(project_dir: Path, digest: str) -> Deliverable | None:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
        return None
    wanted = normalize_sha256(digest)
    return next((d for d in current_deliverables(project_dir) if d.exportable and d.export_sha256 == wanted), None)


def verified_export_snapshot(project_dir: Path, digest: str) -> tuple[Deliverable, BinaryIO] | None:
    deliverable = exportable_deliverable(project_dir, digest)
    if deliverable is None:
        return None
    try:
        source = _export_path(project_dir, deliverable.export_relative_path)
    except ValueError:
        return None
    try:
        with tempfile.TemporaryFile(mode="w+b") as snapshot, source.open("rb") as original:
            actual = hashlib.sha256()
            for chunk in iter(lambda: original.read(1024 * 1024), b""):
                snapshot.write(chunk)
                actual.update(chunk)
            if actual.hexdigest() != deliverable.approved_sha256:
                return None
            snapshot.flush()
            snapshot.seek(0)
            return deliverable, os.fdopen(os.dup(snapshot.fileno()), "rb")
    except FileNotFoundError:
        return None


__all__ = [
    "COMPOSITE_CONTRACT_TYPE",
    "MASTER_REF_PREFIX",
    "SILENCE_PEAK_DB",
    "ApprovedMasterResolver",
    "Deliverable",
    "ExportCopy",
    "SourceMasterMismatchError",
    "audio_decision_holds",
    "audio_peak_db",
    "composite_dependencies",
    "current_deliverables",
    "export_relative_path",
    "exportable_deliverable",
    "normalize_sha256",
    "sha256_file",
    "verified_export_snapshot",
    "write_export_copy",
]
