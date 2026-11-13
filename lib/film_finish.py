"""Finishing filters of the rendered film: a camera move on a still clip and the film's colour grade.

A still clip (one picture held for the whole unit) gets a slow camera move chosen from the shot's planned
``camera_motion``: the frame is supersampled, then ``zoompan`` moves a window over it, so the move has sub-pixel
steps instead of the one-pixel jitter ``zoompan`` shows at the output size. Moves the picture cannot carry (orbit,
tracking, shake) become a slow push in or a diagonal drift.

The grade is one of a closed set of ``colorbalance`` / ``curves`` / ``eq`` profiles applied to every unit, blended
with the ungraded picture by ``intensity`` so a profile never overpowers the generated look.
"""

from __future__ import annotations

from typing import Literal, get_args

Move = Literal["static", "push_in", "pull_out", "pan_left", "pan_right", "tilt_up", "tilt_down", "drift"]
Grade = Literal[
    "neutral", "cinematic_warm", "cinematic_cool", "moody_dark", "bright_clean", "vintage_film", "high_contrast"
]

MOVES: tuple[str, ...] = get_args(Move)
GRADES: tuple[str, ...] = get_args(Grade)

#: Zoom gained over the whole unit by a push in or a pull out.
ZOOM = 0.10
#: Zoom held while panning or tilting; the extra picture is the room the move travels.
PAN_ZOOM = 1.10
#: Zoom gained by the gentle push a planned static shot gets, so a held picture still breathes.
STATIC_ZOOM = 0.04
SUPERSAMPLE = 3
DEFAULT_GRADE_INTENSITY = 0.7

#: Planned camera motion (``lib.script_models.CameraMotion``) → the move a still picture can carry.
CAMERA_MOTION_MOVES: dict[str, Move] = {
    "Static": "static",
    "Push In": "push_in",
    "Zoom In": "push_in",
    "Pull Out": "pull_out",
    "Zoom Out": "pull_out",
    "Pan Left": "pan_left",
    "Truck Left": "pan_left",
    "Pan Right": "pan_right",
    "Truck Right": "pan_right",
    "Tilt Up": "tilt_up",
    "Pedestal Up": "tilt_up",
    "Tilt Down": "tilt_down",
    "Pedestal Down": "tilt_down",
    "Orbit": "drift",
    "Tracking Shot": "drift",
    "Shake": "push_in",
}

GRADE_FILTERS: dict[str, str] = {
    "neutral": "eq=contrast=1.02:saturation=1.02:brightness=0.01",
    "cinematic_warm": (
        "colorbalance=rs=0.08:gs=0.02:bs=-0.05:rh=0.06:gh=0.02:bh=-0.04,"
        "curves=all='0/0.03 0.25/0.22 0.5/0.50 0.75/0.78 1/0.97',"
        "eq=contrast=1.05:saturation=1.1"
    ),
    "cinematic_cool": (
        "colorbalance=rs=-0.02:gs=-0.03:bs=0.08:rh=0.06:gh=-0.02:bh=-0.06,"
        "curves=all='0/0.02 0.25/0.20 0.5/0.48 0.75/0.78 1/0.98',"
        "eq=contrast=1.08:saturation=1.05"
    ),
    "moody_dark": "curves=all='0/0.05 0.15/0.12 0.5/0.45 0.85/0.82 1/0.95',eq=contrast=1.12:saturation=0.8:brightness=-0.03",
    "bright_clean": "curves=all='0/0.05 0.25/0.30 0.5/0.55 0.75/0.80 1/1.0',eq=contrast=1.0:saturation=1.15:brightness=0.02",
    "vintage_film": (
        "colorbalance=rs=0.06:gs=0.03:bs=-0.03:rm=0.03:bm=-0.02,"
        "curves=all='0/0.06 0.25/0.25 0.5/0.50 0.75/0.74 1/0.94',"
        "eq=saturation=0.85:contrast=0.95"
    ),
    "high_contrast": "curves=all='0/0 0.20/0.12 0.5/0.50 0.80/0.88 1/1',eq=contrast=1.2:saturation=1.1",
}

