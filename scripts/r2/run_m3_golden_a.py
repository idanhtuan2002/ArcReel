from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from r2.m3.golden_a import GoldenARunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Run R2-M3 Golden A end-to-end.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-copy", type=Path)
    args = parser.parse_args()

    result = GoldenARunner().run(args.output)
    if args.evidence_copy is not None:
        args.evidence_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result.evidence_path, args.evidence_copy)

    print(
        json.dumps(
            {
                "final_path": str(result.final_path),
                "final_sha256": result.final_sha256,
                "duration_seconds": result.final_duration_seconds,
                "methods": [method.value for method in result.methods],
                "external_provider_cost": str(result.external_provider_cost),
                "invalidation": result.invalidation,
                "restart_verified": result.restart_verified,
                "evidence_path": str(result.evidence_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
