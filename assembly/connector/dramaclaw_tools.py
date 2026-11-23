"""DramaClaw's Hermes toolset, loaded the way DramaClaw's own MCP bridge loads it.

Ported from DramaClaw @ b299bfd ``src/novelvideo/chat/dramaclaw_mcp.py`` (``_install_hermes_registry_shim``,
``_load_dramaclaw_plugin``, ``_tool_index``); the plugin itself is vendored unchanged at
``vendor/dramaclaw/hermes/plugins/dramaclaw/__init__.py``. The MCP stdio server part is not needed: the connector calls
the handlers in-process. Auth uses DramaClaw's CE owner mode (``DRAMACLAW_CE_OWNER=1`` with a loopback
``DRAMACLAW_API_URL``).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types as py_types
from collections.abc import Callable
from pathlib import Path
from typing import Any

PLUGIN_PATH = Path(__file__).resolve().parents[2] / "vendor/dramaclaw/hermes/plugins/dramaclaw/__init__.py"
DEFAULT_API_URL = "http://127.0.0.1:8780"


def _install_hermes_registry_shim() -> None:
    if "tools.registry" in sys.modules:
        return

    tools_pkg = py_types.ModuleType("tools")
    registry = py_types.ModuleType("tools.registry")

    def tool_result(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    def tool_error(message: Any) -> str:
        return json.dumps({"ok": False, "error": str(message)}, ensure_ascii=False)

    registry.tool_result = tool_result  # pyright: ignore[reportAttributeAccessIssue]
    registry.tool_error = tool_error  # pyright: ignore[reportAttributeAccessIssue]
    tools_pkg.registry = registry  # pyright: ignore[reportAttributeAccessIssue]
    sys.modules.setdefault("tools", tools_pkg)
    sys.modules["tools.registry"] = registry


def _load_dramaclaw_plugin() -> Any:
    _install_hermes_registry_shim()
    spec = importlib.util.spec_from_file_location("_dramaclaw_hermes_plugin_for_assembly", PLUGIN_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load DramaClaw plugin from {PLUGIN_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tool_index(plugin: Any) -> dict[str, tuple[dict[str, Any], Any]]:
    index: dict[str, tuple[dict[str, Any], Any]] = {}
    for entry in getattr(plugin, "TOOLS", ()):
        if not isinstance(entry, tuple) or len(entry) != 3:
            continue
        name, schema, handler = entry
        if isinstance(name, str) and isinstance(schema, dict) and callable(handler):
            index[name] = (schema, handler)
    return index


class DramaClawTools:
    """Calls DramaClaw's toolset handlers for one project; results are the handlers' decoded JSON."""

    def __init__(self, project_id: str, api_url: str | None = None) -> None:
        os.environ.setdefault("DRAMACLAW_API_URL", api_url or DEFAULT_API_URL)
        os.environ.setdefault("DRAMACLAW_CE_OWNER", "1")
        os.environ["DRAMACLAW_PROJECT_ID"] = project_id
        self.project_id = project_id
        self.plugin = _load_dramaclaw_plugin()
        self.tools = _tool_index(self.plugin)

    def call(self, tool: str, /, **args: Any) -> Any:
        _schema, handler = self.tools[tool]
        args.setdefault("project_id", self.project_id)
        raw: str = handler(args)
        return json.loads(raw)

    def request(self, method: str, path: str, *, query: Any = None, body: Any = None) -> dict[str, Any]:
        return self.plugin._request(method, path, query=query, body=body)

    @property
    def names(self) -> list[str]:
        return sorted(self.tools)


ToolCall = Callable[..., Any]
