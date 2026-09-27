"""Whole-deployment backup sets under the V1 offline fence (H6, ADR-0078, ADR-0090).

A deployment backup set binds one PostgreSQL recovery point to every regular
file under the deployment's named data roots. It is captured only while the
operator has stopped the application and worker. Capture proves that fence
instead of trusting it: before and after the copy it requires zero other
client sessions on the database, no queued/running/cancelling Task, an
unchanged database write counter and an unchanged file-tree fingerprint.
Capture never writes to the source database.

Credential-bearing rows never enter the set. Their table data is excluded from
``pg_dump`` and captured separately as a binary COPY of the rows with credential
columns blanked (``SANITIZED_TABLE_POLICY``). Known secret files at the top of
the data root are excluded and named in the manifest. After a restore the
operator re-enters provider credentials.

The set directory is the durable ledger of its own lifecycle: ``state.json``
moves ``PREPARING -> COMPLETE -> VERIFIED`` or to ``REJECTED``, bound to the
canonical digest of ``manifest.json``; ``verdict.json`` records the
clean-target verification.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import stat
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import asyncpg

from lib.content_digest import canonical_json_digest
from lib.json_io import atomic_write_bytes
from r2.contracts.host_hardening import (
    BackupFileEntry,
    BackupSetState,
    DeploymentBackupManifest,
    DeploymentBackupVerdict,
    OfflineFenceEvidence,
    SanitizedTableEntry,
)

DATA_ROOT = "data"
MANIFEST_FILENAME = "manifest.json"
STATE_FILENAME = "state.json"
VERDICT_FILENAME = "verdict.json"
DUMP_FILENAME = "database.dump"
SANITIZED_DIRNAME = "sanitized"
FILES_DIRNAME = "files"

ACTIVE_TASK_STATUSES = ("queued", "running", "cancelling")

# Top-level entries of the ``data`` root that are never captured: legacy
# configuration that can hold provider keys, the legacy SQLite database (the V1
# baseline is PostgreSQL) and application logs.
EXCLUDED_DATA_ENTRIES = (
    ".arcreel.db",
    ".arcreel.db-journal",
    ".arcreel.db-shm",
    ".arcreel.db-wal",
    ".system_config.json",
    ".system_config.json.bak",
    "logs",
)

_SECRET_SETTING_KEY_PATTERN = "(api_key|apikey|secret|token|password|credential)"

# table -> column -> SQL expression replacing that column in the captured rows.
SANITIZED_TABLE_POLICY: Mapping[str, Mapping[str, str]] = {
    "provider_credential": {
        "api_key": "NULL",
        "access_key": "NULL",
        "secret_key": "NULL",
        "credentials_path": "NULL",
    },
    "agent_anthropic_credentials": {"api_key": "''"},
    "custom_provider": {"api_key": "''"},
    "provider_config": {"value": "CASE WHEN is_secret THEN '' ELSE value END"},
    "system_setting": {"value": f"CASE WHEN key ~* '{_SECRET_SETTING_KEY_PATTERN}' THEN '' ELSE value END"},
}

# Post-restore proof that no credential value survived, per sanitized column.
_SECRET_RESIDUE_PREDICATES: Mapping[str, Mapping[str, str]] = {
    "provider_credential": {
        column: f"{column} IS NOT NULL" for column in SANITIZED_TABLE_POLICY["provider_credential"]
    },
    "agent_anthropic_credentials": {"api_key": "api_key <> ''"},
    "custom_provider": {"api_key": "api_key <> ''"},
    "provider_config": {"value": "is_secret AND value <> ''"},
    "system_setting": {"value": f"key ~* '{_SECRET_SETTING_KEY_PATTERN}' AND value <> ''"},
}

PROBED_MEDIA_SUFFIXES = frozenset({".mp4", ".mov", ".webm", ".mp3", ".wav", ".m4a", ".png", ".jpg", ".jpeg", ".webp"})

MediaProbe = Callable[[Path], Awaitable[bool]]


class DeploymentBackupError(Exception):
    """Base class for deployment backup failures; ``reason_code`` is stable."""

    reason_code = "BACKUP_FAILED"


class OfflineFenceViolation(DeploymentBackupError):
    reason_code = "OFFLINE_FENCE_VIOLATED"


class UnsupportedFileEntry(DeploymentBackupError):
    reason_code = "UNSUPPORTED_FILE_ENTRY"


class BackupIntegrityError(DeploymentBackupError):
    reason_code = "BACKUP_INTEGRITY"


class UnsafeBackupPath(DeploymentBackupError):
    reason_code = "UNSAFE_PATH"


class RestoreTargetNotEmpty(DeploymentBackupError):
    reason_code = "RESTORE_TARGET_NOT_EMPTY"


class BackupSetNotRestorable(DeploymentBackupError):
    reason_code = "BACKUP_SET_NOT_RESTORABLE"


class ExternalToolFailed(DeploymentBackupError):
    reason_code = "EXTERNAL_TOOL_FAILED"


@dataclass(frozen=True)
class ReleaseIdentity:
    source_deployment_id: str
    release_git_sha: str
    release_image_digest: str
    configuration: Mapping[str, Any]


@dataclass(frozen=True)
class _FenceSnapshot:
    other_sessions: int
    active_tasks: int
    write_counter: int
    file_fingerprint: str


# --------------------------------------------------------------------------- paths


def libpq_url(database_url: str) -> str:
    """``pg_dump``/asyncpg understand ``postgresql://``, not SQLAlchemy's driver-qualified form."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _paths_alias(a: Path, b: Path) -> bool:
    a, b = a.resolve(), b.resolve()
    return a == b or a in b.parents or b in a.parents


