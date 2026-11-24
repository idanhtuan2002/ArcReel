"""Review post-stage, report only (ASSEMBLY_PLAN M4.2): DramaClaw's own verifiers on a finished episode.

Called on demand after compose; nothing is regenerated (rework needs the sponsor's approval of its cost). DramaClaw's
verifiers use its default model (`MODEL_NAME`, set to `DC-verifier-LLM` in `assembly/deploy/dramaclaw/override.yml`).

`python -m assembly.review --state ~/assembly-data/runs/<project>.json [--episode 1]`
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from assembly.connector.dramaclaw_tools import DramaClawTools
from assembly.connector.film import RunState

# (key, Vietnamese label, verifier path under the episode, body)
CHECKS: list[tuple[str, str, str, dict[str, Any]]] = [
    ("overview", "Duyệt toàn tập (góc nhìn đạo diễn)", "verify/episode-overview", {}),
    ("consistency", "Nhân vật nhất quán trên khung hình", "verify/consistency", {"verify_type": "frame"}),
    ("continuity", "Mạch truyện giữa các beat liền kề", "verify/continuity", {}),
]
TRANSIENT = ("503", "429", "high demand", "temporarily", "Rate limit")
PAUSES = (60, 180)


def run_check(
    request: Callable[..., dict[str, Any]],
    project_id: str,
    episode: int,
    path: str,
    body: dict[str, Any],
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """One verifier call; transient model errors are retried after a pause."""
    result: dict[str, Any] = {}
    for pause in (*PAUSES, None):
        result = request("POST", f"/projects/{project_id}/episodes/{episode}/{path}", body=body)
        error = str(result.get("error") or "")
        if result.get("ok") or pause is None or not any(mark in error for mark in TRANSIENT):
            break
        sleep(pause)
    data = result.get("data") or {}
    return {
        "ok": bool(result.get("ok")),
        "error": str(result.get("error") or "")[:500],
        "passed": data.get("passed", data.get("overall_passed")),
        "report": str(data.get("report_text") or "")[:6000],
        "report_path": data.get("report_path"),
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def review_episode(request: Callable[..., dict[str, Any]], project_id: str, episode: int) -> dict[str, Any]:
    return {
        key: {"label": label, **run_check(request, project_id, episode, path, body)}
        for key, label, path, body in CHECKS
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m assembly.review")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--episode", type=int, default=1)
    args = parser.parse_args(argv)
    state = RunState.load(args.state)
    tools = DramaClawTools(state.project_id)
    result = review_episode(tools.request, state.project_id, args.episode)
    state = RunState.load(args.state)
    state.reviews[str(args.episode)] = result
    state.save(args.state)
    for key, item in result.items():
        print(f"REVIEW {key}: ok={item['ok']} passed={item['passed']} {item['error'][:200]}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
