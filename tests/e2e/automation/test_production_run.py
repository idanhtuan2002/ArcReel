"""A new idea becomes an exported, Quality-passed film through the activated app and real local models.

Opt-in: ``ARCREEL_E2E_AUTOMATION=1`` with PostgreSQL, Ollama (writer and both reviewers pulled), ComfyUI (FLUX.2
klein and Wan 2.2) and the VieNeu TTS shim running, and ``ARCREEL_E2E_REVIEWER_CORPUS`` naming a labeled corpus
manifest. The host is the real app lifespan with run delegation activated over fixture governance custody. Setup
does what a release owner does once per project: configure the launch profile's routes, publish the automatic
Quality profile, qualify both reviewers on the blind corpus and record the launch qualification. The run itself is
driven only through the public API. A record of the run is written to ``ARCREEL_E2E_EVIDENCE`` when set.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from lib.db.models.custom_endpoint import CustomEndpoint
from lib.db.models.custom_provider import CustomProvider, CustomProviderModel
from lib.db.repositories.launch_qualifications import LaunchQualificationRepository
from lib.db.repositories.quality_dispositions import QualityDispositionRepository
from lib.db.repositories.reviewer_qualifications import ReviewerQualificationRepository
from lib.generation_resources import configure_device_admission
from lib.project_manager import ProjectManager
from r2.automation.profiles import reviewer_is_qualified
from r2.contracts.automation import ModelRoute
from server import auth
from server.production_run.composition import ProjectPolicyResolver, device_admission_from_env
from server.production_run.evaluators import OllamaReviewer, provider_base_url
from tests.integration.server.services.test_automation_grants import interactive_env as interactive_env

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("ARCREEL_E2E_AUTOMATION") != "1", reason="real-model automatic production e2e is opt-in"
    ),
    pytest.mark.timeout(12 * 3600),
]

REPO = Path(__file__).resolve().parents[3]
MEDIA_EVIDENCE = REPO / "docs/r2/evidence/media-local-2026-10-30"
OLLAMA = "http://127.0.0.1:11434"
COMFYUI = "http://127.0.0.1:8188"
TTS = "http://127.0.0.1:23340/v1"
WRITER = "qwen3.5-vimax:9b"
REVIEWERS = {"reviewer_a": "qwen2.5vl:7b", "reviewer_b": "gemma3:4b"}
TERMINAL = {"SUCCEEDED", "FAILED", "FAILED_QUALITY", "CANCELLED"}
STOPPED = {"WAITING_REVIEW", "PAUSED"}
IDEA = "Một cậu bé ở làng chài miền Trung nhặt được chiếc chai có lá thư của người cha đã mất tích ngoài biển."


def _ollama_identity(model: str) -> str:
    tags = httpx.get(f"{OLLAMA}/api/tags", timeout=10).json()["models"]
    digest = next(item["digest"] for item in tags if item["name"] == model)
    return f"ollama/{model}@sha256:{digest}"


def _source_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()


def _definition(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("definition", data)


async def _configure_providers(sessions) -> None:
    """The launch profile's provider ids, exactly as the host is configured: Ollama, VieNeu and ComfyUI."""
    flux = _definition(MEDIA_EVIDENCE / "endpoint-definition.json")
    wan = _definition(MEDIA_EVIDENCE / "wan-2.2/saved-endpoint-definition.json")
    async with sessions() as session, session.begin():
        for endpoint_id, definition in ((1, flux), (2, wan)):
            session.add(
                CustomEndpoint(
                    id=endpoint_id,
                    definition=definition,
                    kind=definition["kind"],
                    schema_version=definition["schema_version"],
                    media_type=definition["media_type"],
                    display_name=definition["meta"]["name"],
                )
            )
        session.add_all(
            [
                CustomProvider(
                    id=1, display_name="Ollama local", discovery_format="openai", base_url=OLLAMA, api_key=""
                ),
                CustomProvider(
                    id=2, display_name="VieNeu TTS (local)", discovery_format="openai", base_url=TTS, api_key="local"
                ),
                CustomProvider(
                    id=3,
                    display_name="ComfyUI local (RTX 2070)",
                    discovery_format="comfyui",
                    base_url=COMFYUI,
                    api_key="",
                    image_max_workers=1,
                    video_max_workers=1,
                ),
            ]
        )
        await session.flush()
        for model in (WRITER, *REVIEWERS.values()):
            session.add(CustomProviderModel(provider_id=1, model_id=model, display_name=model, endpoint="ollama-chat"))
        session.add(
            CustomProviderModel(
                provider_id=2,
                model_id="vieneu-tts-v3-turbo",
                display_name="VieNeu",
                endpoint="openai-tts",
                price_input=0.0,
            )
        )
        session.add(
            CustomProviderModel(
                provider_id=3,
                model_id="flux2-klein-4b-gguf",
                display_name="FLUX.2 klein",
                endpoint="ce-1",
                price_input=0.0,
            )
        )
        session.add(
            CustomProviderModel(
                provider_id=3,
                model_id="wan2.2-ti2v-5b-gguf",
                display_name="Wan 2.2",
                endpoint="ce-2",
                price_input=0.0,
                supported_durations=json.dumps([2]),
                resolution="480p",
            )
        )


