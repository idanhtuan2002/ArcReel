"""NewAPI channel that serves DramaClaw's `index-tts-2` speech model from our voice adapter (ASSEMBLY_PLAN D9).

Inside pipeline tasks DramaClaw sends IndexTTS2 through NewAPI only (`generators/indextts2_fal.py`: the direct fal
path returns ORG_EGRESS_DENIED when a task egress context is present), as `POST /v1/audio/speech` with the cast sample
in `metadata.audio_url`. This OpenAI-type channel forwards that request to `assembly.voice_adapter` on the docker0
address; it holds no real key. Idempotent. Run on the host: `python assembly/ops/newapi_voice_channel.py`.
"""

from __future__ import annotations

from pathlib import Path

import httpx

NEWAPI = "http://127.0.0.1:3000"
NAME = "assembly-voice"
CHANNEL = {
    "type": 1,
    "name": NAME,
    "key": "local",
    "base_url": "http://172.17.0.1:23350",
    "models": "index-tts-2",
    "group": "default",
    "auto_ban": 0,
    "priority": 0,
}


def main() -> None:
    password = (Path.home() / "assembly-data/secrets/newapi-root").read_text().strip()
    client = httpx.Client(base_url=NEWAPI, timeout=30)
    data = client.post("/api/user/login", json={"username": "root", "password": password}).json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}", "New-Api-User": str(data["user"]["id"])}
    items = client.get("/api/channel/", params={"p": 1, "page_size": 100}, headers=headers).json()["data"]["items"]
    if any(c["name"] == NAME for c in items):
        print("exists")
        return
    result = client.post("/api/channel/", json={"mode": "single", "channel": CHANNEL}, headers=headers).json()
    print("created" if result.get("success") else f"failed: {result.get('message')}")


if __name__ == "__main__":
    main()