def _safe_relative(root: Path, ref: str) -> Path:
    """Resolve a manifest-relative POSIX path under ``root`` without following symlinks."""
    parts = PurePosixPath(ref).parts
    if (
        not ref
        or ref.startswith("/")
        or "\\" in ref
        or "\x00" in ref
        or any(part in {"", ".", ".."} for part in parts)
        or ":" in parts[0]
    ):
        raise UnsafeBackupPath("manifest path is not a safe relative path")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise UnsafeBackupPath("manifest path traverses a symlink")
    return current


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _is_empty_dir(path: Path) -> bool:
    return not path.exists() or (path.is_dir() and not any(path.iterdir()))


# --------------------------------------------------------------------------- file census


def _walk_regular_files(root_name: str, root: Path) -> list[tuple[str, os.stat_result]]:
    """Every regular file under ``root`` (sorted, POSIX-relative), refusing links and specials."""
    if root.is_symlink() or not root.is_dir():
        raise UnsupportedFileEntry(f"data root {root_name!r} is not a real directory")
    excluded = set(EXCLUDED_DATA_ENTRIES) if root_name == DATA_ROOT else set()
    found: list[tuple[str, os.stat_result]] = []

    def _visit(directory: Path, relative: PurePosixPath) -> None:
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                if not relative.parts and entry.name in excluded:
                    continue
                child_relative = relative / entry.name
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    _visit(Path(entry.path), child_relative)
                elif stat.S_ISREG(info.st_mode):
                    found.append((child_relative.as_posix(), info))
                else:
                    raise UnsupportedFileEntry(f"{root_name}:{child_relative.as_posix()} is not a regular file")

    _visit(root, PurePosixPath())
    return found


def _file_fingerprint(roots: Mapping[str, Path]) -> str:
    rows = [
        [name, relative, info.st_size, info.st_mtime_ns]
        for name in sorted(roots)
        for relative, info in _walk_regular_files(name, roots[name])
    ]
    return "sha256:" + canonical_json_digest(rows)


def _copy_files(roots: Mapping[str, Path], backup_dir: Path) -> list[BackupFileEntry]:
    entries: list[BackupFileEntry] = []
    for name in sorted(roots):
        for relative, info in _walk_regular_files(name, roots[name]):
            source = roots[name] / relative
            destination = backup_dir / FILES_DIRNAME / name / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            source_digest = _sha256_file(source)
            shutil.copy2(source, destination)
            if destination.stat().st_size != info.st_size or _sha256_file(destination) != source_digest:
                raise BackupIntegrityError(f"copy of {name}:{relative} is incomplete or changed while copying")
            entries.append(
                BackupFileEntry(root=name, path=relative, byte_size=info.st_size, content_digest=source_digest)
            )
    return entries


