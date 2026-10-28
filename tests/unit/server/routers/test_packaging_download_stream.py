"""The download response releases its snapshot however the stream ends."""

from __future__ import annotations

import pytest
from starlette.requests import ClientDisconnect

from server.routers.packaging import _ClosingStream


class FakeDownload:
    def __init__(self) -> None:
        self.closes = 0

    def close(self) -> None:
        self.closes += 1


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


@pytest.mark.parametrize("failure", [OSError("client went away"), RuntimeError("stream broke")])
async def test_a_failed_send_still_releases_the_download(failure: Exception) -> None:
    download = FakeDownload()

    def chunks():
        yield b"a"
        yield b"b"

    async def send(message):
        if message["type"] == "http.response.body":
            raise failure

    response = _ClosingStream(download, chunks(), media_type="application/zip")
    with pytest.raises((type(failure), ClientDisconnect)):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, _receive, send)
    assert download.closes == 1


async def test_a_completed_stream_releases_the_download_once() -> None:
    download = FakeDownload()
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    response = _ClosingStream(download, iter([b"zip"]), media_type="application/zip")
    await response({"type": "http", "asgi": {"spec_version": "2.4"}}, _receive, send)
    assert download.closes == 1
    assert any(message.get("body") == b"zip" for message in sent)
