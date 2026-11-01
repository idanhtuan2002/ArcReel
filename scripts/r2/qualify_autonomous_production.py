"""Drive one automatic production run through the public API and print its acceptance evidence.

It reads the start offer, starts the run with a new idea, polls the run until it is terminal or waits for review
(a semi checkpoint is reported, never approved here), and prints a redacted JSON record: the source HEAD, the run's
policy digest and status history, the final snapshot's outcomes, completed targets and timings. It never fabricates a
pass: the record states exactly the status the server reports, and the exit code is 0 only for SUCCEEDED.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import uuid
from collections.abc import Callable

import httpx

TERMINAL = {"SUCCEEDED", "FAILED", "FAILED_QUALITY", "CANCELLED"}
STOPPED = {
    "WAITING_REVIEW",
    "PAUSED",
    "BLOCKED_INPUT_CHANGED",
    "BLOCKED_CONFIGURATION",
    "BLOCKED_BUDGET",
    "BLOCKED_RESOURCE",
    "BLOCKED_UNKNOWN",
}


def source_head() -> str:
    completed = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return completed.stdout.strip() or "unknown"


def run_once(
    client: httpx.Client,
    *,
    project: str,
    idea: str,
    mode: str,
    poll_seconds: float,
    timeout_seconds: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    base = f"/api/v1/projects/{project}/production-runs"
    offer = client.get(base).raise_for_status().json()["start"]
    if not offer.get("enabled"):
        return {"started": False, "reason": offer.get("reason")}
    started = clock()
    run = (
        client.post(
            base,
            json={
                "command_id": f"qualify-{uuid.uuid4()}",
                "mode": mode,
                "idea": idea,
                "expected_input_digest": offer["input_digest"],
                "policy_digest": offer["policy_digests"][mode],
            },
        )
        .raise_for_status()
        .json()
    )
    history = [{"t": 0.0, "stage": run["stage"], "status": run["status"]}]
    while run["status"] not in TERMINAL | STOPPED and clock() - started < timeout_seconds:
        sleep(poll_seconds)
        run = client.get(f"{base}/{run['run_id']}").raise_for_status().json()
        last = history[-1]
        if (last["stage"], last["status"]) != (run["stage"], run["status"]):
            history.append({"t": round(clock() - started, 1), "stage": run["stage"], "status": run["status"]})
    return {
        "started": True,
        "run_id": run["run_id"],
        "policy_digest": run["policy_digest"],
        "input_digest": run["input_digest"],
        "status": run["status"],
        "stage": run["stage"],
        "reason": run.get("reason"),
        "generation": run["generation"],
        "final_evaluations": run.get("final_evaluations"),
        "repair_counts": run.get("repair_counts"),
        "completed_targets": run.get("completed_targets"),
        "elapsed_seconds": round(clock() - started, 1),
        "history": history,
        "timed_out": run["status"] not in TERMINAL | STOPPED,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", required=True, help="an interactive Showrunner session token")
    parser.add_argument("--project", required=True)
    parser.add_argument("--idea", required=True)
    parser.add_argument("--mode", choices=("auto", "semi"), default="auto")
    parser.add_argument("--poll-seconds", type=float, default=30)
    parser.add_argument("--timeout-seconds", type=float, default=6 * 3600)
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, headers={"Authorization": f"Bearer {args.token}"}, timeout=60) as client:
        record = run_once(
            client,
            project=args.project,
            idea=args.idea,
            mode=args.mode,
            poll_seconds=args.poll_seconds,
            timeout_seconds=args.timeout_seconds,
        )
    print(json.dumps({"source_head": source_head(), **record}, ensure_ascii=False, indent=2))
    return 0 if record.get("status") == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