# --------------------------------------------------------------------------- database probes


async def _fetch_int(conn: asyncpg.Connection, query: str, *args: object) -> int:
    value = await conn.fetchval(query, *args)
    return 0 if value is None else int(value)


async def _other_client_sessions(conn: asyncpg.Connection) -> int:
    return await _fetch_int(
        conn,
        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
        "AND pid <> pg_backend_pid() AND backend_type = 'client backend'",
    )


async def _active_tasks(conn: asyncpg.Connection) -> int:
    return await _fetch_int(
        conn, "SELECT count(*) FROM tasks WHERE status = ANY($1::text[])", list(ACTIVE_TASK_STATUSES)
    )


async def _write_counter(conn: asyncpg.Connection) -> int:
    await conn.execute("SELECT pg_stat_clear_snapshot()")
    value = await conn.fetchval(
        "SELECT coalesce(tup_inserted + tup_updated + tup_deleted, 0) FROM pg_stat_database "
        "WHERE datname = current_database()"
    )
    return int(value or 0)


async def _fence_snapshot(conn: asyncpg.Connection, roots: Mapping[str, Path]) -> _FenceSnapshot:
    return _FenceSnapshot(
        other_sessions=await _other_client_sessions(conn),
        active_tasks=await _active_tasks(conn),
        write_counter=await _write_counter(conn),
        file_fingerprint=await asyncio.to_thread(_file_fingerprint, roots),
    )


def _assert_quiescent(snapshot: _FenceSnapshot, *, phase: str) -> None:
    if snapshot.other_sessions:
        raise OfflineFenceViolation(f"{phase}: {snapshot.other_sessions} other client session(s) are connected")
    if snapshot.active_tasks:
        raise OfflineFenceViolation(f"{phase}: {snapshot.active_tasks} task(s) are queued, running or cancelling")


