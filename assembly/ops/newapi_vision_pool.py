"""Spread DramaClaw's vision features over several free Gemini models (ASSEMBLY_MODELS vision slot).

Gemini's free tier counts requests per model (about 20 a day each, docs/r2/cloud-free-quota-registry.md); one episode
needs ~36 vision calls (video prompt optimizer + sketch identity detector, one per beat), more than one model allows.
NewAPI retries a failed request on another channel serving the same model name when `RetryTimes` > 0
(gateway `controller/relay.go` shouldRetry). This script sets `RetryTimes` and keeps one cloned Gemini channel per
extra model (cloned server-side with `/api/channel/copy/:id`, so the key is never read), each mapping the vision
names to its model, auto-ban off (a quota 429 must not disable a channel). Clones are named `assembly-gemini-*`;
DramaClaw only manages its `DC-*` channels. Run on the host: `python assembly/ops/newapi_vision_pool.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

NEWAPI = "http://127.0.0.1:3000"
RETRY_TIMES = 3
VISION_NAMES = [
    "DC-video-prompt-optimizer-LLM",
    "DC-video-identity-detector-LLM",
    "DC-freezone-vision-LLM",
    "DC-style-analyzer-LLM",
]
EXTRA_MODELS = ["gemini-3.5-flash-lite", "gemini-2.5-flash", "gemini-3-flash-preview"]


def _session() -> tuple[httpx.Client, dict[str, str]]:
    password = (Path.home() / "assembly-data/secrets/newapi-root").read_text().strip()
    client = httpx.Client(base_url=NEWAPI, timeout=30)
    data = client.post("/api/user/login", json={"username": "root", "password": password}).json()["data"]
    return client, {"Authorization": f"Bearer {data['access_token']}", "New-Api-User": str(data["user"]["id"])}


def _update(client: httpx.Client, headers: dict[str, str], channel: dict) -> None:
    channel = {k: v for k, v in channel.items() if k not in {"status", "key"}}
    for body in (channel, {"channel": channel}):
        if client.put("/api/channel/", json=body, headers=headers).json().get("success"):
            return
    raise RuntimeError(f"channel {channel.get('id')} update refused")


def main() -> None:
    client, headers = _session()
    result = client.put("/api/option/", json={"key": "RetryTimes", "value": str(RETRY_TIMES)}, headers=headers).json()
    print("RetryTimes", RETRY_TIMES, "ok" if result.get("success") else result.get("message"))
    items = client.get("/api/channel/", params={"p": 1, "page_size": 100}, headers=headers).json()["data"]["items"]
    origin = next(c for c in items if c["name"] == "DC-gemini")
    for model in EXTRA_MODELS:
        name = f"assembly-gemini-{model}"
        existing = next((c for c in items if c["name"] == name), None)
        if existing is None:
            copied = client.post(
                f"/api/channel/copy/{origin['id']}", params={"suffix": f"-{model}"}, headers=headers
            ).json()
            if not copied.get("success"):
                raise RuntimeError(f"copy failed: {copied.get('message')}")
            items = client.get("/api/channel/", params={"p": 1, "page_size": 100}, headers=headers).json()["data"][
                "items"
            ]
            existing = next(c for c in items if c["name"] == f"DC-gemini-{model}")
        detail = client.get(f"/api/channel/{existing['id']}", headers=headers).json()["data"]
        detail.update(
            {
                "name": name,
                "models": ",".join(VISION_NAMES),
                "model_mapping": json.dumps(dict.fromkeys(VISION_NAMES, model)),
                "auto_ban": 0,
            }
        )
        _update(client, headers, detail)
        print("channel", existing["id"], name)


if __name__ == "__main__":
    main()
