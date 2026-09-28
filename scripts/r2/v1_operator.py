"""Operator CLI for producing and approving the V1 no-provider factual product (Golden A).

Each command is one operator step against a running ArcReel server on this machine. The operator
signs in with their own account, and a gate command records the operator's own decision (ADR-0089
Human Gates). Gate A (Greenlight), Gate B (script lock) and Gate D (Publish Approval) are decided in
the web UI; this tool prints the digests they bind to. It also renders the shots and records the
Gate C decisions, which have no UI yet.

    export ARCREEL_URL=http://127.0.0.1:1241 ARCREEL_USERNAME=<operator>
    export ARCREEL_PASSWORD=<password>          # or be prompted
    uv run python -m scripts.r2.v1_operator digests
    uv run python -m scripts.r2.v1_operator produce --project <name> --data-dir <ARCREEL_DATA_DIR>
    uv run python -m scripts.r2.v1_operator approve-shots --project <name> --data-dir <ARCREEL_DATA_DIR>
    uv run python -m scripts.r2.v1_operator approve-final --project <name> --data-dir <ARCREEL_DATA_DIR> --audio MUTE

No paid provider is called: shots are rendered locally with Remotion and composed with ffmpeg.
The content is the Golden A H.264 explainer bundle (``r2/m3/fixtures/golden_a_h264.json``); its
director backend is fixture-specific, so another topic needs its own bundle and director.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE = REPO_ROOT / "r2" / "m3" / "fixtures" / "golden_a_h264.json"
REUSED_ASSET = "r2/m3/fixtures/assets/reused_terminal_frame.svg"
FINAL_TARGET_REF = "FINAL"
SHOTS_RECORD = "operator-shots.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bundle():
    from r2.m3.factual_fixture import load_golden_a_factual_bundle

    return load_golden_a_factual_bundle(BUNDLE)


def _prepared(bundle) -> list[Any]:
    from r2.m3.director import FixtureOpenMontageBackendH264, GoldenAOpenMontageAdapter
    from r2.m3.preparation import GoldenAProductionPreparation

    direction = GoldenAOpenMontageAdapter(FixtureOpenMontageBackendH264()).direct(bundle.script)
    return list(GoldenAProductionPreparation().prepare(direction.shots, reused_asset_ref=REUSED_ASSET))


def _claim_dependency(index: int):
    from r2.production import DependencySnapshot

    claim_id = f"CLAIM-H264-{index:03d}"
    return claim_id, DependencySnapshot(
        ref=f"claim:{claim_id}", version="1", fingerprint=hashlib.sha256(f"{claim_id}-v1".encode()).hexdigest()
    )


def digests() -> dict[str, str]:
    """The Gate A source digest and the Gate B script digest of the bundle."""
    bundle = _bundle()
    return {
        "source_digest": "sha256:" + _sha256_file(BUNDLE),
        "script_digest": "sha256:" + hashlib.sha256(bundle.script.model_dump_json().encode()).hexdigest(),
    }


def _production_root(data_dir: Path, project: str) -> Path:
    project_dir = (data_dir / project).resolve()
    if not project_dir.is_dir():
        raise SystemExit(f"project directory not found: {project_dir} (create the project in the UI first)")
    return project_dir / "production"


def produce(project: str, data_dir: Path) -> dict[str, Any]:
    """Render every shot into ``production/`` and record them; nothing is approved."""
    from r2.contracts.enums import ProductionMethod
    from r2.m3.local_production import GoldenALocalProducer

    bundle = _bundle()
    claims = {claim.id: claim for claim in bundle.claim_ledger.claims}
    production_root = _production_root(data_dir, project)
    producer = GoldenALocalProducer()
    shots: list[dict[str, Any]] = []
    for index, item in enumerate(_prepared(bundle), start=1):
        claim_id, _dependency = _claim_dependency(index)
        display_text = None if item.method.method is ProductionMethod.REUSE else claims[claim_id].statement
        asset = producer.produce(item, work_dir=production_root, display_text=display_text)
        shots.append(
            {
                "shot_id": item.shot.id,
                "method": asset.method.value,
                "relative_path": asset.path.resolve().relative_to(production_root.resolve()).as_posix(),
                "sha256": asset.sha256,
                "duration_seconds": asset.duration_seconds,
                "execution_fingerprint": asset.execution_fingerprint,
                "tool": asset.tool,
                "tool_version": asset.tool_version,
                "wall_time_seconds": asset.wall_time_seconds,
                "external_provider_cost": str(asset.external_provider_cost),
            }
        )
    (production_root / SHOTS_RECORD).write_text(json.dumps(shots, indent=2) + "\n", encoding="utf-8")
    return {"project": project, "shots": [{k: s[k] for k in ("shot_id", "relative_path", "sha256")} for s in shots]}


class _Api:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/") + "/api/v1", timeout=600)
        response = self._client.post("/auth/token", data={"username": username, "password": password})
        if response.status_code != 200:
            raise SystemExit(f"login failed: HTTP {response.status_code}")
        self._client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(path, json=body)
        if response.status_code != 200:
            raise SystemExit(f"POST {path} -> HTTP {response.status_code}: {response.text[:800]}")
        return response.json()


def approve_shots(api: _Api, project: str, data_dir: Path, only: Sequence[str] = ()) -> dict[str, Any]:
    """Gate C for each rendered shot master (or only the named shots)."""
    from r2.m3.host_integration import compute_content_fingerprint

    production_root = _production_root(data_dir, project)
    record = {s["shot_id"]: s for s in json.loads((production_root / SHOTS_RECORD).read_text(encoding="utf-8"))}
    approved: list[str] = []
    for index, item in enumerate(_prepared(_bundle()), start=1):
        shot = item.shot
        if only and shot.id not in only:
            continue
        _claim_id, dependency = _claim_dependency(index)
        produced = {k: v for k, v in record[shot.id].items() if k != "shot_id"}
        api.post(
            f"/projects/{project}/gates/final-cut",
            {
                "resource_type": "videos",
                "episode": 1,
                "target_ref": shot.id,
                "content_fingerprint": compute_content_fingerprint(shot, [dependency]),
                "content_basis": shot.content_basis.model_dump(mode="json"),
                "direct_dependencies": [dependency.model_dump(mode="json")],
                "contract_version": shot.version,
                "contract_schema_version": shot.schema_version,
                "produced": {**produced, "source_master_refs": []},
                "approval_record": f"APR-{project}-{shot.id}-{produced['sha256'][:12]}",
            },
        )
        approved.append(shot.id)
    return {"project": project, "approved_shots": approved}


def approve_final(api: _Api, project: str, data_dir: Path, audio: str) -> dict[str, Any]:
    """Compose the final from the approved shot masters and record Gate C for it."""
    from r2.m3.composition import GoldenAComposer
    from r2.m3.host_integration import GoldenAHostIntegration

    production_root = _production_root(data_dir, project)
    prepared = _prepared(_bundle())
    host = GoldenAHostIntegration(production_root.parent, resource_type="videos", episode=1)
    asset = GoldenAComposer().compose(
        host, [item.shot.id for item in prepared], output_path=production_root / "final" / f"{project}.mp4"
    )
    approved = api.post(
        f"/projects/{project}/gates/final-cut",
        {
            "resource_type": "videos",
            "episode": 1,
            "target_ref": FINAL_TARGET_REF,
            "content_fingerprint": hashlib.sha256(json.dumps(list(asset.source_master_refs)).encode()).hexdigest(),
            "content_basis": prepared[0].shot.content_basis.model_dump(mode="json"),
            "direct_dependencies": [],
            "contract_version": 1,
            "contract_schema_version": "1",
            "produced": {
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
            },
            "approval_record": f"APR-{project}-{FINAL_TARGET_REF}-{asset.sha256[:12]}",
            "audio_decision": audio,
        },
    )
    return {
        "project": project,
        "export": approved["export"],
        "duration_seconds": asset.duration_seconds,
        "next": "Project settings > Final Cut: Download, review, then Use for Publish Approval (Gate D)",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("digests", help="print the Gate A source digest and Gate B script digest")
    for name in ("produce", "approve-shots", "approve-final"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--project", required=True)
        cmd.add_argument("--data-dir", type=Path, default=Path(os.environ.get("ARCREEL_DATA_DIR", "projects")))
        if name == "approve-shots":
            cmd.add_argument("--shot", action="append", default=[], help="approve only this shot (repeatable)")
        if name == "approve-final":
            cmd.add_argument("--audio", required=True, choices=("AUDIO", "MUTE"))
    args = parser.parse_args(argv)

    if args.command == "digests":
        result: dict[str, Any] = digests()
    elif args.command == "produce":
        result = produce(args.project, args.data_dir)
    else:
        password = os.environ.get("ARCREEL_PASSWORD") or getpass.getpass("ArcReel password: ")
        api = _Api(
            os.environ.get("ARCREEL_URL", "http://127.0.0.1:1241"),
            os.environ.get("ARCREEL_USERNAME", "admin"),
            password,
        )
        if args.command == "approve-shots":
            result = approve_shots(api, args.project, args.data_dir, args.shot)
        else:
            result = approve_final(api, args.project, args.data_dir, args.audio)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