def _automation_settings(profile: dict) -> dict:
    routes = [
        {"role": "writer", "provider_id": "custom-1", "model_id": WRITER, "model_identity": _ollama_identity(WRITER)},
        {"role": "script", "provider_id": "custom-1", "model_id": WRITER, "model_identity": _ollama_identity(WRITER)},
        *(
            {"role": role, "provider_id": "custom-1", "model_id": model, "model_identity": _ollama_identity(model)}
            for role, model in REVIEWERS.items()
        ),
        {
            "role": "image",
            "provider_id": "custom-3",
            "model_id": "flux2-klein-4b-gguf",
            "model_identity": "comfyui/flux2-klein-4b-Q4_K_M",
        },
        {
            "role": "video",
            "provider_id": "custom-3",
            "model_id": "wan2.2-ti2v-5b-gguf",
            "model_identity": "comfyui/wan2.2-ti2v-5b-Q4_K_M",
        },
        {
            "role": "audio",
            "provider_id": "custom-2",
            "model_id": "vieneu-tts-v3-turbo",
            "model_identity": "vieneu/tts-v3-turbo",
        },
    ]
    return {
        **profile,
        "launch_profile_id": "fiction_narration_vi_v1",
        "local_only": True,
        "paid": False,
        "routes": [{**route, "local": True, "paid": False} for route in routes],
        "voice_available": True,
        "required_disk_bytes": 8 * 1024**3,
        "required_gpu_bytes": 7 * 1024**3,
    }


async def _qualify_reviewers(sessions, projects: ProjectManager, corpus: Path, output: Path) -> dict:
    from lib.config.resolver import ConfigResolver
    from scripts.r2.qualify_reviewers import qualify

    routes = await ProjectPolicyResolver(sessions, projects=projects, resolver=ConfigResolver(sessions)).routes(
        "project"
    )
    settings = projects.load_project("project")["automation"]
    results = {}
    for route in routes:
        if route.role not in REVIEWERS:
            continue
        started = time.monotonic()
        record = await qualify(
            corpus=corpus,
            route=ModelRoute.model_validate(route),
            evaluator=OllamaReviewer(base_url_for=provider_base_url(sessions)),
            output=output / route.role,
            profile_digest=settings["profile_digest"],
            launch_profile_id=settings["launch_profile_id"],
            language="vi",
        )
        qualified = reviewer_is_qualified(record)
        results[route.role] = {
            "model_identity": record.model_identity,
            "qualified": qualified,
            "seconds": round(time.monotonic() - started, 1),
            "cases": [case.model_dump(mode="json") for case in record.cases],
        }
        if qualified:
            async with sessions() as session, session.begin():
                await ReviewerQualificationRepository(session).record(record)
    return results


@pytest.fixture
async def e2e_sessions():
    """The process-wide session factory on ``DATABASE_URL``: a PostgreSQL database migrated to head for this run.

    Worker, scheduler and app all use that factory, exactly as on a host. The fixture custody stamps the schema
    version and installs the Quality publication immutability triggers itself, so the migrated stamp and those
    triggers are removed first; the run's user is seeded.
    """
    import sqlalchemy as sa

    from lib.db import async_session_factory

    engine = async_session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("automatic production e2e needs a migrated PostgreSQL database")
    async with engine.begin() as connection:
        await connection.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))
        for table in (
            "m10_profile_publication_authorizations",
            "m10_quality_profile_revisions",
            "m10_quality_commands",
            "m10_quality_outbox",
        ):
            await connection.execute(sa.text(f'DROP TRIGGER IF EXISTS "{table}_immutable" ON "{table}"'))
        await connection.execute(
            sa.text(
                "INSERT INTO users (id, username, role, is_active, created_at, updated_at) "
                "VALUES ('default', 'default', 'user', true, NOW(), NOW()) ON CONFLICT (id) DO NOTHING"
            )
        )
    return async_session_factory


def _write_evidence(record: dict) -> None:
    target = os.environ.get("ARCREEL_E2E_EVIDENCE")
    if target:
        Path(target).write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


