#!/usr/bin/env python3
"""Verify exact-version provider evidence; never call a provider or enable routes."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from r2.host_hardening.compatibility import CompatibilityError, verify_provider_qualification


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--evidence-repo", type=Path, required=True)
    parser.add_argument("--now", type=datetime.fromisoformat, default=datetime.now(UTC))
    parser.add_argument("--enable-production", action="store_true")
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text())
        verdict = verify_provider_qualification(
            report,
            registry_path=args.registry,
            evidence_repo=args.evidence_repo,
            now=args.now,
            enable_production=args.enable_production,
        )
    except (CompatibilityError, OSError, ValueError) as exc:
        print(json.dumps({"verdict": "REJECTED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"verdict": verdict}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
