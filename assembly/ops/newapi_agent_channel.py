"""NewAPI channel for DramaClaw's chat agent model `DC-codex-agent-LLM` (Xia Director, Codex backend).

In CE Custom mode DramaClaw's Codex agent calls `DC-codex-agent-LLM` through NewAPI with the Responses API
(`chat/service.py` `_codex_model`, `wire_api="responses"`), but the Custom feature list only maps the retired
`DC-hermes-LLM` (`frontend/src/lib/feature-models.ts` HERMES). This keeps a clone of DramaClaw's OpenRouter channel
(cloned server-side, the key is never read) named `assembly-agent` that serves `DC-codex-agent-LLM` with the same free
model and OpenRouter fallback chain as the text slot. DramaClaw only manages its `DC-*` channels.
Run on the host: `python assembly/ops/newapi_agent_channel.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

NEWAPI = "http://127.0.0.1:3000"
NAME = "assembly-agent"
AGENT_MODEL = "DC-codex-agent-LLM"
UPSTREAM = "baidu/ernie-5.5-flash-preview:free"
FALLBACK = ["baidu/ernie-5.5-flash-preview:free", "particle-ai/particle-1:free", "inclusionai/ling-3.2-flash:free"]


def main() -> None:
    password = (Path.home() / "assembly-data/secrets/newapi-root").read_text().strip()
    client = httpx.Client(base_url=NEWAPI, timeout=30)
    data = client.post("/api/user/login", json={"username": "root", "password": password}).json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}", "New-Api-User": str(data["user"]["id"])}

    def channels() -> list[dict]:
        return client.get("/api/channel/", params={"p": 1, "page_size": 100}, headers=headers).json()["data"]["items"]

    existing = next((c for c in channels() if c["name"] == NAME), None)
    if existing is None:
        origin = next(c for c in channels() if c["name"] == "DC-openrouter")
        copied = client.post(f"/api/channel/copy/{origin['id']}", params={"suffix": "-agent"}, headers=headers).json()
        if not copied.get("success"):
            raise RuntimeError(f"copy failed: {copied.get('message')}")
        existing = next(c for c in channels() if c["name"] == "DC-openrouter-agent")
    detail = client.get(f"/api/channel/{existing['id']}", headers=headers).json()["data"]
    detail.update(
        {
            "name": NAME,
            "models": AGENT_MODEL,
            "model_mapping": json.dumps({AGENT_MODEL: UPSTREAM}),
            "param_override": json.dumps({"models": FALLBACK}),
            "auto_ban": 0,
        }
    )
    detail = {k: v for k, v in detail.items() if k not in {"status", "key"}}
    for body in (detail, {"channel": detail}):
        if client.put("/api/channel/", json=body, headers=headers).json().get("success"):
            print("channel", existing["id"], NAME)
            return
    raise RuntimeError("update refused")


if __name__ == "__main__":
    main()
