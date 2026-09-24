#!/usr/bin/env python3
"""Verify a pinned M7-E upstream report without modifying either repository."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from r2.host_hardening.compatibility import CompatibilityError, verify_upstream_candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--host-repo", type=Path, required=True)
    parser.add_argument("--upstream-repo", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text())
        verdict = verify_upstream_candidate(report, host_repo=args.host_repo, upstream_repo=args.upstream_repo)
    except (CompatibilityError, OSError, ValueError) as exc:
        print(json.dumps({"verdict": "INCOMPATIBLE", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"verdict": verdict}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
