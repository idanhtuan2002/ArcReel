"""Pure artifact-key wire primitives and leaf validation, without host initialization."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from typing import NamedTuple, cast

_KEY_PREFIX = "artifact-key-v1:"
EPISODE_VIDEO_KIND = "episode-video"


def encode_artifact_key_parts(kind: str, components: Sequence[object]) -> str:
    """Encode raw key parts into the manifest key wire form.

    Shared with :meth:`ArtifactKey.encode` so exactly one encoding exists, including
    for producers that cannot go through :class:`ArtifactKey` — a migration rewriting
    a key whose kind this build no longer defines has no typed key to encode.
    """

    payload = json.dumps([kind, *components], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return _KEY_PREFIX + token


class ArtifactKeyParts(NamedTuple):
    """A manifest key's raw parts, before any :class:`ArtifactKind` is required to exist."""

    kind: str
    components: tuple[object, ...]


def decode_artifact_key_parts(value: str) -> ArtifactKeyParts | None:
    """Decode a manifest key back into its raw kind and components.

    Returns ``None`` for anything that is not this encoding.  Unlike
    :meth:`ArtifactKey.decode` the kind is not required to still be a supported
    :class:`ArtifactKind`, which is what lets a migration rewrite a renamed kind.
    """

    if not value.startswith(_KEY_PREFIX):
        return None
    token = value.removeprefix(_KEY_PREFIX)
    try:
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], str):
        return None
    return ArtifactKeyParts(payload[0], tuple(cast(list[object], payload)[1:]))


def _episode_number(value: int) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"episode must be a positive integer, got {value!r}")
    return value


def _non_empty(field: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def validate_m3_target_ref(target_ref: str) -> str:
    if (
        not target_ref
        or target_ref in {".", ".."}
        or any(char in target_ref for char in ("/", "\\", ":", "\x00"))
        or any(ord(char) < 32 for char in target_ref)
    ):
        raise ValueError("target_ref must be one safe filename component")
    return target_ref


def episode_video_key(episode: int, resource_id: str) -> str:
    """Encode the same generic video coordinate as the host's typed factory."""
    return encode_artifact_key_parts(
        EPISODE_VIDEO_KIND, (_episode_number(episode), _non_empty("resource_id", resource_id))
    )


def decode_episode_video_key(value: str) -> tuple[int, str]:
    """Decode a canonical episode-video key without constructing a host adapter."""
    parts = decode_artifact_key_parts(value)
    if parts is None or parts.kind != EPISODE_VIDEO_KIND or len(parts.components) != 2:
        raise ValueError("artifact key is not an episode video")
    episode, resource_id = parts.components
    if type(episode) is not int or not isinstance(resource_id, str):
        raise ValueError("episode video key has invalid components")
    if episode_video_key(episode, resource_id) != value:
        raise ValueError("episode video key is not canonical")
    return episode, resource_id
