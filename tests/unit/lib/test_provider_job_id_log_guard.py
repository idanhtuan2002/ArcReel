"""Provider backends never pass a raw provider job identifier to a logger.

In provider backend modules, ``task_id`` / ``job_id`` / ``op_name`` /
``operation_name`` name the provider-side job; log lines must use
``job_ref_for_log(...)`` (the HMAC reference) instead. ``lib/video_backends/base.py``
is excluded because its ``task_id`` is the ArcReel queue task, not a provider job.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_BACKEND_DIRS = ("lib/video_backends", "lib/image_backends", "lib/audio_backends", "lib/custom_provider")
_QUEUE_TASK_MODULES = {"lib/video_backends/base.py"}
_PROVIDER_ID_NAMES = {"task_id", "job_id", "op_name", "operation_name", "provider_job_id"}
_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def _backend_modules() -> list[Path]:
    modules = [path for directory in _BACKEND_DIRS for path in sorted((_REPO / directory).rglob("*.py"))]
    return [path for path in modules if path.relative_to(_REPO).as_posix() not in _QUEUE_TASK_MODULES]


def _raw_id_arguments(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _LOG_METHODS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
        ):
            continue
        offenders.extend(
            f"{path.relative_to(_REPO).as_posix()}:{node.lineno}:{argument.id}"
            for argument in node.args[1:]
            if isinstance(argument, ast.Name) and argument.id in _PROVIDER_ID_NAMES
        )
    return offenders


@pytest.mark.parametrize("module", _backend_modules(), ids=lambda path: path.relative_to(_REPO).as_posix())
def test_backend_logs_use_job_references(module: Path) -> None:
    assert _raw_id_arguments(module) == []
