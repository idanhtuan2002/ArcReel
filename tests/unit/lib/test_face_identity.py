"""The face-identity ranking judge against a scripted face server."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from lib.face_identity import FaceIdentityService, face_identity_from_env

pytestmark = pytest.mark.asyncio

#: (sheet, candidate) -> cosine; a missing pair means no face.
SCORES = {(b"lan", b"good"): 0.42, (b"lan", b"bad"): 0.12, (b"minh", b"good"): 0.30, (b"minh", b"bad"): 0.35}


def _server() -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        pair = (base64.b64decode(body["reference"]), base64.b64decode(body["candidate"]))
        return httpx.Response(200, json={"cosine": SCORES.get(pair)})

    return httpx.MockTransport(handle)


async def test_the_candidate_closest_to_the_cast_on_average_wins():
    service = FaceIdentityService("http://face", transport=_server())

    index, scores = await service.choose([b"lan", b"minh"], [b"bad", b"good"])

    assert index == 1
    assert scores == [0.235, 0.36]


async def test_no_scored_face_means_no_choice():
    service = FaceIdentityService("http://face", transport=_server())

    assert await service.choose([b"nobody"], [b"good", b"bad"]) == (None, [None, None])


async def test_the_server_url_comes_from_the_environment():
    assert face_identity_from_env({}) is None
    assert face_identity_from_env({"ARCREEL_FACE_ID_URL": "http://127.0.0.1:8003"}) is not None
