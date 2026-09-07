#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from r2.bootstrap import frozen_docs_dir

VALID_DECISION_STATUSES = {
    "LOCKED",
    "ACTIVE",
    "SUPERSEDED",
    "DEFERRED",
    "REJECTED",
}

NON_AUTHORITATIVE_PLANES = {
    "NON_AUTHORITATIVE",
    "PROPOSAL",
    "PROPOSAL_TO_NARRATIVE_AUTHORITY",
    "CROSS_AUTHORITY_LINEAGE",
    "REVIEW_PLANE",
}

REQUIRED_PROVIDER_NEUTRAL_FORBIDDEN_FIELDS = {
    "provider",
    "model",
    "endpoint",
    "payload",
    "provider_job_id",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_roadmap_acyclic(roadmap: dict) -> list[str]:
    errors: list[str] = []
    milestones = {m["id"]: set(m.get("depends_on", [])) for m in roadmap["milestones"]}

    for node, deps in milestones.items():
        unknown = deps - milestones.keys()
        if unknown:
            errors.append(f"roadmap {node} has unknown dependencies: {sorted(unknown)}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            errors.append(f"roadmap cycle detected at {node}")
            return
        visiting.add(node)
        for dep in milestones.get(node, set()):
            visit(dep)
        visiting.remove(node)
        visited.add(node)

    for node in milestones:
        visit(node)
    return errors


def verify(docs_dir: Path | None = None) -> list[str]:
    docs = docs_dir or frozen_docs_dir()
    errors: list[str] = []

    required = {
        "contracts": docs / "R2_03_CONTRACT_REGISTRY.json",
        "decisions": docs / "R2_04_DECISION_REGISTRY.json",
        "supersession": docs / "R2_04_SUPERSESSION_MAP.json",
        "hardening": docs / "R2_05_HOST_HARDENING_REGISTRY.json",
        "roadmap": docs / "R2_06_ROADMAP_REGISTRY.json",
    }
    for name, path in required.items():
        if not path.is_file():
            errors.append(f"missing {name} registry: {path.name}")
    if errors:
        return errors

    try:
        contracts = _load(required["contracts"])
        decisions = _load(required["decisions"])
        supersession = _load(required["supersession"])
        hardening = _load(required["hardening"])
        roadmap = _load(required["roadmap"])
    except (json.JSONDecodeError, OSError) as exc:
        return [f"registry load failure: {exc}"]

    ids = [item["decision_id"] for item in decisions["decisions"]]
    if len(ids) != len(set(ids)):
        errors.append("duplicate decision IDs")
    id_set = set(ids)

    errors.extend(
        f"{item.get('decision_id')} has invalid status {item.get('status')}"
        for item in decisions["decisions"]
        if item.get("status") not in VALID_DECISION_STATUSES
    )

    for mapping in supersession["mappings"]:
        target = mapping.get("superseded_by")
        if target not in id_set:
            errors.append(f"supersession target missing: {mapping.get('legacy_decision')} -> {target}")

    by_name: dict[str, dict] = {}
    for item in contracts["contracts"]:
        name = item["name"]
        by_name[name] = item
        if item.get("authority") not in NON_AUTHORITATIVE_PLANES and not item.get("commit_authority"):
            errors.append(f"{name} has no commit authority")

    for name in ("SceneSpec", "ShotSpec"):
        item = by_name.get(name)
        if item is None:
            errors.append(f"missing contract {name}")
            continue
        forbidden = set(item.get("forbidden_fields", []))
        missing = REQUIRED_PROVIDER_NEUTRAL_FORBIDDEN_FIELDS - forbidden
        if missing:
            errors.append(f"{name} missing forbidden fields: {sorted(missing)}")

    h1 = next(
        (item for item in hardening["requirements"] if item.get("id") == "H1"),
        None,
    )
    if h1 is None:
        errors.append("H1 missing from Host hardening registry")
    else:
        if h1.get("severity") != "PRODUCTION_BLOCKER":
            errors.append("H1 must remain PRODUCTION_BLOCKER")
        if h1.get("decision_ref") != "R2-HOST-001":
            errors.append("H1 must reference R2-HOST-001")

    errors.extend(_check_roadmap_acyclic(roadmap))
    return errors


def main() -> int:
    errors = verify()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("R2 frozen registry verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
