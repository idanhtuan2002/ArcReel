"""Real Remotion-backed rendering (M3 real-media closure Task 3).

Replaces the solid-color FFmpeg stub previously in ``local_production.py``.
Mirrors the existing ``composition.py``/``local_production.py`` subprocess
pattern exactly (a synchronous ``subprocess.run`` call, an ``ffprobe`` for
duration, a sha256/execution-fingerprint pair) -- this module owns no new
async surface, no shared tool framework, nothing beyond what a real
``npx remotion render`` invocation needs.

A ``video_passthrough`` cut's source is staged into the vendored project's
own ``public/`` directory and referenced by a relative path (Remotion's
``staticFile()`` convention), not passed as a raw absolute ``file://`` path.
Chrome's headless renderer refuses to load local ``file://`` resources at
all (confirmed this session: "Not allowed to load local resource") even
though ``resolveAsset.ts`` happily constructs that URL -- ``resolveAsset``'s
absolute-path branch is real donor code for its own (browser, non-headless)
Studio preview mode, not for the CLI ``render`` path this module drives.
Staging is scoped to a per-call unique subdirectory and always removed
afterward (success or failure) so no render ever leaves a leftover file
under the vendored ``public/`` tree.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from r2.contracts.enums import ProductionMethod

from .render_plan import RenderCut, RenderedCutAsset

DEFAULT_REMOTION_PROJECT = Path(__file__).resolve().parents[2] / "vendor" / "openmontage" / "remotion-composer"
_COMPOSITION_ID = "Explainer"
_ENTRY_POINT = "src/index.tsx"
_STAGING_DIRNAME = "_r2_runtime_staging"

_KIND_TO_METHOD = {
    "video_passthrough": ProductionMethod.REUSE,
    "text_card": ProductionMethod.DETERMINISTIC,
    "stat_card": ProductionMethod.DETERMINISTIC,
}


def _ensure_npm_dependencies(remotion_project: Path) -> None:
    """Install once, lazily, on first real use -- callers (tests, a future
    real production path) must not need to remember a separate `npm install`
    step or a matching pytest fixture; a fixture scoped to one test
    directory silently misses any other test file that reaches this module
    (a real gap found this session: tests/fixtures/r2/m6_dual_profile_corpus.py
    calls into this engine from outside tests/integration/r2/m3/).
    """
    if (remotion_project / "node_modules").is_dir():
        return
    subprocess.run(["npm", "install"], cwd=remotion_project, check=True, capture_output=True, text=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remotion_version(remotion_project: Path) -> str:
    # `remotion --version` is not a real subcommand -- it prints the CLI's
    # own version as a courtesy alongside full usage help, then exits 1 (an
    # unrecognized-flag error). `remotion versions` is the real subcommand:
    # exits 0 and prints "On version: X.Y.Z" first.
    result = subprocess.run(
        ["npx", "remotion", "versions"],
        cwd=remotion_project,
        check=True,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("On version:"):
            return line.removeprefix("On version:").strip()
    raise RuntimeError(f"could not parse remotion version from: {result.stdout!r}")


@contextmanager
def _staged_source(source_path: Path, *, remotion_project: Path) -> Generator[str]:
    """Copy ``source_path`` into a unique subdirectory of the project's
    ``public/`` folder for the duration of one render, yielding the relative
    path Remotion's ``staticFile()`` resolves it by. Always removed on exit.
    """
    staging_root = remotion_project / "public" / _STAGING_DIRNAME / uuid.uuid4().hex
    staging_root.mkdir(parents=True)
    try:
        staged_path = staging_root / source_path.name
        shutil.copy2(source_path, staged_path)
        yield f"{_STAGING_DIRNAME}/{staging_root.name}/{source_path.name}"
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def _cut_to_remotion_json(cut: RenderCut, *, staged_source_relpath: str | None) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": cut.cut_id,
        "in_seconds": cut.in_seconds,
        "out_seconds": cut.out_seconds,
    }
    if cut.kind == "video_passthrough":
        if staged_source_relpath is None:
            raise ValueError(f"{cut.cut_id}: video_passthrough requires a staged source")
        payload["source"] = staged_source_relpath
    elif cut.kind in ("text_card", "stat_card"):
        if cut.text is None:
            raise ValueError(f"{cut.cut_id}: {cut.kind} requires text")
        payload["type"] = cut.kind
        payload["text"] = cut.text
    else:
        raise ValueError(f"{cut.cut_id}: unknown RenderCut.kind {cut.kind!r}")

    if cut.subtitle is not None:
        payload["subtitle"] = cut.subtitle
    if cut.background_color is not None:
        payload["backgroundColor"] = cut.background_color
    return payload


class RemotionRenderError(RuntimeError):
    """``remotion render`` failed; the message carries the tail of its output."""


def _run_render(remotion_project: Path, output_path: Path, props: dict[str, object]) -> float:
    start = time.perf_counter()
    result = subprocess.run(
        [
            "npx",
            "remotion",
            "render",
            _ENTRY_POINT,
            _COMPOSITION_ID,
            str(output_path.resolve()),
            f"--props={json.dumps(props, separators=(',', ':'))}",
        ],
        cwd=remotion_project,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # The render's own output is the only diagnosis (bundler, Chrome, disk); keep its tail.
        tail = "\n".join((result.stderr or result.stdout or "").strip().splitlines()[-20:])
        raise RemotionRenderError(f"remotion render exited {result.returncode} for {output_path.name}:\n{tail}")
    return time.perf_counter() - start


def render_cut(
    cut: RenderCut,
    *,
    remotion_project: Path = DEFAULT_REMOTION_PROJECT,
    output_path: Path,
) -> RenderedCutAsset:
    """Render exactly one cut as the sole segment of its own output file."""
    _ensure_npm_dependencies(remotion_project)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tool_version = _remotion_version(remotion_project)

    # The fingerprint identifies a cut by the *content* it renders, never by
    # the disposable per-call staging path -- two calls passing the same
    # logical source must fingerprint identically, matching their actually
    # byte-identical rendered output (verified this session).
    fingerprint_cut_json: dict[str, object]

    if cut.kind == "video_passthrough":
        if cut.source_path is None:
            raise ValueError(f"{cut.cut_id}: video_passthrough requires source_path")
        if not cut.source_path.is_file():
            raise FileNotFoundError(cut.source_path)
        source_digest = _sha256(cut.source_path)
        fingerprint_cut_json = _cut_to_remotion_json(cut, staged_source_relpath=f"sha256:{source_digest}")
        with _staged_source(cut.source_path, remotion_project=remotion_project) as staged_relpath:
            cut_json = _cut_to_remotion_json(cut, staged_source_relpath=staged_relpath)
            props = {"cuts": [cut_json], "overlays": [], "captions": [], "audio": {}}
            wall = _run_render(remotion_project, output_path, props)
    else:
        cut_json = _cut_to_remotion_json(cut, staged_source_relpath=None)
        fingerprint_cut_json = cut_json
        props = {"cuts": [cut_json], "overlays": [], "captions": [], "audio": {}}
        wall = _run_render(remotion_project, output_path, props)

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    duration = float(probe.stdout.strip())

    fingerprint_payload = {
        "tool": "remotion",
        "tool_version": tool_version,
        "composition": _COMPOSITION_ID,
        "props": {"cuts": [fingerprint_cut_json], "overlays": [], "captions": [], "audio": {}},
    }
    execution_fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    source_master_refs: tuple[str, ...] = ()
    if cut.kind == "video_passthrough" and cut.source_path is not None:
        source_master_refs = (f"{cut.cut_id}:{_sha256(cut.source_path)}",)

    return RenderedCutAsset(
        target_ref=cut.cut_id,
        method=_KIND_TO_METHOD[cut.kind],
        path=output_path,
        sha256=_sha256(output_path),
        duration_seconds=duration,
        execution_fingerprint=execution_fingerprint,
        tool="remotion",
        tool_version=tool_version,
        wall_time_seconds=wall,
        external_provider_cost=Decimal("0"),
        source_master_refs=source_master_refs,
    )


__all__ = ["DEFAULT_REMOTION_PROJECT", "RemotionRenderError", "render_cut"]
