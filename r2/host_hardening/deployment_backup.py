"""Whole-deployment backup sets under the V1 offline fence (H6, ADR-0078, ADR-0090).

A deployment backup set binds one PostgreSQL recovery point to every regular
file under the deployment's named data roots. It is captured only while the
operator has stopped the application and worker. Capture proves that fence
instead of trusting it: before and after the copy it requires zero other
client sessions on the database, no queued/running/cancelling Task, and
unchanged user-table write counters, relation storage and definitions, sequence
positions and file-tree fingerprint. Capture never writes to the source database.

Credential-bearing rows never enter the set. Their table data is excluded from
``pg_dump`` and captured separately as a binary COPY of the rows with credential
columns blanked (``SANITIZED_TABLE_POLICY``). Known secret files are excluded
and named in the manifest. Database passwords reach ``pg_dump``/``pg_restore``
through the child environment, never argv. After a restore the operator
re-enters provider credentials.

The set directory is the durable ledger of its own lifecycle. ``state.json``
moves ``PREPARING -> COMPLETE`` (or ``REJECTED`` when capture fails), bound to
the canonical digest of ``manifest.json``. ``verify`` records a target's
automated checks in ``verdicts/<restore_target_id>.json`` without touching the set's state;
``attest`` moves the set to ``VERIFIED`` only when those checks and the
no-provider Golden read/review/export evidence both passed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import asyncpg
from pydantic import ValidationError

from lib.artifact_manifest import MANIFEST_FILENAME as ARTIFACT_MANIFEST_FILENAME
from lib.artifact_manifest import ArtifactManifestError, ProjectArtifactManifestAdapter
from lib.content_digest import canonical_json_digest
from lib.json_io import atomic_write_bytes
from r2.contracts.host_hardening import (
    BackupFileEntry,
    BackupSetState,
    DeploymentBackupAttestation,
    DeploymentBackupManifest,
    DeploymentBackupVerdict,
    GoldenRestoreEvidence,
    OfflineFenceEvidence,
    SanitizedTableEntry,
)

DATA_ROOT = "data"
MANIFEST_FILENAME = "manifest.json"
STATE_FILENAME = "state.json"
VERDICTS_DIRNAME = "verdicts"
_RESTORE_TARGET_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
GOLDEN_EVIDENCE_FILENAME = "golden-evidence.json"
ATTESTATION_FILENAME = "attestation.json"
# The V1 Golden corpus is two products (factual and drama).
MIN_GOLDEN_PRODUCTS = 2
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

# File names never captured at any depth of any root: CLI credential stores (the
# Claude CLI keeps its OAuth credentials in ``.credentials.json``).
EXCLUDED_FILE_NAMES = (".credentials.json",)

# ``system_setting`` keys whose values are credentials: matched on the key's final
# segment so counters such as ``max_tokens`` stay intact.
_SECRET_SETTING_KEY_PATTERN = (
    "(^|_)(api_?key|apikey|secret|secret_key|access_key|private_key|password|passwd"
    "|credentials?|token|access_token|auth_token|refresh_token)$"
)

# table -> column -> SQL expression replacing that column in the captured rows.
# URLs keep scheme, host and path; every ``user:password@`` userinfo is removed.
# Userinfo never spans whitespace or ``/``, ``?``, ``#`` (RFC 3986 ends the
# authority there and requires them percent-encoded inside it), so prose after
# a URL and ``@`` in a query or fragment are left alone.
_STRIP_USERINFO = "regexp_replace({column}, '://[^/?#@\\s]*@', '://', 'g')"
_HAS_USERINFO = "{column} ~ '://[^/?#@\\s]*@'"

SANITIZED_TABLE_POLICY: Mapping[str, Mapping[str, str]] = {
    "provider_credential": {
        "api_key": "NULL",
        "access_key": "NULL",
        "secret_key": "NULL",
        "credentials_path": "NULL",
        "base_url": _STRIP_USERINFO.format(column="base_url"),
    },
    "agent_anthropic_credentials": {"api_key": "''", "base_url": _STRIP_USERINFO.format(column="base_url")},
    "custom_provider": {"api_key": "''", "base_url": _STRIP_USERINFO.format(column="base_url")},
    "provider_config": {
        "value": f"CASE WHEN is_secret THEN '' ELSE {_STRIP_USERINFO.format(column='value')} END",
    },
    "system_setting": {
        "value": (
            f"CASE WHEN key ~* '{_SECRET_SETTING_KEY_PATTERN}' THEN '' "
            f"ELSE {_STRIP_USERINFO.format(column='value')} END"
        ),
    },
}

# Post-restore proof that no credential value survived, per sanitized column.
_SECRET_RESIDUE_PREDICATES: Mapping[str, Mapping[str, str]] = {
    "provider_credential": {
        **{column: f"{column} IS NOT NULL" for column in ("api_key", "access_key", "secret_key", "credentials_path")},
        "base_url": _HAS_USERINFO.format(column="base_url"),
    },
    "agent_anthropic_credentials": {"api_key": "api_key <> ''", "base_url": _HAS_USERINFO.format(column="base_url")},
    "custom_provider": {"api_key": "api_key <> ''", "base_url": _HAS_USERINFO.format(column="base_url")},
    "provider_config": {"value": f"(is_secret AND value <> '') OR {_HAS_USERINFO.format(column='value')}"},
    "system_setting": {
        "value": f"(key ~* '{_SECRET_SETTING_KEY_PATTERN}' AND value <> '') OR {_HAS_USERINFO.format(column='value')}"
    },
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


class AttestationRejected(DeploymentBackupError):
    reason_code = "ATTESTATION_REJECTED"


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
    sequence_fingerprint: str
    relation_fingerprint: str


# --------------------------------------------------------------------------- paths


def libpq_url(database_url: str) -> str:
    """``pg_dump``/asyncpg understand ``postgresql://``, not SQLAlchemy's driver-qualified form."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def libpq_command_target(database_url: str) -> tuple[str, dict[str, str]]:
    """A password-free connection URL for a libpq tool's argv, plus the environment carrying the password.

    Command lines are visible to every local user (``ps``, ``/proc/<pid>/cmdline``);
    the password travels in the child's ``PGPASSWORD`` instead.
    """
    parts = urlsplit(libpq_url(database_url))
    # Other query parameters are kept byte-for-byte: libpq decodes them itself, and
    # re-encoding would change values such as ``options=-c%20...`` or a literal ``+``.
    kept: list[str] = []
    query_password: str | None = None
    for item in parts.query.split("&") if parts.query else ():
        name, _, value = item.partition("=")
        if unquote(name) == "password":
            query_password = unquote(value)
        else:
            kept.append(item)
    if query_password is not None:
        parts = parts._replace(query="&".join(kept))
    password = unquote(parts.password) if parts.password is not None else query_password
    if password is None:
        return urlunsplit(parts), {}
    if parts.password is None:
        return urlunsplit(parts), {"PGPASSWORD": password}
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    netloc = host if parts.port is None else f"{host}:{parts.port}"
    if parts.username:
        netloc = f"{parts.username}@{netloc}"
    return urlunsplit(parts._replace(netloc=netloc)), {"PGPASSWORD": password}


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
                    if entry.name not in EXCLUDED_FILE_NAMES:
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
    """Rows inserted, updated or deleted in user tables.

    Database-wide counters also count system-catalog writes, which autovacuum and
    autoanalyze make on their own (``pg_statistic``, ``pg_class``); user-table
    counters move only when data changes.
    """
    await conn.execute("SELECT pg_stat_clear_snapshot()")
    return await _fetch_int(conn, "SELECT coalesce(sum(n_tup_ins + n_tup_upd + n_tup_del), 0) FROM pg_stat_user_tables")


