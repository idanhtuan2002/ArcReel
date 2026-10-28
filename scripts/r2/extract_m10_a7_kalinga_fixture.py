"""Extract the exact pinned Kalinga function sources into the M10-A7 donor fixture.

Bytes come from Git objects at the pin, never from the donor working tree.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path

PIN = "e4b5a2173ca03d365aad565a89fcc43159b44f9b"
REPOSITORY_URL = "https://github.com/desaultkhan/Kalinga-Shorts-Factory"
SELECTED = {
    "pipeline/src/validate.py": ("tech_qc", "parse_virality", "virality_gate"),
    "pipeline/src/make_video.py": ("sh", "ffprobe_duration", "_safe_validate"),
}
RUN_OK = ("pipeline/src/validate.py", 159, 'ok = not qc and vir["status"] != "weak" and not seo')


def _sha(text: str | bytes) -> str:
    return hashlib.sha256(text.encode("utf-8") if isinstance(text, str) else text).hexdigest()


def extract(donor: Path) -> dict[str, object]:
    files: dict[str, str] = {}
    functions: list[dict[str, object]] = []
    run_ok: dict[str, object] = {}
    for path, names in SELECTED.items():
        raw = subprocess.run(["git", "-C", str(donor), "show", f"{PIN}:{path}"], capture_output=True, check=True).stdout
        files[path] = _sha(raw)
        text = raw.decode("utf-8")
        lines = text.splitlines(keepends=True)
        found = {node.name: node for node in ast.parse(text).body if isinstance(node, ast.FunctionDef)}
        for name in names:
            node = found[name]
            source = "".join(lines[node.lineno - 1 : node.end_lineno])
            functions.append(
                {
                    "path": path,
                    "name": name,
                    "lineno": node.lineno,
                    "end_lineno": node.end_lineno,
                    "sha256": _sha(source),
                    "source": source,
                }
            )
        if path == RUN_OK[0]:
            line = lines[RUN_OK[1] - 1].strip()
            if line != RUN_OK[2]:
                raise SystemExit("pinned run() verdict expression moved")
            run_ok = {"path": path, "lineno": RUN_OK[1], "source": line, "sha256": _sha(line)}
    return {
        "schema_id": "m10.a7-kalinga-donor-functions.v1",
        "repository_url": REPOSITORY_URL,
        "commit_sha": PIN,
        "files": files,
        "functions": functions,
        "run_ok_expression": run_ok,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--donor", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.write_text(json.dumps(extract(args.donor), indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
