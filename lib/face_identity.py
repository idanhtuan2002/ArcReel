"""Face identity as a ranking judge for best-of-N storyboards (ADR-0151).

A local ArcFace server (InsightFace ``buffalo_l``) scores a candidate storyboard against each character's sheet: the
cosine between the sheet's front-view face and the closest face in the candidate. A candidate's score is the mean over
the shot's characters that both pictures show; the highest score wins. On continuity corpus 2 this ranked the right
person above a look-alike in 36 of 37 pairs (``docs/r2/evidence/face-identity-qualification-2026-11-14``).
"""

from __future__ import annotations

import base64
import hashlib
import os
from collections.abc import Mapping, Sequence

import httpx

FACE_JUDGE_IDENTITY = "insightface/buffalo_l@2.1"
FACE_JUDGE_RULE = (
    "score(candidate) = mean over the shot's characters of cosine(ArcFace(front-view face of the character sheet), "
    "max over the candidate's faces of ArcFace(face)); characters either picture does not show are left out; "
    "the highest score wins; a shot with no scored character keeps its current version"
)
FACE_JUDGE_RULE_DIGEST = "sha256:" + hashlib.sha256(FACE_JUDGE_RULE.encode()).hexdigest()


class FaceIdentityService:
    def __init__(self, base_url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._transport = transport

    async def similarity(self, reference: bytes, candidate: bytes) -> float | None:
        """The candidate's face cosine to the sheet's face; ``None`` when either shows no face."""
        async with httpx.AsyncClient(timeout=120.0, transport=self._transport) as client:
            response = await client.post(
                f"{self._base}/v1/face-similarity",
                json={
                    "reference": base64.b64encode(reference).decode(),
                    "candidate": base64.b64encode(candidate).decode(),
                },
            )
            response.raise_for_status()
        cosine = response.json().get("cosine")
        return float(cosine) if isinstance(cosine, int | float) else None

    async def choose(
        self, sheets: Sequence[bytes], candidates: Sequence[bytes]
    ) -> tuple[int | None, list[float | None]]:
        """The index of the candidate whose faces best match the sheets, and every candidate's score; ``None`` when no
        candidate has a scored face."""
        scores: list[float | None] = []
        for candidate in candidates:
            values = [value for sheet in sheets if (value := await self.similarity(sheet, candidate)) is not None]
            scores.append(round(sum(values) / len(values), 4) if values else None)
        scored = [(score, index) for index, score in enumerate(scores) if score is not None]
        return (max(scored)[1] if scored else None), scores


def face_identity_from_env(environ: Mapping[str, str] | None = None) -> FaceIdentityService | None:
    """``ARCREEL_FACE_ID_URL`` (the local face-identity server); ``None`` when none is configured."""
    env = os.environ if environ is None else environ
    base = env.get("ARCREEL_FACE_ID_URL", "").strip()
    return FaceIdentityService(base) if base else None


__all__ = [
    "FACE_JUDGE_IDENTITY",
    "FACE_JUDGE_RULE",
    "FACE_JUDGE_RULE_DIGEST",
    "FaceIdentityService",
    "face_identity_from_env",
]