async def _relation_fingerprint(conn: asyncpg.Connection) -> str:
    """Digest of every relation's storage file and column definitions.

    ``TRUNCATE`` and table rewrites give a relation a new ``relfilenode`` without
    moving the row counters; DDL changes the column definitions. Autovacuum and
    ``ANALYZE`` change neither.
    """
    relations = await conn.fetch(
        "SELECT c.relname, c.relkind, c.relfilenode FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() ORDER BY c.relname"
    )
    columns = await conn.fetch(
        "SELECT table_name, ordinal_position, column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns WHERE table_schema = current_schema() "
        "ORDER BY table_name, ordinal_position"
    )
    return "sha256:" + canonical_json_digest(
        [[list(map(str, row.values())) for row in relations], [list(map(str, row.values())) for row in columns]]
    )


async def _sequence_fingerprint(conn: asyncpg.Connection) -> str:
    """Digest of every sequence's position: ``nextval``/``setval`` do not move the tuple counters."""
    rows = await conn.fetch(
        "SELECT schemaname, sequencename, last_value FROM pg_sequences ORDER BY schemaname, sequencename"
    )
    return "sha256:" + canonical_json_digest(
        [[str(row["schemaname"]), str(row["sequencename"]), row["last_value"]] for row in rows]
    )


