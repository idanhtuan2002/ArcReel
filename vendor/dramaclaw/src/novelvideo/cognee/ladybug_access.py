"""Seam: the Cognee graph path is never taken (``is_structured_pipeline`` is always true here)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


@asynccontextmanager
async def ladybug_graph_access(state_dir: str, *, read_only: bool) -> AsyncIterator[None]:
    raise RuntimeError("the Cognee graph is not part of the ArcReel port")
    yield  # pragma: no cover
