"""M8-B Creative Canvas benchmark against the frozen protocol (R2_M8_B_CANVAS_BENCHMARK_PROTOCOL.json).

Runs the production build (``vite preview``) in the Chromium bundled with the repository's Python
Playwright. The API is served by Playwright route handlers, so no server, database or provider is
involved: the Canvas opens a seeded, episode-shaped graph for each ladder rung and autosaves to an
in-memory candidate.

    (cd frontend && pnpm build)
    uv run playwright install chromium
    ARCREEL_M8B_BENCHMARK=1 [ARCREEL_M8B_BASE_DIST=<base build>/dist] \\
      uv run python -m pytest tests/e2e/test_m8b_canvas_benchmark.py -s

Measurements:
- continuous: requestAnimationFrame deltas while Playwright pans (Space + drag), zooms (wheel) and
  drags a node, at zoom 0.5 and 1.0 (viewport bookmarks 1 and 2);
- discrete: the Event Timing duration of the input event, which runs from the event to the next
  paint after its handlers. Chromium reports only events of 16 ms or more, so an operation without
  an entry is recorded as 16 ms, its upper bound;
- open: navigation start to the first frame with nodes mounted, the viewport fitted and the
  toolbar enabled;
- heap: CDP used JS heap after garbage collection, the top rung minus an empty Canvas;
- bundle: gzip sizes of the initial assets (index.html) and of the lazy Canvas chunk; the initial
  delta needs the base build;
- idle: rAF deltas of an empty, untouched Canvas, the environment's frame-time floor.

Frame-time verdicts are reported twice: strictly against the protocol thresholds, and with one
clock quantum (CLOCK_QUANTUM_MS) of tolerance, because the idle floor itself reaches 16.8 ms.

The result is written to docs/r2/evidence/R2_M8_B_CANVAS_BENCHMARK_RESULT.json.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import platform
import random
import socket
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Browser, FloatRect, Page, Route

sync_api = pytest.importorskip("playwright.sync_api", reason="uv sync (dev group)")

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
DIST = FRONTEND / "dist"
PROTOCOL = REPO_ROOT / "docs/r2/evidence/R2_M8_B_CANVAS_BENCHMARK_PROTOCOL.json"
RESULT = REPO_ROOT / "docs/r2/evidence/R2_M8_B_CANVAS_BENCHMARK_RESULT.json"
PROJECT = "bench"
CANDIDATE = "canvas-episode-1"
SEED = 20260929
DIGEST = "sha256:" + "0" * 64
# A 1x1 PNG: every referenced image resolves without touching the disk.
PIXEL = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360f8cfc0f01f0005000201a5f6450d0000000049454e44ae426082"
)
CANVAS_URL = f"/app/projects/{PROJECT}/episodes/1/canvas"
# Chromium coarsens performance.now() to 0.1 ms with jitter; idle rAF deltas at 60 Hz spread over
# 16.6-16.8 ms. The clock-tolerant verdict allows one quantum over a frame threshold.
CLOCK_QUANTUM_MS = 0.1

pytestmark = pytest.mark.timeout(3600)


# ─── graph generator ─────────────────────────────────────────────────────


def _node(node_id: str, node_type: str, body: dict[str, Any]) -> dict[str, Any]:
    return {"node_id": node_id, "node_type": node_type, "body": body}


def episode_graph(nodes: int, edges_count: int, seed: int = SEED) -> dict[str, Any]:
    """A deterministic, episode-shaped CanvasCandidate with the ladder rung's node and edge counts.

    Blocks of ten: one storyboard of four frames (hidden members drawn by the board), two beats,
    two clips and one note, chained beat -> frame -> clip. Remaining nodes are notes and audio
    references. Extra edges join random visible nodes, seeded.
    """
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []
    edges: list[tuple[str, str]] = []
    visible: list[str] = []
    block = 0
    while len(out) + 10 <= nodes:
        ox, oy = (block % 5) * 2400, (block // 5) * 1400
        group = f"g{block}"
        cell_w, cell_h = 320, 180
        out.append(
            _node(
                group,
                "group",
                {
                    "position": {"x": ox, "y": oy},
                    "style": {"width": cell_w * 2 + 44, "height": cell_h * 2 + 74},
                    "dragHandle": ".storyboard-handle",
                    "data": {
                        "label": f"Storyboard {block + 1}",
                        "storyboardGroup": True,
                        "storyboardAspect": "16:9",
                        "storyboardCols": 2,
                        "storyboardBaseWidth": cell_w,
                        "storyboardBaseHeight": cell_h,
                    },
                },
            )
        )
        visible.append(group)
        frames = [f"f{block}-{index}" for index in range(4)]
        for index, frame in enumerate(frames):
            out.append(
                _node(
                    frame,
                    "frame",
                    {
                        "position": {"x": 12 + (index % 2) * (cell_w + 8), "y": 34 + (index // 2) * (cell_h + 8)},
                        "style": {"width": cell_w, "height": cell_h},
                        "parentId": group,
                        "hidden": True,
                        "data": {"label": f"E1S{block * 4 + index + 1:02d}", "assetRef": f"storyboards/{frame}.png"},
                    },
                )
            )
        beats = [f"b{block}-{index}" for index in range(2)]
        clips = [f"c{block}-{index}" for index in range(2)]
        for index, beat in enumerate(beats):
            out.append(
                _node(
                    beat,
                    "beat",
                    {
                        "position": {"x": ox + 800, "y": oy + index * 420},
                        "data": {"label": f"Beat {block * 2 + index + 1}", "text": "A turn in the story."},
                    },
                )
            )
        for index, clip in enumerate(clips):
            out.append(
                _node(
                    clip,
                    "clip",
                    {
                        "position": {"x": ox + 1360, "y": oy + index * 420},
                        "data": {
                            "label": f"Clip {block * 2 + index + 1}",
                            "assetRef": f"videos/{clip}.mp4",
                            "thumbnailRef": f"thumbnails/{clip}.jpg",
                        },
                    },
                )
            )
        note = f"n{block}"
        out.append(_node(note, "note", {"position": {"x": ox + 1960, "y": oy}, "data": {"label": "Note", "text": ""}}))
        visible += [*beats, *clips, note]
        edges += [
            (beats[0], frames[0]),
            (beats[1], frames[2]),
            (frames[0], clips[0]),
            (frames[2], clips[1]),
            (beats[0], beats[1]),
            (note, beats[0]),
            (clips[0], clips[1]),
        ]
        block += 1
    extra = 0
    while len(out) < nodes:
        node_id = f"x{extra}"
        node_type = "audio" if extra % 2 else "note"
        body: dict[str, Any] = {
            "position": {"x": (extra % 8) * 520, "y": -800 - (extra // 8) * 360},
            "data": {"label": f"Extra {extra + 1}", "text": ""},
        }
        if node_type == "audio":
            body["data"]["assetRef"] = f"audio/{node_id}.wav"
        out.append(_node(node_id, node_type, body))
        visible.append(node_id)
        extra += 1
    target = edges_count
    seen = set(edges)
    while len(edges) < target:
        source, target_id = rng.sample(visible, 2)
        if (source, target_id) not in seen:
            seen.add((source, target_id))
            edges.append((source, target_id))
    edges = edges[:target]
    groups = [item for item in out if item["node_type"] == "group"]
    return {
        "kind": "CANVAS",
        "graph_schema_version": "1",
        "nodes": out,
        "edges": [
            {"edge_id": f"e{index}", "source_node_id": s, "target_node_id": t, "edge_type": "default", "body": {}}
            for index, (s, t) in enumerate(edges)
        ],
        "groups": [
            {
                "group_id": group["node_id"],
                "member_ids": [item["node_id"] for item in out if item["body"].get("parentId") == group["node_id"]],
                "storyboard": True,
            }
            for group in groups
        ],
        "storyboard_order": [item["node_id"] for item in out if item["body"].get("parentId")],
        "viewport_bookmarks": [
            {"slot": 0, "x": 0, "y": 0, "zoom": 0.5},
            {"slot": 1, "x": 0, "y": 0, "zoom": 1.0},
        ],
    }


# ─── mocked API ──────────────────────────────────────────────────────────

CONTEXT = {
    "lineage": {
        "project_name": PROJECT,
        "content_basis_digest": DIGEST,
        "approved_master_id": None,
        "approved_master_digest": None,
        "creative_profile_id": "arcreel.host",
        "creative_profile_version": "1",
        "policy_digest": DIGEST,
    },
    "created_by": "default",
}

PROJECT_BODY = {
    "project": {
        "title": "Benchmark",
        "content_mode": "narration",
        "style": "",
        "episodes": [{"episode": 1, "title": "Benchmark episode", "script_file": "scripts/episode_1.json"}],
    },
    "scripts": {},
}


@dataclass
class FakeApi:
    """Route handler for /api/v1/**: one Canvas candidate kept in memory."""

    payload: dict[str, Any] | None
    revision: int = 0
    appended: int = 0
    unknown: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.payload is not None:
            self.revision = 1

    def _revision_body(self) -> dict[str, Any]:
        return {
            "candidate_id": CANDIDATE,
            "revision": self.revision,
            "kind": "CANVAS",
            "parent_revision": None,
            "payload": self.payload,
            "payload_digest": DIGEST,
            "lineage": CONTEXT["lineage"],
            "created_by": "default",
            "created_at": "2026-09-30T00:00:00Z",
        }

    def handle(self, route: Route) -> None:
        request = route.request
        path = request.url.split("/api/v1", 1)[1].split("?", 1)[0]

        def reply(body: object, status: int = 200) -> None:
            route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

        if path.startswith("/files/"):
            route.fulfill(status=200, content_type="image/png", body=PIXEL)
        elif path == "/auth/status":
            reply({"enabled": False})
        elif path == f"/projects/{PROJECT}":
            reply(PROJECT_BODY)
        elif path == f"/projects/{PROJECT}/m8/exploration/context":
            reply(CONTEXT)
        elif path == f"/projects/{PROJECT}/m8/exploration/candidates/{CANDIDATE}":
            if self.revision == 0:
                reply({"detail": "not found"}, 404)
            else:
                reply({"candidate_id": CANDIDATE, "current_revision": self.revision, "head_version": self.revision})
        elif path.startswith(f"/projects/{PROJECT}/m8/exploration/candidates/{CANDIDATE}/revisions/"):
            reply(self._revision_body())
        elif path == f"/projects/{PROJECT}/m8/exploration/revisions" and request.method == "POST":
            body = json.loads(request.post_data or "{}")
            self.payload = body["candidate"]["payload"]
            self.revision += 1
            self.appended += 1
            reply({"candidate_id": CANDIDATE, "current_revision": self.revision, "head_version": self.revision})
        elif path.endswith("/events/stream"):
            route.fulfill(status=204, body="")
        else:
            self.unknown.add(f"{request.method} {path}")
            reply({"detail": "not available in the benchmark"}, 404)


# ─── servers and pages ───────────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def preview_url() -> Iterator[str]:
    if not (DIST / "index.html").is_file():
        pytest.skip("frontend/dist is missing; run (cd frontend && pnpm build)")
    port = _free_port()
    process = subprocess.Popen(
        ["pnpm", "exec", "vite", "preview", "--port", str(port), "--strictPort", "--host", "127.0.0.1"],
        cwd=FRONTEND,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("vite preview did not start")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_api.sync_playwright() as playwright:
        launched = playwright.chromium.launch()
        try:
            yield launched
        finally:
            launched.close()


# Installed before the app loads: frame recorder and open-to-interactive probe.
INIT_SCRIPT = """
(() => {
  const bench = { frames: null, openAt: null, events: [] };
  window.__bench = bench;
  const tick = (now) => {
    if (bench.frames) {
      if (bench.last !== undefined) bench.frames.push(now - bench.last);
      bench.last = now;
    }
    if (bench.openAt === null) {
      const viewport = document.querySelector('.react-flow__viewport');
      const fitted = viewport && viewport.style.transform && viewport.style.transform !== 'translate(0px, 0px) scale(1)';
      const nodes = document.querySelectorAll('.react-flow__node').length;
      const toolbar = document.querySelector('[role=toolbar] button');
      if ((window.__benchExpectEmpty || (fitted && nodes > 0)) && toolbar && !toolbar.disabled) bench.openAt = now;
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) bench.events.push({ name: entry.name, start: entry.startTime, duration: entry.duration });
  }).observe({ type: 'event', durationThreshold: 16, buffered: true });
  bench.startFrames = () => { bench.frames = []; bench.last = undefined; };
  bench.stopFrames = () => { const out = bench.frames || []; bench.frames = null; return out; };
})();
"""


def open_canvas(browser: Browser, base_url: str, api: FakeApi, *, expect_empty: bool = False) -> Page:
    context = browser.new_context(locale="en-US", viewport={"width": 1600, "height": 1000})
    context.add_init_script(INIT_SCRIPT)
    if expect_empty:
        context.add_init_script("window.__benchExpectEmpty = true;")
    context.route("**/api/v1/**", api.handle)
    page = context.new_page()
    page.goto(base_url + CANVAS_URL)
    page.wait_for_function("window.__bench && window.__bench.openAt !== null", timeout=30_000)
    return page


# ─── operations ──────────────────────────────────────────────────────────


def _now(page: Page) -> float:
    return float(page.evaluate("performance.now()"))


def _event_latency(page: Page, since: float, names: tuple[str, ...]) -> float:
    """The longest Event Timing duration of ``names`` since ``since``, or 16 ms (its reporting floor)."""
    page.evaluate("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    page.wait_for_timeout(50)
    entries = page.evaluate("(since) => window.__bench.events.filter((e) => e.start >= since)", since)
    durations = [float(entry["duration"]) for entry in entries if entry["name"] in names]
    return max(durations) if durations else 16.0


def _visible(page: Page, selector: str) -> Any:
    return page.locator(selector).filter(visible=True)


def _node_box(page: Page, node_id: str) -> FloatRect:
    box = page.locator(f'.react-flow__node[data-id="{node_id}"]').bounding_box()
    assert box is not None, node_id
    return box


def _selected_new_beat(page: Page) -> str:
    return str(page.locator(".react-flow__node.selected").first.get_attribute("data-id"))


def discrete_cycle(page: Page) -> dict[str, float]:
    """One repetition of every discrete operation of the protocol; returns ms per operation."""
    out: dict[str, float] = {}
    # Full detail (zoom 1.0, bookmark 2): text fields and handles are rendered.
    page.evaluate("document.activeElement instanceof HTMLElement && document.activeElement.blur()")
    page.keyboard.press("2")
    page.wait_for_timeout(250)
    t = _now(page)
    page.get_by_role("button", name="Add beat").click()
    out["add_node"] = _event_latency(page, t, ("pointerdown", "pointerup", "click"))
    node_id = _selected_new_beat(page)
    node = page.locator(f'.react-flow__node[data-id="{node_id}"]')

    title = node.get_by_role("textbox", name="Title")
    title.click()
    title.type("x")
    t = _now(page)
    page.keyboard.press("Tab")
    out["node_text_edit_commit"] = _event_latency(page, t, ("keydown",))

    others = [
        item
        for item in page.locator(".react-flow__node-beat, .react-flow__node-note").evaluate_all(
            "(els) => els.map((el) => el.dataset.id)"
        )
        if item != node_id
    ]
    target = others[0]
    source_handle = node.locator(".react-flow__handle.source").bounding_box()
    target_handle = page.locator(f'.react-flow__node[data-id="{target}"] .react-flow__handle.target').bounding_box()
    assert source_handle is not None
    assert target_handle is not None
    page.mouse.move(source_handle["x"] + 4, source_handle["y"] + 4)
    page.mouse.down()
    page.mouse.move(target_handle["x"] + 4, target_handle["y"] + 4, steps=4)
    t = _now(page)
    page.mouse.up()
    out["connect_edge"] = _event_latency(page, t, ("pointerup", "mouseup"))

    box = _node_box(page, node_id)
    page.mouse.click(box["x"] + 12, box["y"] + 10)
    other_box = _node_box(page, target)
    page.keyboard.down("Shift")
    page.mouse.click(other_box["x"] + 12, other_box["y"] + 10)
    page.keyboard.up("Shift")
    t = _now(page)
    page.get_by_role("button", name="Group", exact=True).click()
    grouped = _event_latency(page, t, ("pointerdown", "pointerup", "click"))
    t = _now(page)
    page.get_by_role("button", name="Ungroup").click()
    out["group_ungroup"] = max(grouped, _event_latency(page, t, ("pointerdown", "pointerup", "click")))

    page.evaluate("document.activeElement instanceof HTMLElement && document.activeElement.blur()")
    t = _now(page)
    page.keyboard.press("Control+z")
    undone = _event_latency(page, t, ("keydown",))
    t = _now(page)
    page.keyboard.press("Control+Shift+z")
    out["undo_redo"] = max(undone, _event_latency(page, t, ("keydown",)))

    box = _node_box(page, node_id)
    page.mouse.click(box["x"] + 12, box["y"] + 10)
    t = _now(page)
    page.keyboard.press("Delete")
    out["delete"] = _event_latency(page, t, ("keydown",))
    return out


def _frames(page: Page, action: Callable[[], None]) -> list[float]:
    page.evaluate("window.__bench.startFrames()")
    action()
    return [float(value) for value in page.evaluate("window.__bench.stopFrames()")]


def continuous_run(page: Page) -> dict[str, list[float]]:
    """Frame times of pan, zoom and node drag at zoom 0.5 and 1.0 (bookmarks 1 and 2)."""
    out: dict[str, list[float]] = {"pan": [], "zoom": [], "node_drag": []}
    pane = page.locator(".react-flow__renderer").bounding_box()
    assert pane is not None
    cx, cy = pane["x"] + pane["width"] / 2, pane["y"] + pane["height"] / 2
    for slot in ("1", "2"):
        page.evaluate("document.activeElement instanceof HTMLElement && document.activeElement.blur()")
        page.keyboard.press(slot)
        page.wait_for_timeout(400)

        def pan() -> None:
            page.keyboard.down("Space")
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.mouse.move(cx - 300, cy - 150, steps=40)
            page.mouse.move(cx, cy, steps=40)
            page.mouse.up()
            page.keyboard.up("Space")

        def zoom() -> None:
            page.mouse.move(cx, cy)
            for _ in range(15):
                page.mouse.wheel(0, -40)
                page.wait_for_timeout(16)
            for _ in range(15):
                page.mouse.wheel(0, 40)
                page.wait_for_timeout(16)

        out["pan"] += _frames(page, pan)
        out["zoom"] += _frames(page, zoom)
        page.keyboard.press(slot)
        page.wait_for_timeout(400)
        beat = _visible(page, ".react-flow__node-beat").first
        box = beat.bounding_box()
        assert box is not None

        def drag(start: FloatRect = box) -> None:
            page.mouse.move(start["x"] + 12, start["y"] + 10)
            page.mouse.down()
            page.mouse.move(start["x"] + 212, start["y"] + 110, steps=40)
            page.mouse.move(start["x"] + 12, start["y"] + 10, steps=40)
            page.mouse.up()

        out["node_drag"] += _frames(page, drag)
    return out


def _heap_mb(page: Page) -> float:
    cdp = page.context.new_cdp_session(page)
    cdp.send("HeapProfiler.collectGarbage")
    used = cdp.send("Runtime.getHeapUsage")["usedSize"]
    cdp.detach()
    return float(used) / (1024 * 1024)


# ─── statistics and bundle ───────────────────────────────────────────────


def nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100 * len(ordered)))
    return ordered[rank - 1]


def _summary(values: list[float]) -> dict[str, float | int]:
    return {"n": len(values), "p50": round(nearest_rank(values, 50), 2), "p95": round(nearest_rank(values, 95), 2)}


def _gzip_kb(path: Path) -> float:
    return len(gzip.compress(path.read_bytes(), compresslevel=9)) / 1024


def _initial_assets(dist: Path) -> set[Path]:
    html = (dist / "index.html").read_text(encoding="utf-8")
    refs: set[Path] = set()
    for marker in ('src="/', 'href="/'):
        for part in html.split(marker)[1:]:
            ref = part.split('"', 1)[0]
            if ref.endswith((".js", ".css")):
                refs.add(dist / ref)
    return refs


def bundle_report(dist: Path, base_dist: Path | None) -> dict[str, Any]:
    initial = sum(_gzip_kb(path) for path in _initial_assets(dist))
    canvas = [path for path in (dist / "assets").glob("CreativeCanvasPage-*") if path.suffix in (".js", ".css")]
    report: dict[str, Any] = {
        "initial_gzip_kb": round(initial, 2),
        "lazy_canvas_chunk_gzip_kb": round(sum(_gzip_kb(path) for path in canvas), 2),
        "lazy_canvas_chunk_files": sorted(path.name for path in canvas),
    }
    if base_dist is not None:
        base = sum(_gzip_kb(path) for path in _initial_assets(base_dist))
        report["base_initial_gzip_kb"] = round(base, 2)
        report["initial_delta_gzip_kb"] = round(initial - base, 2)
    return report


def _machine() -> dict[str, Any]:
    def read(command: list[str]) -> str:
        try:
            return subprocess.run(command, capture_output=True, text=True, check=False).stdout.strip()
        except OSError:
            return ""

    cpu = next((line.split(":", 1)[1].strip() for line in read(["lscpu"]).splitlines() if "Model name" in line), "")
    memory = next((line.split()[1] for line in read(["free", "-g"]).splitlines() if line.startswith("Mem:")), "")
    gpu = next((line for line in read(["lspci"]).splitlines() if "VGA" in line or "3D" in line), "")
    return {
        "cpu": cpu,
        "cores": os.cpu_count(),
        "ram_gb": memory,
        "gpu": gpu,
        "os": platform.platform(),
        "display_refresh_rate": "headless (no display)",
    }


# ─── the benchmark ───────────────────────────────────────────────────────


def test_canvas_meets_the_frozen_benchmark_protocol(preview_url: str, browser: Browser) -> None:
    if os.environ.get("ARCREEL_M8B_BENCHMARK") != "1":
        pytest.skip("set ARCREEL_M8B_BENCHMARK=1 to run the Canvas benchmark")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    thresholds = protocol["thresholds"]
    cycles = int(os.environ.get("ARCREEL_M8B_CYCLES", "10"))
    runs = int(os.environ.get("ARCREEL_M8B_RUNS", "3"))
    rungs: list[dict[str, Any]] = []
    unknown: set[str] = set()
    failures: list[str] = []
    strict_only: list[str] = []
    idle: list[float] = []

    for rung in protocol["ladder"]:
        size = int(rung["nodes"])
        discrete: dict[str, list[float]] = {}
        continuous: dict[str, list[float]] = {}
        opens: list[float] = []
        for _ in range(runs):
            idle_page = open_canvas(browser, preview_url, FakeApi(None), expect_empty=True)
            idle += _frames(idle_page, lambda page=idle_page: page.wait_for_timeout(2000))
            idle_page.context.close()
            api = FakeApi(episode_graph(size, int(rung["edges"])))
            page = open_canvas(browser, preview_url, api)
            opens.append(float(page.evaluate("window.__bench.openAt")))
            for _ in range(cycles):
                for name, value in discrete_cycle(page).items():
                    discrete.setdefault(name, []).append(value)
            for name, values in continuous_run(page).items():
                continuous.setdefault(name, []).extend(values)
            unknown |= api.unknown
            page.context.close()
        frame_limit = thresholds["continuous_interaction_frame_time_p95_ms"][
            "top_rung" if size == protocol["ladder"][-1]["nodes"] else "up_to_200_nodes"
        ]
        row: dict[str, Any] = {
            "nodes": size,
            "edges": int(rung["edges"]),
            "open_ms": _summary(opens),
            "discrete_ms": {name: _summary(values) for name, values in discrete.items()},
            "continuous_frame_ms": {name: _summary(values) for name, values in continuous.items()},
            "frame_limit_ms": frame_limit,
        }
        for name, values in discrete.items():
            if len(values) < 30 or nearest_rank(values, 95) > thresholds["discrete_operation_latency_p95_ms"]:
                failures.append(f"{size} nodes: discrete {name} {_summary(values)}")
        for name, values in continuous.items():
            p95 = nearest_rank(values, 95)
            if len(values) < 30 or p95 > frame_limit + CLOCK_QUANTUM_MS:
                failures.append(f"{size} nodes: continuous {name} {_summary(values)}")
            elif p95 > frame_limit:
                strict_only.append(f"{size} nodes: continuous {name} {_summary(values)}")
        rungs.append(row)

    top = int(protocol["ladder"][-1]["nodes"])
    top_open = rungs[-1]["open_ms"]["p95"]
    if top_open > thresholds["top_rung_open_to_interactive_ms"]:
        failures.append(f"open to interactive p95 {top_open} ms at {top} nodes")

    empty = open_canvas(browser, preview_url, FakeApi(None), expect_empty=True)
    empty_heap = _heap_mb(empty)
    empty.context.close()
    full = open_canvas(browser, preview_url, FakeApi(episode_graph(top, int(protocol["ladder"][-1]["edges"]))))
    full_heap = _heap_mb(full)
    full.context.close()
    canvas_heap = round(full_heap - empty_heap, 2)
    if canvas_heap > thresholds["top_rung_canvas_js_heap_mb"]:
        failures.append(f"canvas heap {canvas_heap} MB")

    low_end_rung = 100
    low_end: dict[str, list[float]] = {}
    low = open_canvas(browser, preview_url, FakeApi(episode_graph(low_end_rung, 150)))
    cdp = low.context.new_cdp_session(low)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
    for _ in range(max(30, cycles)):
        for name, value in discrete_cycle(low).items():
            low_end.setdefault(name, []).append(value)
    low.context.close()
    for name, values in low_end.items():
        if nearest_rank(values, 95) > thresholds["discrete_operation_latency_p95_ms"]:
            failures.append(f"low-end {low_end_rung} nodes: discrete {name} {_summary(values)}")

    base_dist = os.environ.get("ARCREEL_M8B_BASE_DIST")
    bundle = bundle_report(DIST, Path(base_dist) if base_dist else None)
    if bundle["lazy_canvas_chunk_gzip_kb"] > thresholds["bundle"]["lazy_canvas_chunk_max_kb_gzip"]:
        failures.append(f"lazy canvas chunk {bundle['lazy_canvas_chunk_gzip_kb']} KB")
    if "initial_delta_gzip_kb" not in bundle:
        failures.append("initial bundle delta not measured (ARCREEL_M8B_BASE_DIST unset)")
    elif bundle["initial_delta_gzip_kb"] > thresholds["bundle"]["initial_app_bundle_delta_kb_gzip"]:
        failures.append(f"initial bundle delta {bundle['initial_delta_gzip_kb']} KB")

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    RESULT.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "protocol_sha256": _sha256_file(PROTOCOL),
                "head": head.stdout.strip(),
                "status": "PASS" if not failures else "FAIL",
                "status_strict": "PASS" if not failures and not strict_only else "FAIL",
                "status_clock_tolerant": "PASS" if not failures else "FAIL",
                "clock_quantum_ms": CLOCK_QUANTUM_MS,
                "failures": failures,
                "strict_only_failures": strict_only,
                "idle_frame_ms": _summary(idle),
                "machine": _machine(),
                "browser": browser.version,
                "runs": runs,
                "cycles_per_run": cycles,
                "rungs": rungs,
                "top_rung_heap_mb": {
                    "empty_canvas": round(empty_heap, 2),
                    "top_rung": round(full_heap, 2),
                    "canvas": canvas_heap,
                },
                "low_end": {
                    "cpu_throttling_rate": 4,
                    "nodes": low_end_rung,
                    "discrete_ms": {k: _summary(v) for k, v in low_end.items()},
                },
                "bundle": bundle,
                "event_timing_floor_ms": 16,
                "unmocked_requests": sorted(unknown),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    assert not failures, failures


def _sha256_file(path: Path) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_graph_generator_is_deterministic_and_sized_by_the_protocol() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    for rung in protocol["ladder"]:
        graph = episode_graph(int(rung["nodes"]), int(rung["edges"]))
        assert len(graph["nodes"]) == rung["nodes"]
        assert len(graph["edges"]) == rung["edges"]
        ids = {node["node_id"] for node in graph["nodes"]}
        assert all(edge["source_node_id"] in ids and edge["target_node_id"] in ids for edge in graph["edges"])
        assert len({(edge["source_node_id"], edge["target_node_id"]) for edge in graph["edges"]}) == len(graph["edges"])
    assert episode_graph(100, 150) == episode_graph(100, 150)
