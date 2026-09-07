#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from r2.bootstrap import r2_root


class BaselineError(RuntimeError):
    pass


REQUIRED_KEYS = {"upstream", "tag", "sha", "branch"}


def parse_baseline(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise BaselineError(f"invalid baseline line: {raw!r}")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    missing = REQUIRED_KEYS - values.keys()
    if missing:
        raise BaselineError(f"missing baseline keys: {sorted(missing)}")
    return values


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
    )
    if proc.returncode:
        raise BaselineError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def verify_repository(
    repo: Path,
    cfg: dict[str, str],
    *,
    check_remote: bool = True,
) -> None:
    actual_branch = _git(repo, "branch", "--show-current")
    if actual_branch != cfg["branch"]:
        raise BaselineError(f"branch mismatch: expected {cfg['branch']}, got {actual_branch}")

    tag_sha = _git(repo, "rev-parse", f"{cfg['tag']}^{{commit}}")
    if tag_sha != cfg["sha"]:
        raise BaselineError(f"tag {cfg['tag']} mismatch: expected {cfg['sha']}, got {tag_sha}")

    head = _git(repo, "rev-parse", "HEAD")
    merge_base = _git(repo, "merge-base", head, cfg["sha"])
    if merge_base != cfg["sha"]:
        raise BaselineError(f"pinned baseline {cfg['sha']} is not an ancestor of HEAD {head}")

    if check_remote:
        upstream = _git(repo, "remote", "get-url", "upstream")
        if upstream != cfg["upstream"]:
            raise BaselineError(f"upstream mismatch: expected {cfg['upstream']}, got {upstream}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--baseline",
        type=Path,
        default=r2_root() / "docs" / "r2" / "HOST_BASELINE.txt",
    )
    parser.add_argument("--no-remote-check", action="store_true")
    args = parser.parse_args()

    cfg = parse_baseline(args.baseline)
    verify_repository(
        r2_root(),
        cfg,
        check_remote=not args.no_remote_check,
    )
    print(f"R2 host baseline verification: PASS (tag={cfg['tag']} sha={cfg['sha']} branch={cfg['branch']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
