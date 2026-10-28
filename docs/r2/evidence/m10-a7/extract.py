"""Extract exact pinned Kalinga function sources into a JSON fixture (bytes from git, never the worktree)."""
import ast, hashlib, json, subprocess, sys

DONOR = "/home/anhtuan/Kalinga-Shorts-Factory"
PIN = "e4b5a2173ca03d365aad565a89fcc43159b44f9b"
SELECTED = {
    "pipeline/src/validate.py": ["tech_qc", "parse_virality", "virality_gate"],
    "pipeline/src/make_video.py": ["sh", "ffprobe_duration", "_safe_validate"],
}
RUN_OK_LINE = 159  # validate.run combined verdict

def blob(path):
    return subprocess.check_output(["git", "-C", DONOR, "show", f"{PIN}:{path}"])

out = {"schema_id": "m10.a7-kalinga-donor-functions.v1", "repository_url": "https://github.com/desaultkhan/Kalinga-Shorts-Factory",
       "commit_sha": PIN, "files": {}, "functions": []}
for path, names in SELECTED.items():
    raw = blob(path)
    out["files"][path] = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)
    found = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in names:
        node = found[name]
        src = "".join(lines[node.lineno - 1 : node.end_lineno])
        out["functions"].append({"path": path, "name": name, "lineno": node.lineno, "end_lineno": node.end_lineno,
                                 "sha256": hashlib.sha256(src.encode()).hexdigest(), "source": src})
    if path.endswith("validate.py"):
        ok = lines[RUN_OK_LINE - 1]
        assert ok.strip() == 'ok = not qc and vir["status"] != "weak" and not seo', ok
        out["run_ok_expression"] = {"path": path, "lineno": RUN_OK_LINE, "source": ok.strip(),
                                    "sha256": hashlib.sha256(ok.strip().encode()).hexdigest()}
json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print({f["name"]: f["sha256"][:12] for f in out["functions"]}, out["files"])