async def _fence_snapshot(conn: asyncpg.Connection, roots: Mapping[str, Path]) -> _FenceSnapshot:
    return _FenceSnapshot(
        other_sessions=await _other_client_sessions(conn),
        active_tasks=await _active_tasks(conn),
        write_counter=await _write_counter(conn),
        sequence_fingerprint=await _sequence_fingerprint(conn),
        relation_fingerprint=await _relation_fingerprint(conn),
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


async def _run_tool(argv: list[str], *, extra_env: Mapping[str, str] | None = None) -> None:
    env = None if not extra_env else {**os.environ, **extra_env}
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
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
    try:
        state = json.loads((backup_dir / STATE_FILENAME).read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise BackupIntegrityError("state.json is not a readable ledger") from exc
    if not isinstance(state, dict):
        raise BackupIntegrityError("state.json is not a readable ledger")
    return state


def read_manifest(backup_dir: Path) -> DeploymentBackupManifest:
    """The set's manifest; a manifest of another schema version or shape is not restorable."""
    try:
        return DeploymentBackupManifest.model_validate_json(
            (backup_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
    except (ValidationError, UnicodeDecodeError) as exc:
        raise BackupSetNotRestorable("manifest.json is not a supported deployment backup manifest") from exc


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

    try:
        conn = await asyncpg.connect(libpq_url(database_url))
    except Exception:
        _write_state(
            backup_dir, BackupSetState.REJECTED, now=clock(), backup_set_id=backup_set_id, reason="DATABASE_UNAVAILABLE"
        )
        raise
    try:
        before = await _fence_snapshot(conn, roots)
        _assert_quiescent(before, phase="before capture")
        recovery_point = clock()

        dump_path = backup_dir / DUMP_FILENAME
        exclude_args = [f"--exclude-table-data={table}" for table in sorted(SANITIZED_TABLE_POLICY)]
        dump_target, dump_env = libpq_command_target(database_url)
        await _run_tool(
            [
                pg_dump_path,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--no-password",
                *exclude_args,
                f"--file={dump_path}",
                dump_target,
            ],
            extra_env=dump_env,
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
        if after.relation_fingerprint != before.relation_fingerprint:
            raise OfflineFenceViolation("a table was truncated, rewritten or altered while capturing")
        if after.sequence_fingerprint != before.sequence_fingerprint:
            raise OfflineFenceViolation("a sequence advanced while capturing")
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
            excluded_file_names=EXCLUDED_FILE_NAMES,
            files=tuple(files),
            configuration=dict(identity.configuration),
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
                sequence_fingerprint_before=before.sequence_fingerprint,
                sequence_fingerprint_after=after.sequence_fingerprint,
                relation_fingerprint_before=before.relation_fingerprint,
                relation_fingerprint_after=after.relation_fingerprint,
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
    if state.get("state") == BackupSetState.VERIFIED.value:
        _verify_attestation_record(backup_dir, manifest, state)
    _verify_backup_payload(manifest, backup_dir)
    return manifest


def _verdict_path(backup_dir: Path, restore_target_id: str) -> Path:
    if not _RESTORE_TARGET_ID_RE.fullmatch(restore_target_id):
        raise UnsafeBackupPath("restore target id must be 1-128 of [A-Za-z0-9._-], starting alphanumeric")
    return backup_dir / VERDICTS_DIRNAME / f"{restore_target_id}.json"


def _file_digest_of(path: Path, model: type[DeploymentBackupVerdict] | type[GoldenRestoreEvidence]) -> str | None:
    if not path.is_file():
        return None
    try:
        return _digest(model.model_validate_json(path.read_text(encoding="utf-8")))
    except (ValidationError, UnicodeDecodeError) as exc:
        raise BackupIntegrityError(f"{path.name} is not a valid record") from exc


def _verify_attestation_record(backup_dir: Path, manifest: DeploymentBackupManifest, state: Mapping[str, Any]) -> None:
    """A VERIFIED state must be backed by the attestation it names, and by the verdict
    and Golden evidence that attestation names, for this manifest."""
    path = backup_dir / ATTESTATION_FILENAME
    if not path.is_file():
        raise BackupIntegrityError("state is VERIFIED but the set has no attestation")
    try:
        attestation = DeploymentBackupAttestation.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValidationError, UnicodeDecodeError) as exc:
        raise BackupIntegrityError("attestation.json is not a valid record") from exc
    recorded = "sha256:" + canonical_json_digest(attestation.model_dump(mode="json"))
    if recorded != state.get("attestation_digest") or attestation.manifest_digest != manifest_digest(manifest):
        raise BackupIntegrityError("the attestation does not match the VERIFIED state")
    verdict_digest = _file_digest_of(_verdict_path(backup_dir, attestation.restore_target_id), DeploymentBackupVerdict)
    evidence_digest = _file_digest_of(backup_dir / GOLDEN_EVIDENCE_FILENAME, GoldenRestoreEvidence)
    if verdict_digest != attestation.verdict_digest or evidence_digest != attestation.golden_evidence_digest:
        raise BackupIntegrityError("the attested verdict or Golden evidence has changed")


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
        restore_target, restore_env = libpq_command_target(target_database_url)
        target = f"--dbname={restore_target}"
        await _run_tool([*base, "--section=pre-data", target, dump], extra_env=restore_env)
        await _run_tool([*base, "--section=data", target, dump], extra_env=restore_env)
        for table in manifest.sanitized_tables:
            columns = await _table_columns(conn, table.table)
            await conn.copy_to_table(
                table.table, source=str(backup_dir / table.data_ref), columns=columns, format="binary"
            )
        await _run_tool([*base, "--section=post-data", target, dump], extra_env=restore_env)
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


def _artifact_manifest_references(project_dir: Path) -> tuple[int, list[str]]:
    """Every Artifact Manifest entry of one project must point to an existing file."""
    if not (project_dir / ARTIFACT_MANIFEST_FILENAME).is_file():
        return 0, []
    try:
        entries = ProjectArtifactManifestAdapter(project_dir).snapshot_entries()
    except ArtifactManifestError:
        return 0, [f"ARTIFACT_MANIFEST_INVALID:{project_dir.name}"]
    reasons: list[str] = []
    for entry in entries.values():
        try:
            path = _safe_relative(project_dir, entry.artifact_path)
        except UnsafeBackupPath:
            reasons.append(f"ARTIFACT_REF_UNSAFE:{project_dir.name}")
            continue
        if not path.is_file():
            reasons.append(f"ARTIFACT_FILE_MISSING:{project_dir.name}:{entry.artifact_path}")
    return len(entries), reasons


def _project_references(data_root: Path) -> tuple[int, list[str], list[Path]]:
    """Check every project's metadata, Artifact Manifest and version history resolves.

    A resource's ``current_version`` (its selected master) must name an existing
    version record whose file exists. Returns (checked reference count, reason
    codes, selected media to probe).
    """
    checked = 0
    reasons: list[str] = []
    selected_media: list[Path] = []
    for project_dir in sorted(p for p in data_root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        project_json = project_dir / "project.json"
        if project_json.is_file():
            checked += 1
            try:
                if not isinstance(json.loads(project_json.read_text(encoding="utf-8")), dict):
                    reasons.append(f"PROJECT_JSON_INVALID:{project_dir.name}")
            except ValueError:
                reasons.append(f"PROJECT_JSON_INVALID:{project_dir.name}")
        artifact_checked, artifact_reasons = _artifact_manifest_references(project_dir)
        checked += artifact_checked
        reasons.extend(artifact_reasons)
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
                label = f"{project_dir.name}:{resource_type}/{resource_id}"
                current = resource.get("current_version")
                records = [record for record in resource.get("versions") or () if isinstance(record, dict)]
                current_records = [record for record in records if record.get("version") == current]
                if current and not current_records:
                    checked += 1
                    reasons.append(f"CURRENT_VERSION_MISSING:{label}/v{current}")
                elif current and not any(record.get("file") for record in current_records):
                    checked += 1
                    reasons.append(f"CURRENT_VERSION_FILE_MISSING:{label}/v{current}")
                for record in records:
                    ref = record.get("file")
                    if not ref:
                        continue
                    checked += 1
                    try:
                        path = _safe_relative(project_dir, str(ref))
                    except UnsafeBackupPath:
                        reasons.append(f"VERSION_REF_UNSAFE:{label}")
                        continue
                    if not path.is_file():
                        reasons.append(f"VERSION_FILE_MISSING:{label}/v{record.get('version')}")
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
    restore_target_id: str,
    target_release_git_sha: str,
    media_probe: MediaProbe = ffprobe_media,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> DeploymentBackupVerdict:
    """Run the automated checks on one restored target and record them in its verdict file.

    The set's lifecycle state is not changed: a failing target says nothing
    about the set, and passing checks alone are not VERIFIED (see
    ``attest_deployment_restore``).
    """
    verdict_path = _verdict_path(backup_dir, restore_target_id)
    manifest = await asyncio.to_thread(load_restorable_manifest, backup_dir)
    if read_state(backup_dir).get("state") == BackupSetState.VERIFIED.value:
        attested = DeploymentBackupAttestation.model_validate_json(
            (backup_dir / ATTESTATION_FILENAME).read_text(encoding="utf-8")
        )
        if attested.restore_target_id.casefold() == restore_target_id.casefold():
            raise UnsafeBackupPath("this restore target is already attested; verify a new target under a new id")
    reasons: list[str] = []
    if target_release_git_sha != manifest.release_git_sha:
        reasons.append("RELEASE_MISMATCH")

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

    verdict = DeploymentBackupVerdict(
        backup_set_id=manifest.backup_set_id,
        manifest_digest=manifest_digest(manifest),
        restore_target_id=restore_target_id,
        target_release_git_sha=target_release_git_sha,
        checks_passed=not reasons,
        reason_codes=tuple(reasons),
        checked_table_count=len(manifest.table_row_counts),
        checked_file_count=len(manifest.files),
        checked_reference_count=asset_checked + project_checked,
        probed_media_count=probed,
        checked_at=clock(),
    )
    verdict_path.parent.mkdir(exist_ok=True)
    _write_json(verdict_path, verdict.model_dump(mode="json"))
    return verdict


def _captured_projects(manifest: DeploymentBackupManifest) -> set[str]:
    return {
        entry.path.split("/", 1)[0]
        for entry in manifest.files
        if entry.root == DATA_ROOT and entry.path.count("/") == 1 and entry.path.endswith("/project.json")
    }


def _digest(model: DeploymentBackupVerdict | GoldenRestoreEvidence) -> str:
    return "sha256:" + canonical_json_digest(model.model_dump(mode="json"))


def attest_deployment_restore(
    *,
    backup_dir: Path,
    golden_evidence: GoldenRestoreEvidence,
    measured_rpo_seconds: int,
    measured_rto_seconds: int,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> DeploymentBackupAttestation:
    """Move a set to VERIFIED once its restore checks and Golden evidence both passed.

    Spec §8 step 7 marks a set VERIFIED only after clean-target restore, reference
    and media checks *and* the no-provider Golden A/B read/review/export pass,
    with measured RPO/RTO. Anything missing or mismatched raises
    ``AttestationRejected`` and leaves the set's state unchanged.
    """
    manifest = load_restorable_manifest(backup_dir)
    if read_state(backup_dir).get("state") == BackupSetState.VERIFIED.value:
        # Attesting writes three files before the state; overwriting an existing
        # attestation could leave them mismatched after a crash, so a set is
        # attested once.
        raise AttestationRejected("this set is already VERIFIED")
    digest = manifest_digest(manifest)
    verdict_path = _verdict_path(backup_dir, golden_evidence.restore_target_id)
    if not verdict_path.is_file():
        raise AttestationRejected("no restore verdict has been recorded for this target")
    try:
        verdict = DeploymentBackupVerdict.model_validate_json(verdict_path.read_text(encoding="utf-8"))
    except (ValidationError, UnicodeDecodeError) as exc:
        raise AttestationRejected("the recorded restore verdict is not a valid record") from exc
    if verdict.manifest_digest != digest or not verdict.checks_passed:
        raise AttestationRejected("the recorded restore verdict did not pass for this manifest")
    if golden_evidence.backup_set_id != manifest.backup_set_id or golden_evidence.manifest_digest != digest:
        raise AttestationRejected("Golden evidence belongs to another backup set")
    if golden_evidence.restore_target_id != verdict.restore_target_id:
        raise AttestationRejected("Golden evidence and the restore verdict describe different targets")
    product_names = [product.project_name for product in golden_evidence.products]
    if (
        not golden_evidence.passed
        or len(set(product_names)) < MIN_GOLDEN_PRODUCTS
        or len(set(product_names)) != len(product_names)
        or not all(product.reviewed for product in golden_evidence.products)
    ):
        raise AttestationRejected("Golden read/review/export did not pass for enough distinct products")
    unknown = sorted(set(product_names) - _captured_projects(manifest))
    if unknown:
        raise AttestationRejected(f"Golden products are not projects of this set: {unknown}")

    attestation = DeploymentBackupAttestation(
        backup_set_id=manifest.backup_set_id,
        manifest_digest=digest,
        restore_target_id=verdict.restore_target_id,
        verdict_digest=_digest(verdict),
        golden_evidence_digest=_digest(golden_evidence),
        measured_rpo_seconds=measured_rpo_seconds,
        measured_rto_seconds=measured_rto_seconds,
        verified_at=clock(),
    )
    _write_json(backup_dir / GOLDEN_EVIDENCE_FILENAME, golden_evidence.model_dump(mode="json"))
    _write_json(backup_dir / ATTESTATION_FILENAME, attestation.model_dump(mode="json"))
    _write_state(
        backup_dir,
        BackupSetState.VERIFIED,
        now=attestation.verified_at,
        backup_set_id=manifest.backup_set_id,
        manifest_digest=digest,
        attestation_digest="sha256:" + canonical_json_digest(attestation.model_dump(mode="json")),
    )
    return attestation


__all__ = [
    "ACTIVE_TASK_STATUSES",
    "DATA_ROOT",
    "EXCLUDED_DATA_ENTRIES",
    "EXCLUDED_FILE_NAMES",
    "MIN_GOLDEN_PRODUCTS",
    "SANITIZED_TABLE_POLICY",
    "AttestationRejected",
    "BackupIntegrityError",
    "BackupSetNotRestorable",
    "DeploymentBackupError",
    "ExternalToolFailed",
    "OfflineFenceViolation",
    "ReleaseIdentity",
    "RestoreTargetNotEmpty",
    "UnsafeBackupPath",
    "UnsupportedFileEntry",
    "attest_deployment_restore",
    "create_deployment_backup",
    "ffprobe_media",
    "libpq_command_target",
    "libpq_url",
    "load_restorable_manifest",
    "manifest_digest",
    "read_manifest",
    "read_state",
    "restore_deployment_backup",
    "verify_restored_deployment",
]
