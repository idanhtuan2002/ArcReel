"""Restore-derived Golden A/B drill for V1-05 (H6 attestation evidence).

Operator drill, not a pytest test (the module name keeps it out of collection).
It proves the restore path with the Golden products, per
``docs/research/2026-09-27-r2-v1-restore-derived-golden-drill.md``:

1. ``materialize`` (source deployment): creates three real Host projects
   through the HTTP API with a real login JWT. It renders the Golden A
   (H.264 factual) and both Golden B profile siblings with the existing
   no-provider fixture pipelines and Remotion. It drives Gates A, B
   (Golden B), C (per shot master, then the composed final, whose byte copy lands in
   ``output/``) and D through the real gate routes.
2. ``check`` (restored deployment): reads each project and its gate history
   through the API, confirms the Gate C approved masters and receipts
   survived, downloads the approved final through the host's token route, decodes the stored
   deliverable, and re-exports the final cut
   from the restored masters. That re-export must hash to the Gate D
   ``deliverable_digest``. It then writes ``GoldenRestoreEvidence``.
3. ``run`` (orchestrator): drives the whole drill against a disposable
   PostgreSQL server:
   - create and migrate the source database;
   - ``materialize``, then an offline backup;
   - destroy the source;
   - ``restore``, ``verify`` and ``check`` on a clean target;
   - ``attest`` with the measured RPO/RTO;
   - write the evidence JSON.

No provider credentials are configured and no provider is called.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_A_PROJECT = "golden-a-h264"
GOLDEN_B_PROJECTS = {"WESTERN_GENERIC": "golden-b-western", "CN_SHORT_DRAMA_SHUANGWEN": "golden-b-shuangwen"}
PUBLISH_PLATFORM = "drill"
PUBLISH_VISIBILITY = "private"
FINAL_DIRNAME = "final"
FINAL_TARGET_REF = "FINAL"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _decodes(path: Path) -> bool:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.returncode == 0 and bool(json.loads(probe.stdout or "{}").get("streams"))


async def _client():
    from httpx import ASGITransport, AsyncClient

    from server.app import app
    from server.auth import create_token

    token = create_token("golden-drill-operator")
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://golden-drill",
        headers={"Authorization": f"Bearer {token}"},
        timeout=600,
    )


async def _post(client, path: str, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(f"/api/v1{path}", json=body)
    if response.status_code != 200:
        raise RuntimeError(f"POST {path} -> {response.status_code}: {response.text[:500]}")
    return response.json()


def _produced_body(asset, production_root: Path) -> dict[str, Any]:
    return {
        "method": asset.method.value,
        "relative_path": asset.path.resolve().relative_to(production_root.resolve()).as_posix(),
        "sha256": asset.sha256,
        "duration_seconds": asset.duration_seconds,
        "execution_fingerprint": asset.execution_fingerprint,
        "tool": asset.tool,
        "tool_version": asset.tool_version,
        "wall_time_seconds": asset.wall_time_seconds,
        "external_provider_cost": str(asset.external_provider_cost),
        "source_master_refs": list(asset.source_master_refs),
    }


async def _approve_shot(client, project: str, *, shot, asset, production_root: Path, basis, dependencies) -> None:
    from r2.m3.host_integration import compute_content_fingerprint

    await _post(
        client,
        f"/projects/{project}/gates/final-cut",
        {
            "resource_type": "videos",
            "episode": 1,
            "target_ref": shot.id,
            "content_fingerprint": compute_content_fingerprint(shot, dependencies),
            "content_basis": basis.model_dump(mode="json"),
            "direct_dependencies": [dep.model_dump(mode="json") for dep in dependencies],
            "contract_version": shot.version,
            "contract_schema_version": shot.schema_version,
            "produced": _produced_body(asset, production_root),
            "approval_record": f"APR-{project}-{shot.id}",
        },
    )


def _compose_final(project_dir: Path, shot_ids: list[str], output: Path) -> dict[str, Any]:
    from r2.m3.composition import GoldenAComposer
    from r2.m3.host_integration import GoldenAHostIntegration

    host = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1)
    final = GoldenAComposer().compose(host, shot_ids, output_path=output)
    return {
        "shot_ids": shot_ids,
        "final_relative_path": (
            final.path.resolve().relative_to(project_dir.resolve()).as_posix()
            if final.path.resolve().is_relative_to(project_dir.resolve())
            else None
        ),
        "final_sha256": final.sha256,
        "duration_seconds": final.duration_seconds,
        "source_master_refs": list(final.source_master_refs),
    }


async def _approve_final(client, project: str, *, project_dir: Path, shot_ids: list[str], basis) -> dict[str, Any]:
    """Compose the final from the approved shot masters and approve it at Gate C (ADR-0090, O2a).

    Gate C writes the export copy to ``output/``; its digest is what Gate D binds.
    """
    from r2.m3.composition import GoldenAComposer
    from r2.m3.host_integration import GoldenAHostIntegration

    production_root = project_dir / "production"
    host = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1)
    asset = GoldenAComposer().compose(host, shot_ids, output_path=production_root / FINAL_DIRNAME / f"{project}.mp4")
    approved = await _post(
        client,
        f"/projects/{project}/gates/final-cut",
        {
            "resource_type": "videos",
            "episode": 1,
            "target_ref": FINAL_TARGET_REF,
            "content_fingerprint": hashlib.sha256(json.dumps(list(asset.source_master_refs)).encode()).hexdigest(),
            "content_basis": basis.model_dump(mode="json"),
            "direct_dependencies": [],
            "contract_version": 1,
            "contract_schema_version": "1",
            "produced": _produced_body(asset, production_root),
            "approval_record": f"APR-{project}-{FINAL_TARGET_REF}",
            # The no-provider fixture pipelines render no narration; Gate C verifies the track is silent.
            "audio_decision": "MUTE",
        },
    )
    export = approved["export"]
    return {
        "shot_ids": shot_ids,
        "final_relative_path": export["relative_path"],
        "final_sha256": export["sha256"].removeprefix("sha256:"),
        "duration_seconds": asset.duration_seconds,
        "source_master_refs": list(asset.source_master_refs),
    }


async def _greenlight(client, project: str, *, source_digest: str) -> None:
    await _post(
        client, f"/projects/{project}/gates/greenlight", {"source_digest": source_digest, "action": "GREENLIGHT"}
    )


async def _publish(client, project: str, *, deliverable_digest: str) -> None:
    await _post(
        client,
        f"/projects/{project}/gates/publish-approval",
        {
            "deliverable_digest": deliverable_digest,
            "platform": PUBLISH_PLATFORM,
            "visibility": PUBLISH_VISIBILITY,
            "action": "APPROVE_PUBLISH",
        },
    )


async def _materialize_golden_a(client, data_root: Path) -> dict[str, Any]:
    from r2.contracts.enums import ProductionMethod
    from r2.m3.director import FixtureOpenMontageBackendH264, GoldenAOpenMontageAdapter
    from r2.m3.factual_fixture import load_golden_a_factual_bundle
    from r2.m3.local_production import GoldenALocalProducer
    from r2.m3.preparation import GoldenAProductionPreparation
    from r2.production import DependencySnapshot

    fixture = REPO_ROOT / "r2" / "m3" / "fixtures" / "golden_a_h264.json"
    bundle = load_golden_a_factual_bundle(fixture)
    claims = {claim.id: claim for claim in bundle.claim_ledger.claims}
    direction = GoldenAOpenMontageAdapter(FixtureOpenMontageBackendH264()).direct(bundle.script)
    prepared = GoldenAProductionPreparation().prepare(
        direction.shots, reused_asset_ref="r2/m3/fixtures/assets/reused_terminal_frame.svg"
    )

    await _post(
        client,
        "/projects",
        {"name": GOLDEN_A_PROJECT, "title": "Golden A: how H.264 works", "generation_mode": "storyboard"},
    )
    source_digest = "sha256:" + _sha256_file(fixture)
    await _greenlight(client, GOLDEN_A_PROJECT, source_digest=source_digest)
    # Gate B for the factual product (ADR-0092): lock the exact source and script revision before production.
    script_digest = "sha256:" + hashlib.sha256(bundle.script.model_dump_json().encode()).hexdigest()
    await _post(
        client,
        f"/projects/{GOLDEN_A_PROJECT}/gates/script-lock",
        {"source_digest": source_digest, "script_digest": script_digest, "action": "LOCK"},
    )
    project_dir = data_root / GOLDEN_A_PROJECT
    production_root = project_dir / "production"
    producer = GoldenALocalProducer()
    shot_ids: list[str] = []
    for index, item in enumerate(prepared, start=1):
        claim_id = f"CLAIM-H264-{index:03d}"
        dependency = DependencySnapshot(
            ref=f"claim:{claim_id}", version="1", fingerprint=hashlib.sha256(f"{claim_id}-v1".encode()).hexdigest()
        )
        display_text = None if item.method.method is ProductionMethod.REUSE else claims[claim_id].statement
        asset = producer.produce(item, work_dir=production_root, display_text=display_text)
        await _approve_shot(
            client,
            GOLDEN_A_PROJECT,
            shot=item.shot,
            asset=asset,
            production_root=production_root,
            basis=item.shot.content_basis,
            dependencies=[dependency],
        )
        shot_ids.append(item.shot.id)

    final = await _approve_final(
        client,
        GOLDEN_A_PROJECT,
        project_dir=project_dir,
        shot_ids=shot_ids,
        basis=prepared[0].shot.content_basis,
    )
    await _publish(client, GOLDEN_A_PROJECT, deliverable_digest="sha256:" + final["final_sha256"])
    return {"project_name": GOLDEN_A_PROJECT, "kind": "GOLDEN_A", **final}


async def _materialize_golden_b(client, data_root: Path, profile_key: str) -> dict[str, Any]:
    from lib.db import async_session_factory
    from lib.db.adaptation_uow import adaptation_uow_factory
    from lib.db.base import DEFAULT_USER_ID
    from r2.adaptation.screenplay_reader import ApprovedScreenplayReader
    from r2.contracts import ProductionMethod, ResolvedIdentityStatus, ResolvedVisualIdentity
    from r2.contracts.adaptation import AdmittedScreenplayRef, ArtifactVersionRef, DecisionRef
    from r2.m3.local_production import GoldenALocalProducer
    from r2.m3.preparation import GoldenAMethodAssignment, GoldenAPreparedShot
    from r2.production_intelligence.readiness import ProductionReadinessEvaluator
    from r2.production_intelligence.take_director import TakeDirectionResult, TakeDirectorAdapter
    from tests.fixtures.r2.m6_dual_profile_corpus import build_golden_b_canon, build_screenplay_admission_command
    from tests.integration.r2.test_m6_dual_profile_acceptance import _basis, _shuangwen_ref, _western_ref

    project = GOLDEN_B_PROJECTS[profile_key]
    profile_ref = _western_ref() if profile_key == "WESTERN_GENERIC" else _shuangwen_ref()
    canon = build_golden_b_canon()
    uow_factory = adaptation_uow_factory(async_session_factory)

    await _post(
        client,
        "/projects",
        {
            "name": project,
            "title": f"Golden B: ledger reveal ({profile_key})",
            "generation_mode": "storyboard",
            "content_mode": "drama",
            "source_kind": "screenplay",
        },
    )
    setup = await build_screenplay_admission_command(
        profile_ref, canon=canon, uow_factory=uow_factory, user_id=DEFAULT_USER_ID, project_name=project
    )
    await _greenlight(client, project, source_digest="sha256:" + canon.canon_ref.content_hash.removeprefix("sha256:"))
    lock = await _post(client, f"/projects/{project}/gates/narrative-lock", setup.admit.model_dump(mode="json"))
    admitted = setup.admit.admitted_screenplay
    screenplay_ref = ArtifactVersionRef(
        artifact_id=admitted.screenplay_id, version=admitted.version, content_hash=admitted.content_hash
    )
    direction = await TakeDirectorAdapter(
        ApprovedScreenplayReader(uow_factory), user_id=DEFAULT_USER_ID, project_name=project
    ).direct(
        AdmittedScreenplayRef(
            screenplay_ref=screenplay_ref,
            admission_ref=DecisionRef.model_validate(lock["decision_ref"]),
            profile_ref=profile_ref,
        )
    )
    if not isinstance(direction, TakeDirectionResult):
        raise RuntimeError(f"take direction unavailable: {direction!r}")

    project_dir = data_root / project
    production_root = project_dir / "production"
    producer = GoldenALocalProducer()
    identity = ResolvedVisualIdentity(
        target_ref="golden-b", status=ResolvedIdentityStatus.RESOLVED, resolution_policy_version="identity-v1"
    )
    scenes = {scene.scene_id: scene for scene in admitted.scenes}
    shot_ids: list[str] = []
    for shot in direction.shots:
        readiness = ProductionReadinessEvaluator().evaluate(
            shot=shot,
            bindings=[],
            resolved_identity=identity,
            observed_target_version=f"{shot.id}@1",
            binding_snapshot_ref="golden-b-snapshot@1",
        )
        prepared = GoldenAPreparedShot(
            shot=shot,
            bindings=(),
            readiness=readiness,
            method=GoldenAMethodAssignment(
                target_ref=shot.id, method=ProductionMethod.DETERMINISTIC, rationale="Golden B dramatic text"
            ),
        )
        asset = producer.produce(prepared, work_dir=production_root, display_text=scenes[shot.scene_id].dramatic_text)
        await _approve_shot(
            client, project, shot=shot, asset=asset, production_root=production_root, basis=_basis(), dependencies=[]
        )
        shot_ids.append(shot.id)

    final = await _approve_final(client, project, project_dir=project_dir, shot_ids=shot_ids, basis=_basis())
    await _publish(client, project, deliverable_digest="sha256:" + final["final_sha256"])
    return {
        "project_name": project,
        "kind": f"GOLDEN_B_{profile_key}",
        "narrative_lock_decision_id": lock["decision_ref"]["decision_id"],
        **final,
    }


async def materialize(data_root: Path, out_path: Path) -> None:
    started = time.monotonic()
    async with await _client() as client:
        products = [
            await _materialize_golden_a(client, data_root),
            *[await _materialize_golden_b(client, data_root, profile_key) for profile_key in GOLDEN_B_PROJECTS],
        ]
    await asyncio.to_thread(
        _write_json, out_path, {"products": products, "materialize_seconds": round(time.monotonic() - started, 1)}
    )


async def _download_digest(client, project: str, digest: str) -> str | None:
    """Download the approved final through the host's token route and hash what it served."""
    token_response = await client.post(f"/api/v1/projects/{project}/export/deliverable/token")
    if token_response.status_code != 200:
        return None
    token = token_response.json()["download_token"]
    response = await client.get(
        f"/api/v1/projects/{project}/export/deliverable", params={"download_token": token, "digest": digest}
    )
    if response.status_code != 200:
        return None
    return "sha256:" + hashlib.sha256(response.content).hexdigest()


