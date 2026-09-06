from pathlib import Path


def r2_root() -> Path:
    return Path(__file__).resolve().parents[1]


def frozen_docs_dir() -> Path:
    return r2_root() / "docs" / "r2"
