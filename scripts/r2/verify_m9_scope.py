"""Read-only M9-A baseline, scope and disposable-environment gate.

ARCREEL_M9_DONOR_ROOT names the offline cache of <donor-name>.git repositories.
ARCREEL_M9_ENVIRONMENT_EVIDENCE names the disposable-container/test-grant proof;
DATABASE_URL must match its actual localhost Docker port. The live grant is
revalidated through the accepted reader. This command never provisions a target,
imports grants, fetches donors or writes a receipt.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from r2.governance.grant_transition import GrantScopeV1
from scripts.r2.verify_m8_scope import symbol_seam
from scripts.r2.verify_m9_prerequisites import (
    LOAD_ERRORS,
    M8_ACCEPTANCE,
    M8_PATH,
    M9_PATH,
    SPONSOR_ACCEPTANCE,
    GitPrerequisiteReader,
    loads_unique_json,
    verify_repository,
    verify_sponsor_design,
)
from server.services.governance_grants import CurrentShowrunnerGrantReader

BASE = "39b9c5dab5d0fd56cf52bf65e95355437cb1023b"
BRANCH = "impl/r2-m9a-opportunity-foundation"
PREDECESSOR = "918c4a0e0001"
CONTRACT = "docs/r2/evidence/R2_M9_EXECUTION_CONTRACT_2026-09-14.json"
PACKET = "docs/superpowers/plans/2026-09-14-r2-m9a-foundation-cohort-profiles.md"
BASELINE = "docs/r2/evidence/R2_M9_BASELINE.json"
SCHEMA = "docs/r2/evidence/schemas/R2_M9_BASELINE.schema.json"
SEAMS = {
    "r2/contracts/advanced_creative.py": (
        "r2.contracts.advanced_creative:M8ContractModel",
        "r2.contracts.advanced_creative:CanonicalJsonObject",
    ),
    "r2/advanced_creative/digests.py": (
        "r2.advanced_creative.digests:canonical_json_bytes",
        "r2.advanced_creative.digests:digest_canonical",
    ),
    "r2/advanced_creative/exploration.py": ("r2.advanced_creative.exploration:ExplorationService.append_revision",),
    "lib/db/repositories/learning.py": ("lib.db.repositories.learning:LearningObservationRepository.list_as_of",),
    "r2/contracts/factual.py": ("r2.contracts.factual:SourceRecord", "r2.contracts.factual:EvidenceRecord"),
    "server/services/governance_grants.py": (
        "server.services.governance_grants:CurrentShowrunnerGrantReader.require_current_locked",
    ),
}


@dataclass(frozen=True)
class ScopeObservation:
    design_errors: tuple[str, ...]
    m8_errors: tuple[str, ...]
    prerequisite_errors: tuple[str, ...]
    branch: str
    base_is_ancestor: bool
    dirty_paths: tuple[str, ...]
    outside_paths: tuple[str, ...]
    collisions: tuple[str, ...]
    heads: tuple[str, ...]
    seam_errors: tuple[str, ...]
    donor_errors: tuple[str, ...]
    environment_errors: tuple[str, ...]
    baseline_errors: tuple[str, ...]


def evaluate_scope(observed: ScopeObservation) -> list[str]:
    required = list(observed.prerequisite_errors + observed.environment_errors + observed.baseline_errors)
    if observed.branch != BRANCH:
        required.append("worktree is not the exact M9-A implementation branch")
    if not observed.base_is_ancestor:
        required.append("HEAD does not descend from the accepted P0 base")
    if observed.dirty_paths:
        required.append("worktree is dirty")
    seams = list(observed.seam_errors)
    if observed.outside_paths:
        seams.append("committed changes exceed the accepted owned paths")
    if observed.collisions:
        seams.append("a create-owned path already exists at the accepted base")
    if observed.heads not in ((PREDECESSOR,), ("9a9c4a0e0001",)):
        seams.append("migration graph does not have the exact permitted singleton head")
    return [
        f"{code}: " + detail.removeprefix(f"{code}: ")
        for code, details in (
            ("M9_DESIGN_NOT_ACCEPTED", observed.design_errors),
            ("M9_M8_IMPLEMENTATION_NOT_ACCEPTED", observed.m8_errors),
            ("M9_REQUIRED_EVIDENCE_MISSING", required),
            ("POST_M8_BASE_SEAM_CHANGED", seams),
            ("M9_DONOR_PARITY_INCOMPLETE", observed.donor_errors),
        )
        for detail in details
    ]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def owned_paths(packet: bytes) -> tuple[list[str], list[str]]:
    section = packet.decode().split("## Exact owned file map\n", 1)[1].split("\n## Fixed HTTP surface", 1)[0]
    creates, modifies = section.split("Modify only when exact accepted integration requires it:", 1)

    def paths(value: str) -> list[str]:
        return [
            (
                "tests/unit/r2/opportunity/test_m9_opportunity_boundaries.py"
                if path == "tests/architecture/test_m9_opportunity_boundaries.py"
                else path
            )
            for line in value.splitlines()
            if line.startswith("- `")
            for path in re.findall(r"`([^`]+)`", line)
            if "." in path
        ]

    new = paths(creates)
    return sorted(new + paths(modifies)), sorted(new)


def baseline_problems(repo: Path, baseline: dict[str, Any], source: GitPrerequisiteReader) -> list[str]:
    schema = loads_unique_json((repo / SCHEMA).read_bytes())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = [f"baseline schema: {error.message}" for error in validator.iter_errors(baseline)]
    if errors:
        return errors
    if (baseline["base_head"], baseline["branch"], baseline["alembic_predecessor"]) != (BASE, BRANCH, PREDECESSOR):
        errors.append("baseline substitutes an accepted base, branch or migration predecessor")
    allowed, creates = owned_paths(source.blob(BASE, PACKET))
    if (baseline["scope_allowlist"], baseline["create_paths"]) != (allowed, creates):
        errors.append("baseline owned paths differ from the accepted packet")
    design = loads_unique_json(source.blob(SPONSOR_ACCEPTANCE, M9_PATH))
    if set(baseline["documents"]) != set(design["artifacts"]):
        errors.append("baseline document inventory differs from accepted design")
    errors.extend(
        f"baseline document hash mismatch: {path}"
        for path, digest in baseline["documents"].items()
        if _sha(source.blob(BASE, path)) != digest
    )
    for name, ref, path in (
        ("m8_acceptance", M8_ACCEPTANCE, M8_PATH),
        ("m9_design_acceptance", SPONSOR_ACCEPTANCE, M9_PATH),
    ):
        if baseline[name] != {"path": path, "acceptance_commit": ref, "sha256": _sha(source.blob(ref, path))}:
            errors.append(f"baseline {name} binding differs")
    if source.migration_metadata(BASE) != ((PREDECESSOR,), baseline["revision_graph_digest"]):
        errors.append("baseline migration graph digest differs")
    if set(baseline["seams"]) != set(SEAMS):
        errors.append("baseline seam inventory differs")
    for path, entry in baseline["seams"].items():
        if _sha(source.blob(M8_ACCEPTANCE, path)) != entry["sha256"]:
            errors.append(f"baseline seam hash differs from accepted M8: {path}")
        if set(entry["symbols"]) != set(SEAMS.get(path, ())):
            errors.append(f"baseline symbol inventory differs: {path}")
    return errors


def donor_problems(baseline: dict[str, Any], contract: Mapping[str, Any], root: Path | None) -> list[str]:
    expected = {row["name"]: row for row in contract["donors"]}
    actual = {row["name"]: row for row in baseline["donors"]}
    if len(actual) != len(baseline["donors"]) or set(actual) != set(expected):
        return ["donor inventory does not exactly match the accepted contract"]
    errors = []
    for name, row in actual.items():
        pin = expected[name]
        if row["commit"] != pin["commit"] or set(row["files"]) != set(pin["selected_paths"]):
            errors.append(f"donor pin or selected paths differ: {name}")
            continue
        for path, digest in row["files"].items():
            if root is None:
                errors.append(f"donor cache unavailable: {name}")
                break
            result = subprocess.run(
                ["git", "-C", str(root / (name + ".git")), "show", f"{pin['commit']}:{path}"],
                capture_output=True,
                check=False,
                env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
            )
            if result.returncode or _sha(result.stdout) != digest:
                errors.append(f"donor pinned blob unavailable or hash changed: {name}/{path}")
    return errors


async def _read_environment(proof: dict[str, Any], database_url: str) -> None:
    url = make_url(database_url)
    if url.query:
        raise ValueError("database URL differs from the attested localhost container")
    container = json.loads(
        await asyncio.to_thread(
            subprocess.check_output,
            [
                "docker",
                "inspect",
                "--format",
                '{"id":"{{.Id}}","labels":{{json .Config.Labels}},"ports":{{json .NetworkSettings.Ports}}}',
                proof["container_name"],
            ],
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    )
    ports = container["ports"]["5432/tcp"]
    if (
        container["id"] != proof["container_id"]
        or container["labels"].get("arcreel.disposable") != "true"
        or container["labels"].get("arcreel.task") != "m9a"
    ):
        raise ValueError("not the attested disposable M9-A container")
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host != "127.0.0.1"
        or url.database != proof["database"]
        or not any(row["HostIp"] == url.host and int(row["HostPort"]) == url.port for row in ports)
    ):
        raise ValueError("database URL differs from the attested localhost container")
    key = bytes.fromhex(proof["grant_public_key_hex"])
    if _sha(key) != proof["grant_public_key_sha256"]:
        raise ValueError("fixture public key differs")
    engine = create_async_engine(
        database_url, connect_args={"timeout": 5, "server_settings": {"statement_timeout": "5000"}}, pool_pre_ping=True
    )
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            if await session.scalar(text("select current_database()")) != proof["database"]:
                raise ValueError("wrong database")
            if await session.scalar(text("select version_num from alembic_version")) not in (
                PREDECESSOR,
                "9a9c4a0e0001",
            ):
                raise ValueError("wrong live migration head")
            reader = CurrentShowrunnerGrantReader(key_id="test-governance-key", public_key=key)
            event = await reader.require_current_locked(session, scope=GrantScopeV1(**proof["scope"]))
            if event.event_digest != proof["grant_event_digest"]:
                raise ValueError("current grant differs from the attested fixture")
    finally:
        await engine.dispose()


def environment_problems() -> list[str]:
    try:
        path = os.environ.get("ARCREEL_M9_ENVIRONMENT_EVIDENCE")
        url = os.environ.get("DATABASE_URL")
        if not path or not url:
            return ["attested disposable target and current custodian grant inputs are missing"]
        proof = loads_unique_json(Path(path).read_bytes())
        if proof["authority_boundary"] != "DISPOSABLE_TEST_FIXTURE_ONLY" or proof["base_head"] != BASE:
            return ["environment evidence does not bind this test-only prerequisite base"]
        asyncio.run(_read_environment(proof, url))
        return []
    except Exception:
        return ["disposable target or current scoped custodian grant verification failed"]


def verify_m9_scope(repo: Path, contract: Mapping[str, object]) -> list[str]:
    try:
        source = GitPrerequisiteReader(repo)
        head = source.head()
        accepted_contract = loads_unique_json(source.blob(BASE, CONTRACT))
        if dict(contract) != accepted_contract:
            return ["M9_DESIGN_NOT_ACCEPTED: execution contract differs from the accepted Git object"]
        design_errors = tuple(verify_repository(repo, design_only=True))
        if any(error.startswith("M9_REQUIRED_EVIDENCE_MISSING:") for error in design_errors):
            design_errors = tuple(verify_sponsor_design(source, current_ref=head))
        m8_errors = ()
        try:
            if (repo / M8_PATH).read_bytes() != source.blob(M8_ACCEPTANCE, M8_PATH):
                m8_errors = ("M8 acceptance differs from its accepted object",)
        except LOAD_ERRORS:
            m8_errors = ("M8 acceptance is missing",)
        try:
            baseline = loads_unique_json((repo / BASELINE).read_bytes())
        except LOAD_ERRORS:
            return [
                *design_errors,
                *(f"M9_M8_IMPLEMENTATION_NOT_ACCEPTED: {error}" for error in m8_errors),
                "M9_REQUIRED_EVIDENCE_MISSING: baseline is unavailable or malformed",
            ]
        try:
            baseline_errors = baseline_problems(repo, baseline, source)
        except SchemaError:
            baseline_errors = ["baseline schema is invalid"]
        if baseline_errors:
            return evaluate_scope(
                ScopeObservation(
                    design_errors,
                    m8_errors,
                    (),
                    BRANCH,
                    True,
                    (),
                    (),
                    (),
                    (PREDECESSOR,),
                    (),
                    (),
                    (),
                    tuple(baseline_errors),
                )
            )
        allowed, creates = owned_paths(source.blob(BASE, PACKET))
        changed = source._run("diff", "--name-only", f"{BASE}..{head}").decode().splitlines()
        collisions = [
            path
            for path in creates
            if subprocess.run(
                ["git", "cat-file", "-e", f"{BASE}:{path}"], cwd=repo, capture_output=True, check=False
            ).returncode
            == 0
        ]
        seam_errors = []
        for path, entry in baseline["seams"].items():
            if _sha((repo / path).read_bytes()) != entry["sha256"]:
                seam_errors.append(f"accepted seam source differs: {path}")
            for name, expected in entry["symbols"].items():
                observed = symbol_seam(repo, name, path)
                if observed is None or {"signature": observed.signature, "sha256": observed.sha256} != expected:
                    seam_errors.append(f"accepted symbol differs: {name}")
        root = os.environ.get("ARCREEL_M9_DONOR_ROOT")
        result = evaluate_scope(
            ScopeObservation(
                design_errors,
                m8_errors,
                tuple(verify_repository(repo, acceptance_ref=BASE)),
                source._run("branch", "--show-current").decode().strip(),
                source.is_ancestor(BASE, head),
                tuple(source.dirty_paths()),
                tuple(path for path in changed if path not in allowed),
                tuple(collisions),
                source.migration_metadata(head)[0],
                tuple(seam_errors),
                tuple(donor_problems(baseline, accepted_contract, Path(root) if root else None)),
                tuple(environment_problems()),
                (),
            )
        )
        if source.head() != head or source.dirty_paths():
            result.append("M9_REQUIRED_EVIDENCE_MISSING: worktree changed or remained dirty during verification")
        return result
    except (*LOAD_ERRORS, IndexError):
        return ["M9_DESIGN_NOT_ACCEPTED: required Git-bound scope evidence is unavailable or malformed"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    args = parser.parse_args()
    try:
        errors = verify_m9_scope(Path.cwd(), loads_unique_json(args.contract.read_bytes()))
    except LOAD_ERRORS:
        errors = ["M9_DESIGN_NOT_ACCEPTED: execution contract is unavailable or malformed"]
    for error in errors:
        print(error)
    if not errors:
        print("M9_BASELINE_OK: Git lineage, owned scope, seams, donor pins and disposable custodian verified")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
