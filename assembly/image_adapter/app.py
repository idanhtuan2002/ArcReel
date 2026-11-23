"""Raise DramaClaw's image sizes to Seedream 4.5's minimum before they reach BytePlus (ASSEMBLY_PLAN D7).

DramaClaw generates pipeline images at its fixed "1K" tier (e.g. 768x1024 portraits; `config.get_grid_generation_config`
has no size setting for the pipeline), while Seedream 4.5 rejects images under 3 686 400 pixels ("image size must be
at least 3686400 pixels"). The NewAPI VolcEngine channel points here instead of at BytePlus; image requests below
the minimum are scaled up keeping their aspect ratio, everything else (other sizes, Seedance video tasks, task polls)
is forwarded unchanged. The upstream key travels in the request's own Authorization header and is not stored.
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response

UPSTREAM = os.environ.get("BYTEPLUS_ARK_BASE", "https://ark.ap-southeast.bytepluses.com")
MIN_PIXELS = int(os.environ.get("SEEDREAM_MIN_PIXELS", "3686400"))
_SIZE = re.compile(r"^\s*(\d+)\s*[xX*]\s*(\d+)\s*$")
_HOP_HEADERS = {"host", "content-length", "connection", "accept-encoding", "transfer-encoding"}

app = FastAPI(title="Assembly BytePlus adapter (Seedream minimum size)")


def raised_size(width: int, height: int, minimum: int = MIN_PIXELS) -> tuple[int, int]:
    """Smallest even width/height with the same ratio and at least `minimum` pixels (unchanged when already big)."""
    if width * height >= minimum:
        return width, height
    scale = math.sqrt(minimum / (width * height))
    new_w = math.ceil(width * scale / 2) * 2
    new_h = math.ceil(height * scale / 2) * 2
    while new_w * new_h < minimum:
        new_w += 2
        new_h = math.ceil(new_w * height / width / 2) * 2
    return new_w, new_h


def adjust_image_body(body: dict[str, Any], minimum: int = MIN_PIXELS) -> dict[str, Any]:
    out = dict(body)
    match = _SIZE.match(str(out.get("size") or ""))
    if match:
        w, h = raised_size(int(match.group(1)), int(match.group(2)), minimum)
        out["size"] = f"{w}x{h}"
    if isinstance(out.get("width"), int) and isinstance(out.get("height"), int):
        out["width"], out["height"] = raised_size(out["width"], out["height"], minimum)
    return out


@app.api_route("/{path:path}", methods=["GET", "POST", "DELETE", "PUT", "PATCH"])
async def forward(path: str, request: Request) -> Response:
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_HEADERS}
    content = await request.body()
    if request.method == "POST" and path.rstrip("/").endswith("images/generations"):
        content = json.dumps(adjust_image_body(json.loads(content or b"{}"))).encode()
    async with httpx.AsyncClient(timeout=600) as client:
        upstream = await client.request(
            request.method, f"{UPSTREAM}/{path}", params=request.query_params, headers=headers, content=content
        )
    body_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_HEADERS | {"content-encoding"}}
    return Response(content=upstream.content, status_code=upstream.status_code, headers=body_headers)