async def _final_audio_decision(project: str) -> str | None:
    from sqlalchemy import select

    from lib.artifact_manifest import ArtifactKey
    from lib.db import async_session_factory
    from lib.db.models.gates import FinalCutReceiptModel

    final_key = ArtifactKey.episode_video(1, FINAL_TARGET_REF).encode()
    async with async_session_factory() as session:
        result = await session.execute(
            select(FinalCutReceiptModel.audio_decision)
            .where(FinalCutReceiptModel.project_name == project, FinalCutReceiptModel.artifact_key == final_key)
            .order_by(FinalCutReceiptModel.sequence.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def _final_cut_receipt_count(project: str) -> int:
    from sqlalchemy import func, select

    from lib.db import async_session_factory
    from lib.db.models.gates import FinalCutReceiptModel

    async with async_session_factory() as session:
        result = await session.execute(
            select(func.count()).select_from(FinalCutReceiptModel).where(FinalCutReceiptModel.project_name == project)
        )
        return int(result.scalar_one())


async def check(
    data_root: Path, materialized_path: Path, backup_dir: Path, restore_target_id: str, out_path: Path
) -> None:
    from r2.contracts.host_hardening import GoldenProductResult, GoldenRestoreEvidence
    from r2.host_hardening.deployment_backup import manifest_digest, read_manifest
    from r2.m3.host_integration import GoldenAHostIntegration

    materialized = await asyncio.to_thread(_read_json, materialized_path)
    manifest = read_manifest(backup_dir)
    results: list[GoldenProductResult] = []
    details: list[dict[str, Any]] = []
    export_root = Path(os.environ.get("GOLDEN_DRILL_EXPORT_DIR", str(out_path.parent / "exports")))

    async with await _client() as client:
        for product in materialized["products"]:
            project = product["project_name"]
            problems: list[str] = []
            if (await client.get(f"/api/v1/projects/{project}")).status_code != 200:
                problems.append("PROJECT_UNREADABLE")
            history_response = await client.get(f"/api/v1/projects/{project}/gates")
            history = history_response.json() if history_response.status_code == 200 else {}
            greenlit = any(d.get("action") == "GREENLIGHT" for d in history.get("greenlight", []))
            published = [d for d in history.get("publish_approval", []) if d.get("action") == "APPROVE_PUBLISH"]
            if not greenlit:
                problems.append("GATE_A_MISSING")
            if not published:
                problems.append("GATE_D_MISSING")
            script_locks = history.get("script_lock", [])
            if product["kind"] == "GOLDEN_A" and (not script_locks or script_locks[-1].get("action") != "LOCK"):
                problems.append("GATE_B_MISSING")
            if product["kind"] != "GOLDEN_A" and not product.get("narrative_lock_decision_id"):
                problems.append("GATE_B_MISSING")
            if await _final_audio_decision(project) not in ("AUDIO", "MUTE"):
                problems.append("AUDIO_DECISION_MISSING")
            deliverable_digest = published[-1]["deliverable_digest"] if published else ""

            project_dir = data_root / project
            host = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1)
            for shot_id in product["shot_ids"]:
                metadata = host.snapshot(shot_id)
                if metadata.approved_master is None or not host.current_file_for(shot_id).is_file():
                    problems.append(f"MASTER_UNRESOLVED:{shot_id}")
            # One Gate C receipt per shot master plus one for the composed final.
            if await _final_cut_receipt_count(project) < len(product["shot_ids"]) + 1:
                problems.append("GATE_C_RECEIPTS_MISSING")

            stored_final = project_dir / product["final_relative_path"]
            if not stored_final.is_file() or "sha256:" + _sha256_file(stored_final) != deliverable_digest:
                problems.append("STORED_DELIVERABLE_MISMATCH")
            if stored_final.is_file() and not _decodes(stored_final):
                problems.append("STORED_DELIVERABLE_UNPLAYABLE")

            if await _download_digest(client, project, deliverable_digest) != deliverable_digest:
                problems.append("HOST_DOWNLOAD_MISMATCH")

            await asyncio.to_thread(export_root.mkdir, parents=True, exist_ok=True)
            reexport = _compose_final(project_dir, product["shot_ids"], export_root / f"{project}.mp4")
            reexported = export_root / f"{project}.mp4"
            if "sha256:" + reexport["final_sha256"] != deliverable_digest:
                problems.append("REEXPORT_DIGEST_MISMATCH")
            if not _decodes(reexported):
                problems.append("REEXPORT_UNPLAYABLE")

            details.append(
                {
                    "project_name": project,
                    "deliverable_digest": deliverable_digest,
                    "reexport_digest": "sha256:" + reexport["final_sha256"],
                    "problems": problems,
                }
            )
            results.append(
                GoldenProductResult(
                    project_name=project,
                    reviewed=not problems,
                    export_digest="sha256:" + reexport["final_sha256"],
                )
            )

    evidence = GoldenRestoreEvidence(
        backup_set_id=manifest.backup_set_id,
        manifest_digest=manifest_digest(manifest),
        restore_target_id=restore_target_id,
        passed=all(result.reviewed for result in results),
        products=tuple(results),
    )
    await asyncio.to_thread(_write_json, out_path, evidence.model_dump(mode="json"))
    await asyncio.to_thread(_write_json, out_path.parent / "golden-check-details.json", details)


# --------------------------------------------------------------------------- orchestrator


def _run(argv: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(argv[:6])} exited {result.returncode}: {result.stderr[-2000:]}")
    return result


def _phase_env(database_url: str, data_root: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OTEL_", "ARCREEL_TELEMETRY"))}
    env.update(
        {
            "DATABASE_URL": database_url,
            "ARCREEL_DATA_DIR": str(data_root),
            "ARCREEL_LOG_FILE_DISABLED": "1",
            "AUTH_ENABLED": "true",
        }
    )
    return env


async def _admin(admin_url: str, sql: str) -> None:
    import asyncpg

    from r2.host_hardening.deployment_backup import libpq_url

    conn = await asyncpg.connect(libpq_url(admin_url))
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


def _db_url(admin_url: str, name: str) -> str:
    return f"{admin_url.rsplit('/', 1)[0]}/{name}"


def orchestrate(admin_url: str, work_dir: Path, evidence_path: Path) -> None:
    head = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
    if _run(["git", "status", "--short"]).stdout.strip():
        raise RuntimeError("the drill must run on a clean tree so its evidence binds to HEAD")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    source_db, target_db = "golden_drill_source", "golden_drill_target"
    source_url, target_url = _db_url(admin_url, source_db), _db_url(admin_url, target_db)
    source_root, target_root = work_dir / "source-data", work_dir / "restored-data"
    source_root.mkdir()
    backup_dir = work_dir / "backup-set"
    restore_target_id = "golden-drill-target-1"
    python = [sys.executable, "-m"]
    drill = [*python, "tests.drills.r2.golden_restore_drill"]
    backup_cli = [*python, "scripts.r2.deployment_backup"]

    for name in (source_db, target_db):
        asyncio.run(_admin(admin_url, f'DROP DATABASE IF EXISTS "{name}"'))
        asyncio.run(_admin(admin_url, f'CREATE DATABASE "{name}"'))
    _run([sys.executable, "-m", "alembic", "upgrade", "head"], env=_phase_env(source_url, source_root))

    materialized = work_dir / "materialized.json"
    _run([*drill, "materialize", "--out", str(materialized)], env=_phase_env(source_url, source_root))

    backup_env = {**os.environ, "DRILL_SOURCE_URL": source_url, "DRILL_TARGET_URL": target_url}
    config = work_dir / "config.json"
    config.write_text(json.dumps({"profile": "golden-restore-drill"}), encoding="utf-8")
    created = json.loads(
        _run(
            [
                *backup_cli,
                "create",
                "--backup-set-id",
                "bs-golden-drill",
                "--backup-dir",
                str(backup_dir),
                "--root",
                f"data={source_root}",
                "--database-url-env",
                "DRILL_SOURCE_URL",
                "--deployment-id",
                "golden-drill-source",
                "--release-git-sha",
                head,
                "--release-image-digest",
                "sha256:" + "0" * 64,
                "--configuration-json",
                str(config),
            ],
            env=backup_env,
        ).stdout
    )

    incident_at = time.time()
    incident_monotonic = time.monotonic()
    asyncio.run(_admin(admin_url, f'DROP DATABASE "{source_db}" WITH (FORCE)'))
    shutil.rmtree(source_root)

    restored = json.loads(
        _run(
            [
                *backup_cli,
                "restore",
                "--backup-dir",
                str(backup_dir),
                "--target-root",
                f"data={target_root}",
                "--target-database-url-env",
                "DRILL_TARGET_URL",
            ],
            env=backup_env,
        ).stdout
    )
    verdict = json.loads(
        _run(
            [
                *backup_cli,
                "verify",
                "--backup-dir",
                str(backup_dir),
                "--target-root",
                f"data={target_root}",
                "--target-database-url-env",
                "DRILL_TARGET_URL",
                "--target-release-git-sha",
                head,
                "--restore-target-id",
                restore_target_id,
            ],
            env=backup_env,
        ).stdout
    )
    golden_evidence = work_dir / "golden-evidence.json"
    _run(
        [
            *drill,
            "check",
            "--materialized",
            str(materialized),
            "--backup-dir",
            str(backup_dir),
            "--restore-target-id",
            restore_target_id,
            "--out",
            str(golden_evidence),
        ],
        env={**_phase_env(target_url, target_root), "GOLDEN_DRILL_EXPORT_DIR": str(work_dir / "exports")},
    )
    rto_seconds = int(time.monotonic() - incident_monotonic) + 1
    recovery_point = datetime.fromisoformat(created["recovery_point"]).timestamp()
    rpo_seconds = max(0, int(incident_at - recovery_point))
    attest = subprocess.run(
        [
            *backup_cli,
            "attest",
            "--backup-dir",
            str(backup_dir),
            "--golden-evidence",
            str(golden_evidence),
            "--measured-rpo-seconds",
            str(rpo_seconds),
            "--measured-rto-seconds",
            str(rto_seconds),
        ],
        cwd=REPO_ROOT,
        env=backup_env,
        capture_output=True,
        text=True,
        check=False,
    )
    state = json.loads((backup_dir / "state.json").read_text(encoding="utf-8"))
    evidence = {
        "evidence": "R2 V1 restore-derived Golden A/B drill (V1-05 recovery, V1-07 O2a export)",
        "head": head,
        "research": "docs/research/2026-09-27-r2-v1-restore-derived-golden-drill.md",
        "environment": {
            "database": "disposable PostgreSQL server (not a deployment database)",
            "provider_credentials": "none configured; sanitized tables restored blank",
        },
        "materialized": json.loads(materialized.read_text(encoding="utf-8")),
        "backup_create": created,
        "source_destroyed_before_restore": True,
        "restore": restored,
        "verify": verdict,
        "golden_evidence": json.loads(golden_evidence.read_text(encoding="utf-8")),
        "golden_check_details": json.loads((work_dir / "golden-check-details.json").read_text(encoding="utf-8")),
        "attest": {
            "exit_code": attest.returncode,
            "stdout": json.loads(attest.stdout) if attest.returncode == 0 else None,
            "stderr_tail": attest.stderr.strip().splitlines()[-1:] if attest.returncode else [],
        },
        "measured_rpo_seconds": rpo_seconds,
        "measured_rto_seconds": rto_seconds,
        "ledger_state": state,
        "coverage_limits": [
            "Golden products are the existing fixture corpora (M3 H.264 factual; M6 ledger-reveal, both profiles), "
            "rendered locally with Remotion; no paid provider route is exercised.",
            "Export is ADR-0090 O2a: Gate C approves the composed COMPOSITE final, its byte copy in output/ is "
            "downloaded on the restored target through the host's download-token route and must hash to the Gate D "
            "deliverable_digest; re-composing from the restored masters must reproduce the same bytes.",
            "Browser/operator workflow checks remain the E2 / V1-07 packet.",
            "RPO/RTO are single-machine drill timings (RTO spans restore, verify, the Golden check and re-export).",
        ],
    }
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if attest.returncode != 0 or state.get("state") != "VERIFIED":
        raise SystemExit(f"attest failed: {evidence['attest']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    mat = sub.add_parser("materialize")
    mat.add_argument("--out", required=True, type=Path)
    chk = sub.add_parser("check")
    chk.add_argument("--materialized", required=True, type=Path)
    chk.add_argument("--backup-dir", required=True, type=Path)
    chk.add_argument("--restore-target-id", required=True)
    chk.add_argument("--out", required=True, type=Path)
    run = sub.add_parser("run")
    run.add_argument("--admin-url-env", default="GOLDEN_DRILL_ADMIN_URL")
    run.add_argument("--work-dir", required=True, type=Path)
    run.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.command in {"materialize", "check"}:
        data_root = Path(os.environ["ARCREEL_DATA_DIR"]).resolve()
        if args.command == "materialize":
            asyncio.run(materialize(data_root, args.out))
        else:
            asyncio.run(check(data_root, args.materialized, args.backup_dir, args.restore_target_id, args.out))
        return 0
    orchestrate(os.environ[args.admin_url_env], args.work_dir.resolve(), args.evidence.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
