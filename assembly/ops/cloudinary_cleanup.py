"""Delete DramaClaw's Cloudinary relay copies older than a day (ASSEMBLY_PLAN D28).

Runs inside the DramaClaw api container (`docker exec -i … python - < this file`) so the Cloudinary secret never leaves
DramaClaw's own settings: it reads them with DramaClaw's `get_effective_media_relay_config`. DramaClaw uploads with
`folder=<relay folder>` (`storage/media_relay.py`), so the folder is matched both as an asset folder (dynamic folder
mode) and as a public-id prefix (fixed folder mode). Prints counts only.
"""

from __future__ import annotations

import datetime as dt
import os

import httpx
from novelvideo import config as app_config
from novelvideo.model_gateway_settings import get_effective_media_relay_config

MAX_AGE = dt.timedelta(hours=float(os.environ.get("RELAY_MAX_AGE_HOURS", "24")))


def _config():
    return get_effective_media_relay_config(
        env_provider=app_config.MEDIA_RELAY_PROVIDER,
        env_ttl_seconds=app_config.MEDIA_RELAY_TTL_SECONDS,
        env_endpoint=app_config.OSS_RELAY_ENDPOINT,
        env_bucket=app_config.OSS_RELAY_BUCKET,
        env_access_key_id=app_config.OSS_RELAY_AK,
        env_access_key_secret=app_config.OSS_RELAY_SK,
        env_cloud_name=app_config.CLOUDINARY_RELAY_CLOUD_NAME,
        env_cloudinary_api_key=app_config.CLOUDINARY_RELAY_API_KEY,
        env_cloudinary_api_secret=app_config.CLOUDINARY_RELAY_API_SECRET,
        env_cloudinary_folder=app_config.CLOUDINARY_RELAY_FOLDER,
    )


def _old(resources: list[dict], cutoff: dt.datetime) -> list[str]:
    out = []
    for item in resources:
        created = dt.datetime.fromisoformat(str(item["created_at"]).replace("Z", "+00:00"))
        if created < cutoff:
            out.append(str(item["public_id"]))
    return out


def main() -> None:
    cfg = _config()
    if cfg.provider != "cloudinary" or not cfg.cloud_name or not cfg.cloudinary_folder:
        print("skip: relay is not Cloudinary with a folder")
        return
    base = f"https://api.cloudinary.com/v1_1/{cfg.cloud_name}"
    auth = (cfg.cloudinary_api_key, cfg.cloudinary_api_secret)
    cutoff = dt.datetime.now(dt.UTC) - MAX_AGE
    with httpx.Client(auth=auth, timeout=60) as client:
        for kind in ("image", "video", "raw"):
            ids: set[str] = set()
            statuses = []
            for url, params in (
                (f"{base}/resources/by_asset_folder", {"asset_folder": cfg.cloudinary_folder, "max_results": 500}),
                (f"{base}/resources/{kind}/upload", {"prefix": f"{cfg.cloudinary_folder}/", "max_results": 500}),
            ):
                response = client.get(url, params=params)
                statuses.append(response.status_code)
                if response.status_code == 200:
                    found = [r for r in response.json().get("resources", []) if r.get("resource_type", kind) == kind]
                    ids.update(_old(found, cutoff))
            if 200 not in statuses:
                raise SystemExit(f"{kind}: Cloudinary listing failed, HTTP {statuses}")
            deleted = 0
            batch = sorted(ids)
            for start in range(0, len(batch), 100):
                chunk = batch[start : start + 100]
                response = client.delete(
                    f"{base}/resources/{kind}/upload", params=[("public_ids[]", pid) for pid in chunk]
                )
                response.raise_for_status()
                deleted += sum(1 for v in response.json().get("deleted", {}).values() if v == "deleted")
            print(f"{kind}: {len(batch)} older than {MAX_AGE}, deleted {deleted}")


main()