async def test_new_idea_reaches_current_quality_pass_and_export(e2e_sessions, tmp_path, interactive_env, monkeypatch):
    import server.app as app_module
    from scripts.r2.record_launch_qualification import build_record
    from server.services.governance_attestation import serve_governance_attestor
    from server.tool_runtime import CallerContext, CreateProjectToolRequest, Services, ToolRequest, create_project
    from tests.integration.r2.governance.test_activated_governance_startup import _configure_lifespan
    from tests.integration.server.production_run.test_quality_adapter import _publish_profile
    from tests.integration.server.services.test_quality_profile_custodian import prepare_qualified_custody

    corpus = Path(os.environ["ARCREEL_E2E_REVIEWER_CORPUS"])
    sessions = e2e_sessions
    evidence: dict = {
        "source_head": await asyncio.to_thread(_source_head),
        "started_at": datetime.now(UTC).isoformat(),
        "idea": IDEA,
    }
    root, runtime, *_ = await prepare_qualified_custody(sessions, tmp_path)
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    projects = ProjectManager(projects_root)
    created = await create_project(
        ToolRequest(
            CreateProjectToolRequest(
                name="project", title="Lá thư trong chai", content_mode="narration", generation_mode="storyboard"
            )
        ),
        CallerContext(user_id="default", source="embedded"),
        Services(projects=projects, workflow_planner=object(), capabilities=object()),
    )
    assert created.problem is None
    await _configure_providers(sessions)
    profile = await _publish_profile(sessions)

    def configure(project: dict) -> None:
        project["automation"] = _automation_settings(profile)
        project["default_text_backend"] = f"custom-1/{WRITER}"
        project["default_image_backend"] = "custom-3/flux2-klein-4b-gguf"
        project["video_backend"] = "custom-3/wan2.2-ti2v-5b-gguf"
        project["audio_backend"] = "custom-2/vieneu-tts-v3-turbo"
        project["narration_voice"] = "nova"

    projects.update_project("project", configure)
    evidence["reviewer_qualification"] = await _qualify_reviewers(sessions, projects, corpus, tmp_path / "reviews")
    assert all(item["qualified"] for item in evidence["reviewer_qualification"].values()), "reviewers not qualified"

    monkeypatch.setenv("ARCREEL_GPU_ADMISSION_PROBES", f"ollama={OLLAMA},comfyui={COMFYUI}")
    configure_device_admission(device_admission_from_env())
    record, reasons = await build_record(
        sessions,
        projects=projects,
        user_id="default",
        project_name="project",
        evidence=MEDIA_EVIDENCE / "three-scene-proof/final-verification.json",
    )
    assert record is not None, reasons
    async with sessions() as session, session.begin():
        await LaunchQualificationRepository(session).record(record)
    evidence["launch_qualification"] = record.model_dump(mode="json")

    monkeypatch.setenv("ARCREEL_AUTOMATIC_PRODUCTION", "1")
    _configure_lifespan(sessions, root, runtime, projects_root, monkeypatch)
    headers = {"Authorization": f"Bearer {auth.create_token('actor')}"}
    base = "/api/v1/projects/project/production-runs"
    async with (
        serve_governance_attestor(
            root, runtime, session_factory=sessions, expected_uid=os.getuid(), expected_gid=os.getgid()
        ),
        app_module.lifespan(app_module.app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_module.app), base_url="http://test", timeout=120
        ) as http,
    ):
        offer = (await http.get(base, headers=headers)).raise_for_status().json()["start"]
        evidence["offer"] = offer
        assert offer["enabled"], offer
        started = time.monotonic()
        run = (
            (
                await http.post(
                    base,
                    headers=headers,
                    json={
                        "command_id": "e2e-start-1",
                        "mode": "auto",
                        "idea": IDEA,
                        "expected_input_digest": offer["input_digest"],
                        "policy_digest": offer["policy_digests"]["auto"],
                    },
                )
            )
            .raise_for_status()
            .json()
        )
        history = [{"t": 0.0, "stage": run["stage"], "status": run["status"]}]
        deadline = float(os.environ.get("ARCREEL_E2E_TIMEOUT_SECONDS", 6 * 3600))
        while run["status"] not in TERMINAL | STOPPED and time.monotonic() - started < deadline:
            await asyncio.sleep(15)
            run = (await http.get(f"{base}/{run['run_id']}", headers=headers)).raise_for_status().json()
            if (history[-1]["stage"], history[-1]["status"]) != (run["stage"], run["status"]):
                history.append(
                    {"t": round(time.monotonic() - started, 1), "stage": run["stage"], "status": run["status"]}
                )
                _write_evidence({**evidence, "history": history, "run": run})
        evidence.update(history=history, run=run, elapsed_seconds=round(time.monotonic() - started, 1))
        _write_evidence(evidence)
        assert run["status"] == "SUCCEEDED", (run["status"], run.get("reason"))

        target = run["completed_targets"][0]
        download = await http.get(f"{base}/{run['run_id']}/outputs/1", headers=headers)
        download.raise_for_status()
        downloaded = "sha256:" + hashlib.sha256(download.content).hexdigest()
        evidence["download"] = {"sha256": downloaded, "bytes": len(download.content)}
    disposition_id = target["quality_run"]["receipt_ref"].rpartition("@")[2]
    async with sessions() as session:
        disposition = await QualityDispositionRepository(session).disposition(
            user_id="default", project_name="project", disposition_id=disposition_id
        )
    evidence["disposition"] = disposition.model_dump(mode="json") if disposition else None
    _write_evidence(evidence)
    assert disposition is not None
    assert disposition.decision.value == "PASS"
    assert target["quality_decision"] == "PASS"
    assert downloaded == target["archive_digest"]
