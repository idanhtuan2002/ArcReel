"""Temporarily serve DramaClaw's text slots from the Gemini channels while OpenRouter refuses inference (2026-11-25).

`--apply`: the `DC-*-LLM` names served by `DC-openrouter` are added to the `assembly-gemini-*` clones (mapped to each
clone's model) and `DC-openrouter` is disabled, so NewAPI never routes to it. `--revert`: the names are removed from
the clones and `DC-openrouter` is enabled again. Keys are never read. Sponsor choice 2026-11-25 (ledger row).
Run on the host: `python assembly/ops/newapi_text_to_gemini.py --apply` / `--revert`.
"""

from __future__ import annotations

import argparse
import json

from assembly.ops.newapi_vision_pool import (
    EXTRA_MODELS,
    VERIFIER_MODELS,
    VERIFIER_NAME,
    VISION_NAMES,
    _session,
    _update,
)

ENABLED, MANUALLY_DISABLED = 1, 2


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true")
    group.add_argument("--revert", action="store_true")
    args = parser.parse_args()
    client, headers = _session()
    items = client.get("/api/channel/", params={"p": 1, "page_size": 100}, headers=headers).json()["data"]["items"]
    openrouter = next(c for c in items if c["name"] == "DC-openrouter")
    text_names = [n for n in openrouter["models"].split(",") if n]
    for model in EXTRA_MODELS:
        channel = next(c for c in items if c["name"] == f"assembly-gemini-{model}")
        detail = client.get(f"/api/channel/{channel['id']}", headers=headers).json()["data"]
        names = VISION_NAMES + ([VERIFIER_NAME] if model in VERIFIER_MODELS else [])
        if args.apply:
            names = names + [n for n in text_names if n not in names]
        detail.update({"models": ",".join(names), "model_mapping": json.dumps(dict.fromkeys(names, model))})
        _update(client, headers, detail)
        print("channel", channel["id"], detail["name"], len(names), "names")
    status = MANUALLY_DISABLED if args.apply else ENABLED
    # NewAPI refuses `status` in the channel update; it has its own route (gateway router/channel-router.go).
    result = client.post(f"/api/channel/{openrouter['id']}/status", json={"status": status}, headers=headers).json()
    if not result.get("success"):
        raise RuntimeError(f"DC-openrouter status update refused: {result.get('message')}")
    state = client.get(f"/api/channel/{openrouter['id']}", headers=headers).json()["data"]["status"]
    print("DC-openrouter status", state)


if __name__ == "__main__":
    main()
