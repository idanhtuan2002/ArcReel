"""Give DramaClaw's OpenRouter channel a free-model fallback chain (ASSEMBLY_MODELS text slot).

OpenRouter routes a request through `models` in order when the first model is rate-limited or down. NewAPI's channel
`param_override` adds that list to every request on the channel; DramaClaw's own channel sync does not write
`param_override` (`newapi_provisioner._merge_channel_payload` allowed fields), so the setting survives profile saves.
Chain from docs/r2/cloud-free-quota-registry.md (writer probe ranking). Run on the host:
`python assembly/ops/newapi_text_fallback.py` (logs in as the NewAPI root user from ~/assembly-data/secrets/newapi-root).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

NEWAPI = "http://127.0.0.1:3000"
CHAIN = [
    "baidu/ernie-5.5-flash-preview:free",
    "particle-ai/particle-1:free",
    "inclusionai/ling-3.2-flash:free",
]  # OpenRouter accepts at most 3 entries in `models`


def main() -> None:
    password = (Path.home() / "assembly-data/secrets/newapi-root").read_text().strip()
    login = httpx.post(f"{NEWAPI}/api/user/login", json={"username": "root", "password": password}, timeout=30)
    data = login.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}", "New-Api-User": str(data["user"]["id"])}
    channels = httpx.get(f"{NEWAPI}/api/channel/", params={"p": 1, "page_size": 100}, headers=headers).json()
    target = next(c for c in channels["data"]["items"] if c["name"] == "DC-openrouter")
    detail = httpx.get(f"{NEWAPI}/api/channel/{target['id']}", headers=headers).json()["data"]
    detail["param_override"] = json.dumps({"models": CHAIN})
    detail.pop("status", None)  # read-only on NewAPI's general update endpoint (as DramaClaw's update_channel does)
    detail.pop("key", None)  # keep the stored key
    for body in (detail, {"channel": detail}):
        result = httpx.put(f"{NEWAPI}/api/channel/", json=body, headers=headers, timeout=30).json()
        if result.get("success"):
            print("updated", target["id"])
            return
    print(f"failed: {result.get('message')}", target["id"])


if __name__ == "__main__":
    main()
