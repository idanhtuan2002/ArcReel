"""Runtime route qualifications: the live level of ADR-0091's two-level qualification.

A route is ``QUALIFIED`` in a release deployment only when both levels hold for the
running adapter version:

- **Adapter level.** The static capability registry shipped with the release says the
  adapter was verified offline. This applies to the async video submit families, whose
  profiles carry that status. Synchronous routes have no static profile; for them this
  level is the generic paid-route invariants (no resend after an ambiguous outcome,
  destination guard, budget before submit), which the test suite proves for every
  adapter.
- **Route level.** An operator-run canary succeeded for the exact route and model under
  the current adapter version. The canary is recorded here with its evidence digest and
  an expiry.

Records live in the deployment data root (``.route_qualifications/``), so a backup set
carries them. A record is ignored when it has expired, when the adapter version changed
in a release upgrade, or when its evidence file no longer matches the recorded digest.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lib.app_data_dir import app_data_dir
from lib.json_io import atomic_write_bytes, atomic_write_json
from r2.contracts.host_hardening import ProviderQualificationStatus
from r2.host_hardening.paid_routes import PaidRoute, set_qualification_lookup
from r2.host_hardening.provider_capabilities import ProviderCapabilityError, capability_qualification_status
from r2.host_hardening.route_inventory import (
    BUILTIN_VIDEO_SUBMIT_PROVIDER,
    CUSTOM_PROVIDER_FAMILY,
    HOST_VIDEO_ADAPTER_VERSION,
    PAID_ASYNC_SUBMIT_FAMILIES,
)

logger = logging.getLogger(__name__)

QUALIFICATIONS_DIRNAME = ".route_qualifications"
_RECORDS_FILE = "qualifications.json"
_EVIDENCE_DIR = "evidence"

#: Adapter version per route class. Bumping one in a release invalidates that class's runtime
#: qualifications, so the operator re-runs the canaries after the upgrade.
ROUTE_ADAPTER_VERSIONS: dict[str, str] = {
    "media:video": HOST_VIDEO_ADAPTER_VERSION,
    "media:image": "host-media-v1",
    "media:text": "host-media-v1",
    "media:audio": "host-media-v1",
    "agent": "agent-sdk-v1",
    "trial_run": "declarative-trial-v1",
}

_OFFLINE_OR_BETTER = frozenset(
    {
        ProviderQualificationStatus.OFFLINE_VERIFIED,
        ProviderQualificationStatus.SANDBOX_VERIFIED,
        ProviderQualificationStatus.QUALIFIED,
    }
)


def adapter_version_for(route: PaidRoute) -> str:
    if route.kind in ("media", "custom_media"):
        return ROUTE_ADAPTER_VERSIONS[f"media:{route.media_type}"]
    return ROUTE_ADAPTER_VERSIONS[route.kind]


@dataclass(frozen=True)
class RouteQualification:
    route_ref: str
    model_id: str
    binding: str
    adapter_version: str
    qualified_at: str
    expires_at: str
    evidence_path: str
    evidence_digest: str
    cost_record_ref: str | None
    recorded_by: str


def qualifications_dir(root: Path | None = None) -> Path:
    return (root or app_data_dir()) / QUALIFICATIONS_DIRNAME


#: Route classes that cannot be qualified: the Agent's spend is recorded after the fact, so it has
#: no budget-before-submit (ADR-0091 invariant 1), and trial runs are a setup tool.
UNQUALIFIABLE_ROUTE_KINDS = frozenset({"agent", "trial_run"})


def load_qualifications(root: Path | None = None) -> list[RouteQualification]:
    """Current records; an unreadable or malformed records file counts as no qualifications (fail closed)."""
    path = qualifications_dir(root) / _RECORDS_FILE
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [RouteQualification(**item) for item in raw.get("qualifications", [])]
    except (OSError, ValueError, TypeError, AttributeError):
        logger.error("route qualification records at %s are unreadable; treating every route as unqualified", path)
        return []


@contextmanager
def _exclusive(directory: Path, *, timeout: float = 30.0) -> Generator[None]:
    """Cross-process exclusion for the records read-modify-write, via an ``O_EXCL`` lock file."""
    lock = directory / ".lock"
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"route qualification store is locked: {lock}") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def record_qualification(
    *,
    route: PaidRoute,
    model_id: str,
    binding: str,
    evidence: dict[str, Any],
    expires_at: datetime,
    cost_record_ref: str | None,
    recorded_by: str,
    now: datetime,
    root: Path | None = None,
) -> RouteQualification:
    """Write the canary evidence and replace any earlier record for the same route and model."""
    if route.kind in UNQUALIFIABLE_ROUTE_KINDS:
        raise ValueError(f"route class {route.kind!r} cannot be qualified")
    directory = qualifications_dir(root)
    evidence_dir = directory / _EVIDENCE_DIR
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_bytes = json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode("utf-8")
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    safe_ref = route.ref.replace(":", "_").replace("/", "_")
    evidence_path = evidence_dir / f"{safe_ref}__{model_id.replace('/', '_')}__{stamp}.json"
    atomic_write_bytes(evidence_path, evidence_bytes)
    record = RouteQualification(
        route_ref=route.ref,
        model_id=model_id,
        binding=binding,
        adapter_version=adapter_version_for(route),
        qualified_at=now.isoformat(),
        expires_at=expires_at.isoformat(),
        evidence_path=evidence_path.relative_to(directory).as_posix(),
        evidence_digest=_digest(evidence_bytes),
        cost_record_ref=cost_record_ref,
        recorded_by=recorded_by,
    )
    with _exclusive(directory):
        kept = [q for q in load_qualifications(root) if (q.route_ref, q.model_id) != (route.ref, model_id)]
        atomic_write_json(
            directory / _RECORDS_FILE,
            {"schema_version": 1, "qualifications": [asdict(q) for q in [*kept, record]]},
        )
    return record


def _adapter_level_holds(route: PaidRoute, now: datetime) -> bool:
    """Async video routes also need their shipped adapter profile verified offline."""
    if route.media_type != "video":
        return True
    if route.kind == "custom_media":
        submit_provider = CUSTOM_PROVIDER_FAMILY
    else:
        submit_provider = BUILTIN_VIDEO_SUBMIT_PROVIDER.get(route.provider_id or "")
        if submit_provider is None:
            return False
    refs = [f.capability_profile_ref for f in PAID_ASYNC_SUBMIT_FAMILIES if f.key.provider_id == submit_provider]
    if not refs:
        return False
    try:
        return all(capability_qualification_status(ref, now=now) in _OFFLINE_OR_BETTER for ref in refs)
    except ProviderCapabilityError:
        return False


def is_route_qualified(
    route: PaidRoute,
    model_id: str | None,
    binding: str | None,
    *,
    now: datetime,
    root: Path | None = None,
) -> bool:
    """The single registry read for release gates: static adapter level plus runtime route record."""
    if route.kind in UNQUALIFIABLE_ROUTE_KINDS or binding is None:
        return False
    if not _adapter_level_holds(route, now):
        return False
    directory = qualifications_dir(root)
    for record in load_qualifications(root):
        if (record.route_ref, record.model_id, record.binding) != (route.ref, model_id or "", binding):
            continue
        if record.adapter_version != adapter_version_for(route):
            continue
        if datetime.fromisoformat(record.expires_at) <= now:
            continue
        evidence = directory / record.evidence_path
        if not evidence.is_file() or _digest(evidence.read_bytes()) != record.evidence_digest:
            continue
        return True
    return False


def install_runtime_qualification_lookup(root: Path | None = None) -> None:
    """Make release-mode gates consult the runtime records (called at app startup)."""
    set_qualification_lookup(
        lambda route, model, binding: is_route_qualified(route, model, binding, now=datetime.now(UTC), root=root)
    )


__all__ = [
    "QUALIFICATIONS_DIRNAME",
    "ROUTE_ADAPTER_VERSIONS",
    "UNQUALIFIABLE_ROUTE_KINDS",
    "RouteQualification",
    "adapter_version_for",
    "install_runtime_qualification_lookup",
    "is_route_qualified",
    "load_qualifications",
    "qualifications_dir",
    "record_qualification",
]
