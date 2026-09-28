"""V1 operator workflow in a real browser, against a restore-derived environment (M7-E E2, V1-07).

Runs only when pointed at a restored target: the golden restore drill's restored data root and
database (``tests/drills/r2/golden_restore_drill.py run``). The environment is disposable; the test
records a Gate D decision and a refused Gate C request in it.

    uv sync && (cd frontend && pnpm build)
    ARCREEL_E2E_DATA_DIR=<work>/restored-data \\
    ARCREEL_E2E_DATABASE_URL=postgresql+asyncpg://…/golden_drill_target \\
    [ARCREEL_E2E_EVIDENCE=<dir>] uv run python -m pytest tests/e2e/test_m7_production_candidate_workflow.py

The browser is the system Chrome (``channel="chrome"``). No provider is configured or called. For
each restored Golden product the operator logs in, opens project settings, sees the approved final,
downloads it through the download-token route and checks its bytes against the Gate D digest. Then:

- a refused Gate C re-approval leaves the approved final and its digest unchanged;
- Publish Approval is filled from the listed final and recorded;
- a download token for another project and an unknown digest are refused, and so is an
  unauthenticated gate read;
- the workspace's event stream survives a server restart while the browser is offline: a title
  changed during the outage appears after reconnecting, through the stream's snapshot, without a
  page reload;
- after the restart, the reopened settings page lists the same final and serves the same bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

sync_api = pytest.importorskip("playwright.sync_api", reason="uv sync (dev group)")

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist" / "index.html"
GOLDEN_PROJECTS = ("golden-a-h264", "golden-b-western", "golden-b-shuangwen")
USERNAME = "e2e-operator"
PASSWORD = "e2e-password-not-a-secret"

pytestmark = pytest.mark.timeout(900)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is not set; point it at a restore-derived target")
    return value


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class _Server:
    def __init__(self, env: dict[str, str], port: int, log_path: Path) -> None:
        self.env, self.port, self.log_path = env, port, log_path
        self.base_url = f"http://127.0.0.1:{port}"
        self._process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        log = self.log_path.open("ab")
        self._process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=REPO_ROOT,
            env=self.env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise RuntimeError(f"server exited {self._process.returncode}; see {self.log_path}")
            try:
                if httpx.get(f"{self.base_url}/api/v1/auth/status", timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise RuntimeError(f"server did not become ready; see {self.log_path}")

    def stop(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=10)
        self._process = None


@pytest.fixture(scope="module")
def evidence_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    configured = os.environ.get("ARCREEL_E2E_EVIDENCE", "").strip()
    path = Path(configured) if configured else tmp_path_factory.mktemp("e2e-evidence")
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="module")
def server(evidence_dir: Path) -> Iterator[_Server]:
    data_dir = _require_env("ARCREEL_E2E_DATA_DIR")
    database_url = _require_env("ARCREEL_E2E_DATABASE_URL")
    if not FRONTEND_DIST.is_file():
        pytest.skip("frontend/dist is missing; run (cd frontend && pnpm build)")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OTEL_", "ARCREEL_TELEMETRY"))}
    env.update(
        {
            "DATABASE_URL": database_url,
            "ARCREEL_DATA_DIR": data_dir,
            "ARCREEL_LOG_FILE_DISABLED": "1",
            "AUTH_ENABLED": "true",
            "AUTH_USERNAME": USERNAME,
            "AUTH_PASSWORD": PASSWORD,
            "AUTH_TOKEN_SECRET": "e2e-token-secret-" + "0" * 32,
        }
    )
    instance = _Server(env, _free_port(), evidence_dir / "server.log")
    instance.start()
    try:
        yield instance
    finally:
        instance.stop()


@pytest.fixture(scope="module")
def browser_page(server: _Server) -> Iterator[Page]:
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(accept_downloads=True, locale="en-US", base_url=server.base_url)
        context.add_init_script("window.localStorage.setItem('i18nextLng', 'en')")
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()


def _login(page: Page) -> str:
    page.goto("/login")
    page.fill("#login-username", USERNAME)
    page.fill("#login-password", PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_url("**/app/**", timeout=30_000)
    # The first-use tour opens on a fresh deployment and steers every navigation back to its
    # own route; the operator skips it, which the server records.
    skip = page.get_by_role("button", name="Skip")
    try:
        skip.wait_for(timeout=15_000)
        skip.click()
    except sync_api.TimeoutError:
        pass
    token = page.evaluate("window.localStorage.getItem('arcreel_auth_token')")
    assert isinstance(token, str)
    assert token
    return token


def _api(server: _Server, token: str) -> httpx.Client:
    return httpx.Client(base_url=f"{server.base_url}/api/v1", headers={"Authorization": f"Bearer {token}"})


def _open_settings(page: Page, project: str) -> Locator:
    page.goto(f"/app/projects/{project}/settings")
    row = page.get_by_text("Episode 1 · FINAL", exact=True)
    row.wait_for(timeout=60_000)
    return row.locator("xpath=..")


def _listed_digest(row: Locator) -> str:
    digest = row.locator("code").get_attribute("title")
    assert digest is not None
    assert digest.startswith("sha256:")
    return digest


def _download(page: Page, row: Locator, target: Path) -> bytes:
    with page.expect_download(timeout=120_000) as download_info:
        row.get_by_role("button", name="Download").click()
    download = download_info.value
    download.save_as(target)
    return target.read_bytes()


def _published_digests(client: httpx.Client, project: str) -> list[str]:
    history = client.get(f"/projects/{project}/gates").raise_for_status().json()
    return [d["deliverable_digest"] for d in history["publish_approval"] if d["action"] == "APPROVE_PUBLISH"]


def test_the_operator_reviews_downloads_approves_and_reopens_restored_golden_products(
    server: _Server, browser_page: Page, evidence_dir: Path
) -> None:
    page = browser_page
    token = _login(page)
    record: dict[str, object] = {"products": {}}
    products: dict[str, dict[str, object]] = {}

    with _api(server, token) as client:
        listed = {p["name"] for p in client.get("/projects").raise_for_status().json()["projects"]}
        assert set(GOLDEN_PROJECTS) <= listed

        for project in GOLDEN_PROJECTS:
            row = _open_settings(page, project)
            digest = _listed_digest(row)
            body = _download(page, row, evidence_dir / f"{project}.mp4")
            page.screenshot(path=str(evidence_dir / f"{project}-settings.png"), full_page=True)
            assert _sha256(body) == digest
            assert digest in _published_digests(client, project)
            products[project] = {"digest": digest, "bytes": len(body)}

        project = GOLDEN_PROJECTS[0]
        digest = str(products[project]["digest"])
        project_dir = Path(os.environ["ARCREEL_E2E_DATA_DIR"]) / project
        forged = project_dir / "production" / "e2e-refused.mp4"
        forged.write_bytes(b"not the approved final")
        refused = client.post(
            f"/projects/{project}/gates/final-cut",
            json={
                "resource_type": "videos",
                "episode": 1,
                "target_ref": "FINAL",
                "content_fingerprint": "e2e-refused",
                "content_basis": {"basis_type": "FACTUAL", "basis_version": "v1", "refs": ["research:e2e"]},
                "direct_dependencies": [],
                "contract_version": 1,
                "contract_schema_version": "1",
                "produced": {
                    "method": "COMPOSITE",
                    "relative_path": "e2e-refused.mp4",
                    "sha256": digest,
                    "duration_seconds": 1.0,
                    "execution_fingerprint": "e2e-refused",
                    "tool": "ffmpeg",
                    "tool_version": "e2e",
                    "wall_time_seconds": 0.0,
                    "external_provider_cost": "0",
                    "source_master_refs": [],
                },
                "approval_record": "APR-e2e-refused",
            },
        )
        assert refused.status_code == 400
        assert _listed_digest(_open_settings(page, project)) == digest

        before = len(_published_digests(client, project))
        row = _open_settings(page, project)
        row.get_by_role("button", name="Use for Publish Approval").click()
        assert page.get_by_placeholder("Deliverable digest").input_value() == digest
        page.get_by_placeholder("Platform").fill("youtube")
        page.get_by_placeholder("Visibility").fill("private")
        page.get_by_role("button", name="Approve").last.click()
        deadline = time.monotonic() + 30
        while len(_published_digests(client, project)) == before and time.monotonic() < deadline:
            time.sleep(0.5)
        assert _published_digests(client, project)[before:] == [digest]

        other_token = client.post(f"/projects/{GOLDEN_PROJECTS[1]}/export/deliverable/token").json()["download_token"]
        foreign = page.request.get(
            f"/api/v1/projects/{project}/export/deliverable",
            params={"download_token": other_token, "digest": digest},
        )
        assert foreign.status == 403
        own_token = client.post(f"/projects/{project}/export/deliverable/token").json()["download_token"]
        unknown = page.request.get(
            f"/api/v1/projects/{project}/export/deliverable",
            params={"download_token": own_token, "digest": "sha256:" + "0" * 64},
        )
        assert unknown.status == 404
        assert httpx.get(f"{server.base_url}/api/v1/projects/{project}/gates").status_code == 401

    # Reconnect and resync: the workspace's project event stream is cut by a server restart while
    # the browser is offline, the title changes during the outage, and after reconnecting the
    # stream's snapshot (new fingerprint) must refresh the open page without a reload.
    page.goto(f"/app/projects/{project}")
    with _api(server, token) as client:
        old_title = client.get(f"/projects/{project}").raise_for_status().json()["project"]["title"]
    page.get_by_text(old_title).first.wait_for(timeout=60_000)
    new_title = f"{old_title} (resync {int(time.time())})"
    page.context.set_offline(True)
    server.stop()
    server.start()
    with _api(server, token) as client:
        client.patch(f"/projects/{project}", json={"title": new_title}).raise_for_status()
    page.context.set_offline(False)
    page.get_by_text(new_title).first.wait_for(timeout=90_000)
    resynced_url = page.url

    row = _open_settings(page, project)
    assert _listed_digest(row) == digest
    reopened = _download(page, row, evidence_dir / f"{project}-after-restart.mp4")
    assert _sha256(reopened) == digest

    record["products"] = products
    record["refused_gate_c_status"] = 400
    record["publish_approval_recorded"] = digest
    record["foreign_token_status"] = 403
    record["unknown_digest_status"] = 404
    record["restart_reopen_digest"] = _sha256(reopened)
    record["sse_resync"] = {"page": resynced_url.removeprefix(server.base_url), "title_after_outage": new_title}
    (evidence_dir / "e2e-result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
