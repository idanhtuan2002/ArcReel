"""The reviewed M10 probe catalog of the qualified host (`host-v1`).

Two reference-free recipes with the A4 qualified bodies, each under its own probe rule id, pinned to this host's
ffmpeg 8.0.1 tools and to the probe worker source that parses their output. A host with other tools, or a changed
worker, needs a new reviewed catalog revision; nothing here is generated at runtime.
"""

from __future__ import annotations

from typing import Any

from r2.quality.probes import ProbeCatalog, ProbeConfig

HOST_CATALOG_ID = "host-v1"
# sha256 of server/services/quality_probe_worker.py, the parser of every recipe below.
WORKER_PARSER_DIGEST = "sha256:934ec55210e4aa1f76f1862cc6802ce67f279743576253bcc51e29b560892036"
FFPROBE = {
    "name": "ffprobe",
    "version": "8.0.1",
    "executable_digest": "sha256:fad19fce58bcb6d7168e3a84b660f9a781a9e05778a1b22926a6e3625505c445",
    "build_digest": "sha256:57a3cf6cfb50dd35cf9d11db179049529dd697bd21a63f7e21fcfa08a6cfb59e",
    "model_digest": None,
}
FFMPEG = {
    "name": "ffmpeg",
    "version": "8.0.1",
    "executable_digest": "sha256:84d2f486398c6876f25a384c2ef30d6b85eb74b7d84bbf3307c1d33a84ee4c7d",
    "build_digest": "sha256:fb056f8565daf1212b4f216d546881f2c02b9d79aa1b20537a9f4437e9fedec2",
    "model_digest": None,
}
_PARAMETERS = {
    "require_video": True,
    "require_audio": False,
    "interval_kinds": ["BLACK", "FREEZE", "SILENCE"],
    "black_picture_ratio": "0.98",
    "black_pixel_threshold": "0.1",
    "black_min_duration_ms": 2000,
    "freeze_noise_db": "-60",
    "freeze_min_duration_ms": 2000,
    "silence_noise_db": "-50",
    "silence_min_duration_ms": 2000,
    "caption_format": "SRT",
    "frame_count": 5,
}
_APPLICABILITY = {"schema_id": "m10.probe-applicability.v1", "policy_id": "required", "revision": 1, "mode": "REQUIRED"}
_THRESHOLD = {
    "schema_id": "m10.probe-threshold.v1",
    "policy_id": "decode-complete",
    "revision": 1,
    "metric": "EVIDENCE_COMPLETE",
    "minimum": None,
    "maximum": None,
}


def _config(config_id: str, rule_id: str, recipe: str, tools: list[dict[str, Any]]) -> ProbeConfig:
    return ProbeConfig.model_validate(
        {
            "schema_id": "m10.probe-config.v1",
            "config_id": config_id,
            "revision": 1,
            "rule_id": rule_id,
            "recipe": recipe,
            "tools": tools,
            "parser_version": "host-quality-parser-v1",
            "parser_digest": WORKER_PARSER_DIGEST,
            "parameters": _PARAMETERS,
            "applicability_policy": _APPLICABILITY,
            "threshold_policy": _THRESHOLD,
            "reference_policy": None,
            "max_runtime_ms": 120000,
            "max_output_bytes": 1048576,
        }
    )


CONTAINER_CONFIG = _config("host-v1-container-stream", "probe-container", "CONTAINER_STREAM", [FFPROBE])
DECODE_CONFIG = _config("host-v1-decode", "probe-decode", "DECODE", [FFMPEG, FFPROBE])
HOST_CATALOG = ProbeCatalog(schema_id="m10.probe-catalog.v1", configs=(CONTAINER_CONFIG, DECODE_CONFIG))

__all__ = [
    "CONTAINER_CONFIG",
    "DECODE_CONFIG",
    "HOST_CATALOG",
    "HOST_CATALOG_ID",
    "WORKER_PARSER_DIGEST",
]
