"""Price every model the assembly routes through NewAPI at zero (internal accounting only).

NewAPI pre-charges the root user's quota per call (e.g. $18.75 a Wan clip at its default price) and this DramaClaw
gateway build has no way to raise a user's quota (no quota field in `EditWithTx`, redemption disabled). Every model in
the assembly is a free tier or local, so the honest internal price is zero: per-call models get `ModelPrice` 0,
token-priced models `ModelRatio` 0 and `CompletionRatio` 0. Covers every model name on every enabled channel.
Run on the host: `python assembly/ops/newapi_free_pricing.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

NEWAPI = "http://127.0.0.1:3000"
PER_CALL = ("Wan22-5B-local", "LingShan-G2", "LingShan-NB-2", "index-tts-2")


def main() -> None:
    password = (Path.home() / "assembly-data/secrets/newapi-root").read_text().strip()
    client = httpx.Client(base_url=NEWAPI, timeout=30)
    data = client.post("/api/user/login", json={"username": "root", "password": password}).json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}", "New-Api-User": str(data["user"]["id"])}
    items = client.get("/api/channel/", params={"p": 1, "page_size": 100}, headers=headers).json()["data"]["items"]
    names = sorted({m for c in items if c.get("status") == 1 for m in str(c.get("models") or "").split(",") if m})
    options = {o["key"]: o["value"] for o in client.get("/api/option/", headers=headers).json()["data"]}
    for key, zeroed in (
        ("ModelPrice", [n for n in names if n in PER_CALL]),
        ("ModelRatio", [n for n in names if n not in PER_CALL]),
        ("CompletionRatio", [n for n in names if n not in PER_CALL]),
    ):
        current = json.loads(options.get(key) or "{}")
        current.update(dict.fromkeys(zeroed, 0))
        result = client.put("/api/option/", json={"key": key, "value": json.dumps(current)}, headers=headers).json()
        print(key, len(zeroed), "ok" if result.get("success") else result.get("message"))


if __name__ == "__main__":
    main()
