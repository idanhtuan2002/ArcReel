"""How a film adapted from a story looks by default, keyed by the story's genre pack (ADR-0125 §6).

Every value is a known style template id, the vertical short-video frame and an episode length in seconds; a
genre without an entry keeps what the film already has.
"""

from __future__ import annotations

from dataclasses import dataclass

from lib.style_templates import is_known_template


@dataclass(frozen=True)
class FilmLook:
    style_template_id: str
    aspect_ratio: str
    episode_target_duration: int


_VERTICAL = "9:16"
LOOKS: dict[str, FilmLook] = {
    "family": FilmLook("live_premium_drama", _VERTICAL, 90),
    "mystery": FilmLook("live_cinema", _VERTICAL, 90),
    "horror": FilmLook("live_lynch", _VERTICAL, 90),
    "romance": FilmLook("live_kdrama", _VERTICAL, 90),
    "action": FilmLook("live_shaw", _VERTICAL, 60),
    "fantasy": FilmLook("live_ancient_xianxia", _VERTICAL, 90),
    "scifi": FilmLook("live_cyberpunk", _VERTICAL, 90),
    "comedy": FilmLook("live_anderson", _VERTICAL, 60),
    "historical": FilmLook("live_cinematic_ancient", _VERTICAL, 90),
    "school": FilmLook("anim_kyoto", _VERTICAL, 60),
}


def film_look(genre_pack: object) -> FilmLook | None:
    """The look of a film of a story in ``genre_pack``; ``None`` for an unknown genre or template."""
    look = LOOKS.get(genre_pack) if isinstance(genre_pack, str) else None
    return look if look is not None and is_known_template(look.style_template_id) else None


__all__ = ["LOOKS", "FilmLook", "film_look"]