async def _user_tables(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = current_schema() ORDER BY tablename")
    return [str(row["tablename"]) for row in rows]


async def _table_row_counts(conn: asyncpg.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in await _user_tables(conn):
        counts[table] = await _fetch_int(conn, f'SELECT count(*) FROM "{table}"')
    return counts


async def _table_columns(conn: asyncpg.Connection, table: str) -> list[str]:
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = $1 ORDER BY ordinal_position",
        table,
    )
    return [str(row["column_name"]) for row in rows]


async def _run_tool(argv: list[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        # stderr can echo connection details; keep only a bounded tail.
        tail = stderr.decode(errors="replace").strip().splitlines()[-3:]
        raise ExternalToolFailed(f"{Path(argv[0]).name} exited {process.returncode}: {' | '.join(tail)}")


# --------------------------------------------------------------------------- lifecycle ledger


def manifest_digest(manifest: DeploymentBackupManifest) -> str:
    return "sha256:" + canonical_json_digest(manifest.model_dump(mode="json"))


def _write_json(path: Path, value: object) -> None:
    atomic_write_bytes(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"))


def _write_state(backup_dir: Path, state: BackupSetState, *, now: datetime, **fields: object) -> None:
    _write_json(backup_dir / STATE_FILENAME, {"state": state.value, "updated_at": now.isoformat(), **fields})


def _open_backup_dir(backup_dir: Path, backup_set_id: str, now: datetime) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    _write_state(backup_dir, BackupSetState.PREPARING, now=now, backup_set_id=backup_set_id)


def read_state(backup_dir: Path) -> dict[str, Any]:
    return json.loads((backup_dir / STATE_FILENAME).read_text(encoding="utf-8"))


def read_manifest(backup_dir: Path) -> DeploymentBackupManifest:
    return DeploymentBackupManifest.model_validate_json((backup_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- capture


async def create_deployment_backup(
    *,
    backup_set_id: str,
    database_url: str,
    roots: Mapping[str, Path],
    backup_dir: Path,
    identity: ReleaseIdentity,
    pg_dump_path: str = "pg_dump",
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> DeploymentBackupManifest:
    """Capture one deployment backup set under the offline fence.

    ``roots`` must contain ``DATA_ROOT`` (the application data directory) and
    may name further directories the deployment persists. ``backup_dir`` must
    be empty and must not overlap any root.
    """
    if DATA_ROOT not in roots:
        raise UnsafeBackupPath(f"roots must include {DATA_ROOT!r}")
    for name, root in roots.items():
        if _paths_alias(backup_dir, root):
            raise UnsafeBackupPath(f"backup_dir overlaps root {name!r}")
    if not _is_empty_dir(backup_dir):
        raise UnsafeBackupPath("backup_dir is not empty")
    await asyncio.to_thread(_open_backup_dir, backup_dir, backup_set_id, clock())

    conn = await asyncpg.connect(libpq_url(database_url))
    try:
        before = await _fence_snapshot(conn, roots)
        _assert_quiescent(before, phase="before capture")
        recovery_point = clock()

        dump_path = backup_dir / DUMP_FILENAME
        exclude_args = [f"--exclude-table-data={table}" for table in sorted(SANITIZED_TABLE_POLICY)]
        await _run_tool(
            [
                pg_dump_path,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--no-password",
                *exclude_args,
                f"--file={dump_path}",
                libpq_url(database_url),
            ]
        )

        present_tables = set(await _user_tables(conn))
        sanitized: list[SanitizedTableEntry] = []
        (backup_dir / SANITIZED_DIRNAME).mkdir()
        for table in sorted(SANITIZED_TABLE_POLICY):
            if table not in present_tables:
                continue
            policy = SANITIZED_TABLE_POLICY[table]
            columns = await _table_columns(conn, table)
            select_list = ", ".join(f'{policy[c]} AS "{c}"' if c in policy else f'"{c}"' for c in columns)
            data_ref = f"{SANITIZED_DIRNAME}/{table}.copy"
            await conn.copy_from_query(
                f'SELECT {select_list} FROM "{table}"', output=str(backup_dir / data_ref), format="binary"
            )
            sanitized.append(
                SanitizedTableEntry(
                    table=table,
                    blanked_columns=tuple(sorted(c for c in policy if c in columns)),
                    row_count=await _fetch_int(conn, f'SELECT count(*) FROM "{table}"'),
                    data_ref=data_ref,
                    content_digest=_sha256_file(backup_dir / data_ref),
                )
            )

        files = await asyncio.to_thread(_copy_files, roots, backup_dir)
        row_counts = await _table_row_counts(conn)
        alembic_head = str(await conn.fetchval("SELECT version_num FROM alembic_version"))
        postgres_version = str(await conn.fetchval("SHOW server_version"))

        after = await _fence_snapshot(conn, roots)
        _assert_quiescent(after, phase="after capture")
        if after.write_counter != before.write_counter:
            raise OfflineFenceViolation("the database was written while capturing")
        if after.file_fingerprint != before.file_fingerprint:
            raise OfflineFenceViolation("data-root files changed while capturing")

        manifest = DeploymentBackupManifest(
            backup_set_id=backup_set_id,
            source_deployment_id=identity.source_deployment_id,
            release_git_sha=identity.release_git_sha,
            release_image_digest=identity.release_image_digest,
            postgres_version=postgres_version,
            alembic_head=alembic_head,
            recovery_point=recovery_point,
            database_backup_ref=DUMP_FILENAME,
            database_backup_digest=_sha256_file(dump_path),
            table_row_counts=row_counts,
            sanitized_tables=tuple(sanitized),
            excluded_data_entries=EXCLUDED_DATA_ENTRIES,
            files=tuple(files),
            configuration_digest="sha256:" + canonical_json_digest(dict(identity.configuration)),
            fence=OfflineFenceEvidence(
                other_sessions_before=before.other_sessions,
                other_sessions_after=after.other_sessions,
                active_tasks_before=before.active_tasks,
                active_tasks_after=after.active_tasks,
                write_counter_before=before.write_counter,
                write_counter_after=after.write_counter,
                file_fingerprint_before=before.file_fingerprint,
                file_fingerprint_after=after.file_fingerprint,
            ),
        )
        _write_json(backup_dir / MANIFEST_FILENAME, manifest.model_dump(mode="json"))
        _write_state(
            backup_dir,
            BackupSetState.COMPLETE,
            now=clock(),
            backup_set_id=backup_set_id,
            manifest_digest=manifest_digest(manifest),
        )
        return manifest
    except DeploymentBackupError as exc:
        _write_state(
            backup_dir, BackupSetState.REJECTED, now=clock(), backup_set_id=backup_set_id, reason=exc.reason_code
        )
        raise
    except Exception:
        _write_state(
            backup_dir, BackupSetState.REJECTED, now=clock(), backup_set_id=backup_set_id, reason="BACKUP_FAILED"
        )
        raise
    finally:
        await conn.close()


# --------------------------------------------------------------------------- restore


def load_restorable_manifest(backup_dir: Path) -> DeploymentBackupManifest:
    """The set's manifest, provided its ledger says it completed and it is byte-intact."""
    state = read_state(backup_dir)
    if state.get("state") not in {BackupSetState.COMPLETE.value, BackupSetState.VERIFIED.value}:
        raise BackupSetNotRestorable(f"backup set state is {state.get('state')!r}")
    manifest = read_manifest(backup_dir)
    if manifest_digest(manifest) != state.get("manifest_digest"):
        raise BackupIntegrityError("manifest does not match the digest recorded in state.json")
    _verify_backup_payload(manifest, backup_dir)
    return manifest


def _verify_backup_payload(manifest: DeploymentBackupManifest, backup_dir: Path) -> None:
    dump = _safe_relative(backup_dir, manifest.database_backup_ref)
    if not dump.is_file() or _sha256_file(dump) != manifest.database_backup_digest:
        raise BackupIntegrityError("database dump is missing or altered")
    for table in manifest.sanitized_tables:
        path = _safe_relative(backup_dir, table.data_ref)
        if not path.is_file() or _sha256_file(path) != table.content_digest:
            raise BackupIntegrityError(f"sanitized data for {table.table} is missing or altered")
    for entry in manifest.files:
        path = _safe_relative(backup_dir / FILES_DIRNAME, f"{entry.root}/{entry.path}")
        if not path.is_file() or path.stat().st_size != entry.byte_size or _sha256_file(path) != entry.content_digest:
            raise BackupIntegrityError(f"captured file {entry.root}:{entry.path} is missing or altered")


async def restore_deployment_backup(
    *,
    backup_dir: Path,
    target_database_url: str,
    target_roots: Mapping[str, Path],
    pg_restore_path: str = "pg_restore",
) -> DeploymentBackupManifest:
    """Restore a verified-intact backup set into an empty database and empty roots."""
    manifest = await asyncio.to_thread(load_restorable_manifest, backup_dir)
    captured_roots = {entry.root for entry in manifest.files} | {DATA_ROOT}
    missing = captured_roots - set(target_roots)
    if missing:
        raise UnsafeBackupPath(f"no target given for captured roots {sorted(missing)}")
    for name, root in target_roots.items():
        if _paths_alias(backup_dir, root):
            raise UnsafeBackupPath(f"target root {name!r} overlaps the backup set")
        if root.is_symlink() or not _is_empty_dir(root):
            raise RestoreTargetNotEmpty(f"target root {name!r} is not an empty directory")

    conn = await asyncpg.connect(libpq_url(target_database_url))
    try:
        if await _user_tables(conn):
            raise RestoreTargetNotEmpty("target database already has tables")
        dump = str(backup_dir / manifest.database_backup_ref)
        base = [pg_restore_path, "--no-owner", "--no-privileges", "--no-password", "--exit-on-error"]
        target = f"--dbname={libpq_url(target_database_url)}"
        await _run_tool([*base, "--section=pre-data", target, dump])
        await _run_tool([*base, "--section=data", target, dump])
        for table in manifest.sanitized_tables:
            columns = await _table_columns(conn, table.table)
            await conn.copy_to_table(
                table.table, source=str(backup_dir / table.data_ref), columns=columns, format="binary"
            )
        await _run_tool([*base, "--section=post-data", target, dump])
    finally:
        await conn.close()

    await asyncio.to_thread(_restore_files, manifest, backup_dir, target_roots)
    return manifest


def _restore_files(manifest: DeploymentBackupManifest, backup_dir: Path, target_roots: Mapping[str, Path]) -> None:
    for root in target_roots.values():
        root.mkdir(parents=True, exist_ok=True)
    for entry in manifest.files:
        source = _safe_relative(backup_dir / FILES_DIRNAME, f"{entry.root}/{entry.path}")
        destination = _safe_relative(target_roots[entry.root], entry.path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


# --------------------------------------------------------------------------- verification


async def ffprobe_media(path: Path) -> bool:
    """True when ffprobe decodes at least one stream of ``path``."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return False
    process = await asyncio.create_subprocess_exec(
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        return False
    try:
        return bool(json.loads(stdout or b"{}").get("streams"))
    except ValueError:
        return False


def _verify_files(manifest: DeploymentBackupManifest, target_roots: Mapping[str, Path]) -> list[str]:
    reasons: list[str] = []
    for entry in manifest.files:
        try:
            path = _safe_relative(target_roots[entry.root], entry.path)
        except UnsafeBackupPath:
            reasons.append(f"FILE_UNSAFE:{entry.root}:{entry.path}")
            continue
        if not path.is_file():
            reasons.append(f"FILE_MISSING:{entry.root}:{entry.path}")
        elif path.stat().st_size != entry.byte_size or _sha256_file(path) != entry.content_digest:
            reasons.append(f"FILE_MISMATCH:{entry.root}:{entry.path}")
    return reasons


def _project_references(data_root: Path) -> tuple[int, list[str], list[Path]]:
    """Check every project's metadata and version history resolves.

    Returns (checked reference count, reason codes, selected media to probe).
    """
    checked = 0
    reasons: list[str] = []
    selected_media: list[Path] = []
    for project_dir in sorted(p for p in data_root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        project_json = project_dir / "project.json"
        if not project_json.is_file():
            continue
        checked += 1
        try:
            if not isinstance(json.loads(project_json.read_text(encoding="utf-8")), dict):
                reasons.append(f"PROJECT_JSON_INVALID:{project_dir.name}")
        except ValueError:
            reasons.append(f"PROJECT_JSON_INVALID:{project_dir.name}")
        versions_file = project_dir / "versions" / "versions.json"
        if not versions_file.is_file():
            continue
        try:
            history = json.loads(versions_file.read_text(encoding="utf-8"))
        except ValueError:
            reasons.append(f"VERSIONS_JSON_INVALID:{project_dir.name}")
            continue
        for resource_type, bucket in history.items() if isinstance(history, dict) else ():
            if not isinstance(bucket, dict):
                continue
            for resource_id, resource in bucket.items():
                if not isinstance(resource, dict):
                    continue
                current = resource.get("current_version")
                for record in resource.get("versions") or ():
                    ref = record.get("file") if isinstance(record, dict) else None
                    if not ref:
                        continue
                    checked += 1
                    try:
                        path = _safe_relative(project_dir, str(ref))
                    except UnsafeBackupPath:
                        reasons.append(f"VERSION_REF_UNSAFE:{project_dir.name}:{resource_type}/{resource_id}")
                        continue
                    if not path.is_file():
                        reasons.append(
                            f"VERSION_FILE_MISSING:{project_dir.name}:{resource_type}/{resource_id}/v{record.get('version')}"
                        )
                    elif record.get("version") == current and path.suffix.lower() in PROBED_MEDIA_SUFFIXES:
                        selected_media.append(path)
    return checked, reasons, selected_media


async def _asset_references(conn: asyncpg.Connection, data_root: Path) -> tuple[int, list[str]]:
    checked = 0
    reasons: list[str] = []
    queries = (
        ("assets", "image_path"),
        ("assets", "audio_path"),
        ("asset_derivatives", "image_path"),
    )
    tables = set(await _user_tables(conn))
    for table, column in queries:
        if table not in tables:
            continue
        for row in await conn.fetch(f'SELECT id, "{column}" AS ref FROM "{table}" WHERE "{column}" IS NOT NULL'):
            checked += 1
            try:
                path = _safe_relative(data_root, str(row["ref"]))
            except UnsafeBackupPath:
                reasons.append(f"ASSET_REF_UNSAFE:{table}.{column}:{row['id']}")
                continue
            if not path.is_file():
                reasons.append(f"ASSET_FILE_MISSING:{table}.{column}:{row['id']}")
    return checked, reasons


async def _secret_residue(conn: asyncpg.Connection, manifest: DeploymentBackupManifest) -> list[str]:
    reasons: list[str] = []
    for table in manifest.sanitized_tables:
        for column, predicate in _SECRET_RESIDUE_PREDICATES.get(table.table, {}).items():
            if await _fetch_int(conn, f'SELECT count(*) FROM "{table.table}" WHERE {predicate}'):
                reasons.append(f"SECRET_RESIDUE:{table.table}.{column}")
    return reasons


async def verify_restored_deployment(
    *,
    backup_dir: Path,
    target_database_url: str,
    target_roots: Mapping[str, Path],
    media_probe: MediaProbe = ffprobe_media,
    measured_rpo_seconds: int | None = None,
    measured_rto_seconds: int | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> DeploymentBackupVerdict:
    """Verify a restored target against its set and record VERIFIED or REJECTED in the set's ledger."""
    manifest = await asyncio.to_thread(load_restorable_manifest, backup_dir)
    reasons: list[str] = []

    conn = await asyncpg.connect(libpq_url(target_database_url))
    try:
        head = str(await conn.fetchval("SELECT version_num FROM alembic_version"))
        if head != manifest.alembic_head:
            reasons.append("SCHEMA_MISMATCH")
        restored_counts = await _table_row_counts(conn)
        for table, expected in sorted(manifest.table_row_counts.items()):
            if restored_counts.get(table) != expected:
                reasons.append(f"ROW_COUNT_MISMATCH:{table}")
        reasons.extend(
            f"UNEXPECTED_TABLE:{table}" for table in sorted(set(restored_counts) - set(manifest.table_row_counts))
        )
        reasons.extend(await _secret_residue(conn, manifest))
        asset_checked, asset_reasons = await _asset_references(conn, target_roots[DATA_ROOT])
        reasons.extend(asset_reasons)
    finally:
        await conn.close()

    reasons.extend(await asyncio.to_thread(_verify_files, manifest, target_roots))
    project_checked, project_reasons, selected_media = await asyncio.to_thread(
        _project_references, target_roots[DATA_ROOT]
    )
    reasons.extend(project_reasons)
    probed = 0
    for path in selected_media:
        probed += 1
        if not await media_probe(path):
            reasons.append(f"MEDIA_UNPLAYABLE:{path.relative_to(target_roots[DATA_ROOT]).as_posix()}")

    state = BackupSetState.REJECTED if reasons else BackupSetState.VERIFIED
    verdict = DeploymentBackupVerdict(
        backup_set_id=manifest.backup_set_id,
        manifest_digest=manifest_digest(manifest),
        state=state,
        reason_codes=tuple(reasons),
        checked_table_count=len(manifest.table_row_counts),
        checked_file_count=len(manifest.files),
        checked_reference_count=asset_checked + project_checked,
        probed_media_count=probed,
        verified_at=clock(),
        measured_rpo_seconds=measured_rpo_seconds,
        measured_rto_seconds=measured_rto_seconds,
    )
    _write_json(backup_dir / VERDICT_FILENAME, verdict.model_dump(mode="json"))
    _write_state(
        backup_dir,
        state,
        now=verdict.verified_at,
        backup_set_id=manifest.backup_set_id,
        manifest_digest=verdict.manifest_digest,
        verdict_digest="sha256:" + canonical_json_digest(verdict.model_dump(mode="json")),
    )
    return verdict


__all__ = [
    "ACTIVE_TASK_STATUSES",
    "DATA_ROOT",
    "EXCLUDED_DATA_ENTRIES",
    "SANITIZED_TABLE_POLICY",
    "BackupIntegrityError",
    "BackupSetNotRestorable",
    "DeploymentBackupError",
    "ExternalToolFailed",
    "OfflineFenceViolation",
    "ReleaseIdentity",
    "RestoreTargetNotEmpty",
    "UnsafeBackupPath",
    "UnsupportedFileEntry",
    "create_deployment_backup",
    "ffprobe_media",
    "libpq_url",
    "load_restorable_manifest",
    "manifest_digest",
    "read_manifest",
    "read_state",
    "restore_deployment_backup",
    "verify_restored_deployment",
]
