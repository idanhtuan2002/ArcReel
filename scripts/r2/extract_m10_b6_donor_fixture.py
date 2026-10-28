"""Extract the exact pinned donor sources for the M10-B6 packaging/export parity fixture.

Bytes come from Git objects at each pin, never from a donor working tree: Kalinga `seo_lint` and the
OpenMontage `ExportBundle` chapter/layout methods.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path

DONORS = {
    "kalinga": {
        "repository_url": "https://github.com/desaultkhan/Kalinga-Shorts-Factory",
        "commit_sha": "e4b5a2173ca03d365aad565a89fcc43159b44f9b",
        "selected": {"pipeline/src/validate.py": ("seo_lint",)},
    },
    "openmontage": {
        "repository_url": "https://github.com/calesthio/OpenMontage",
        "commit_sha": "08e2151fa02de28a5d6a312b3d575692bf147ad7",
        "selected": {"tools/publishers/export_bundle.py": ("_format_chapter_time", "_chapter_lines", "execute")},
    },
}


def _sha(data: str | bytes) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _definitions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    found: dict[str, ast.FunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            found[node.name] = node
        elif isinstance(node, ast.ClassDef):
            found.update({child.name: child for child in node.body if isinstance(child, ast.FunctionDef)})
    return found


def extract(roots: dict[str, Path]) -> dict[str, object]:
    donors: dict[str, object] = {}
    for key, donor in DONORS.items():
        files: dict[str, str] = {}
        functions: list[dict[str, object]] = []
        for path, names in donor["selected"].items():
            raw = subprocess.run(
                ["git", "-C", str(roots[key]), "show", f"{donor['commit_sha']}:{path}"], capture_output=True, check=True
            ).stdout
            files[path] = _sha(raw)
            text = raw.decode("utf-8")
            lines = text.splitlines(keepends=True)
            found = _definitions(ast.parse(text))
            for name in names:
                node = found[name]
                start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
                source = "".join(lines[start - 1 : node.end_lineno])
                functions.append(
                    {
                        "path": path,
                        "name": name,
                        "lineno": start,
                        "end_lineno": node.end_lineno,
                        "sha256": _sha(source),
                        "source": source,
                    }
                )
        donors[key] = {
            "repository_url": donor["repository_url"],
            "commit_sha": donor["commit_sha"],
            "files": files,
            "functions": functions,
        }
    return {"schema_id": "m10.b6-donor-functions.v1", "donors": donors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kalinga", type=Path, required=True)
    parser.add_argument("--openmontage", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    body = extract({"kalinga": args.kalinga, "openmontage": args.openmontage})
    args.out.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
