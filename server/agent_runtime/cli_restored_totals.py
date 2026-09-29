"""The cumulative totals the Claude CLI restores into a resumed process (ADR-0093).

When the CLI resumes a session, it restores that session's final cost and model usage from its
global config, but only when the resumed id is the ``lastSessionId`` stored there. The CLI writes
that entry on a graceful exit. This module reads the same file and applies the same rule, so the
host knows before the process starts which totals its first result will already include.

The config file is resolved as the bundled CLI resolves it:

- ``<config home>/.config.json`` if it exists;
- otherwise ``.claude.json`` in ``CLAUDE_CONFIG_DIR`` or the home directory.

``<config home>`` is ``CLAUDE_CONFIG_DIR`` or ``~/.claude``. The file is keyed by project path; a
session id is a UUID, so the entry holding it is found by value, without re-deriving the CLI's key.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from server.agent_runtime.usage_extraction import extract_model_usage_tokens

_CUSTOM_OAUTH_ENV = "CLAUDE_CODE_CUSTOM_OAUTH_URL"


@dataclass(frozen=True)
class RestoredTotals:
    cost_usd: float
    tokens: tuple[int, int, int]


def cli_global_config_path(env: Mapping[str, str] | None = None) -> Path:
    environ = os.environ if env is None else env
    config_dir = (environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    config_home = Path(config_dir) if config_dir else Path.home() / ".claude"
    legacy = config_home / ".config.json"
    if legacy.exists():
        return legacy
    suffix = "-custom-oauth" if environ.get(_CUSTOM_OAUTH_ENV) else ""
    return (Path(config_dir) if config_dir else Path.home()) / f".claude{suffix}.json"


def restored_totals(sdk_session_id: str, env: Mapping[str, str] | None = None) -> RestoredTotals | None:
    """The totals the CLI will restore when resuming ``sdk_session_id``; ``None`` if it restores none.

    An unreadable config restores nothing for the CLI either.
    """
    try:
        config = json.loads(cli_global_config_path(env).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    projects = config.get("projects") if isinstance(config, dict) else None
    if not isinstance(projects, dict):
        return None
    for entry in projects.values():
        if not isinstance(entry, dict) or entry.get("lastSessionId") != sdk_session_id:
            continue
        cost = entry.get("lastCost")
        input_tokens, output_tokens, usage_tokens = extract_model_usage_tokens(
            {"model_usage": entry.get("lastModelUsage")}
        )
        return RestoredTotals(
            cost_usd=float(cost) if isinstance(cost, (int, float)) else 0.0,
            tokens=(input_tokens or 0, output_tokens or 0, usage_tokens or 0),
        )
    return None