#: What each grade is for, written into the planning prompt that picks one.
GRADE_GUIDE: dict[str, str] = {
    "neutral": "true-to-life colour, light contrast",
    "cinematic_warm": "warm, nostalgic, romantic or hopeful stories; golden light",
    "cinematic_cool": "teal-and-orange; urban, thriller, modern drama",
    "moody_dark": "crushed blacks, muted colour; horror, crime, grief, tension",
    "bright_clean": "bright, vivid, lifted shadows; comedy, slice of life, youth",
    "vintage_film": "faded warm film; memory, period pieces, the past",
    "high_contrast": "punchy contrast; action, conflict, revenge",
}


def move_for(camera_motion: object) -> Move:
    """The move a still picture makes for a planned camera motion; an unknown or missing one pushes in gently."""
    return CAMERA_MOTION_MOVES.get(camera_motion, "static") if isinstance(camera_motion, str) else "static"


def motion_filter(move: str, *, width: int, height: int, fps: int, frames: int) -> str:
    """Filter chain moving a camera over a held picture of ``width``×``height`` for ``frames`` frames."""
    if move not in MOVES:
        raise ValueError(f"unknown move: {move!r}")
    last = max(frames - 1, 1)
    p = f"min(on/{last}\\,1)"
    centre_x, centre_y = "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"
    room_x, room_y = "(iw-iw/zoom)", "(ih-ih/zoom)"
    zoom, x, y = {
        "static": (f"1+{STATIC_ZOOM}*{p}", centre_x, centre_y),
        "push_in": (f"1+{ZOOM}*{p}", centre_x, centre_y),
        "pull_out": (f"1+{ZOOM}*(1-{p})", centre_x, centre_y),
        "pan_left": (f"{PAN_ZOOM}", f"{room_x}*(1-{p})", centre_y),
        "pan_right": (f"{PAN_ZOOM}", f"{room_x}*{p}", centre_y),
        "tilt_up": (f"{PAN_ZOOM}", centre_x, f"{room_y}*(1-{p})"),
        "tilt_down": (f"{PAN_ZOOM}", centre_x, f"{room_y}*{p}"),
        "drift": (f"1+{ZOOM}*{p}", f"{room_x}*(0.5-0.3*{p})", f"{room_y}*(0.5-0.2*{p})"),
    }[move]
    big_w, big_h = width * SUPERSAMPLE, height * SUPERSAMPLE
    return f"scale={big_w}:{big_h}:flags=lanczos,zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps}"


def grade_filter(grade: str, intensity: float, *, source: str, output: str) -> str:
    """Filtergraph section grading ``[source]`` into ``[output]``; a grade at full intensity is applied as is."""
    if grade not in GRADE_FILTERS:
        raise ValueError(f"unknown grade: {grade!r}")
    if not 0 < intensity <= 1:
        raise ValueError(f"grade intensity outside (0, 1]: {intensity!r}")
    body = GRADE_FILTERS[grade]
    if intensity >= 1:
        return f"[{source}]{body}[{output}]"
    return (
        f"[{source}]split[{output}_o][{output}_g];[{output}_g]{body}[{output}_c];"
        f"[{output}_o][{output}_c]blend=all_mode=normal:all_opacity={intensity:.3f}[{output}]"
    )


def grade_prompt_options() -> str:
    """The grade choices with what each is for, one per line, for a planning prompt."""
    return "\n".join(f"- {name}: {GRADE_GUIDE[name]}" for name in GRADES)


__all__ = [
    "CAMERA_MOTION_MOVES",
    "DEFAULT_GRADE_INTENSITY",
    "GRADES",
    "GRADE_FILTERS",
    "MOVES",
    "Grade",
    "Move",
    "grade_filter",
    "grade_prompt_options",
    "motion_filter",
    "move_for",
]
