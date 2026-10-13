"""Render a synthetic room from two opposite camera directions: a MASTER and a REVERSE PNG.

The room is a 6 m x 3 m x 8 m box. The camera stands at its centre, eye height 1.6 m:
- MASTER looks at the front wall: a red cabinet and a window;
- REVERSE turns 180 degrees to the back wall: a blue door and a bookshelf.

A yellow painting on the left wall and a whiteboard on the right wall are seen at the edges.
Rendering is deterministic, so the same command always writes the same bytes.

    uv run python -m scripts.r2.render_spatial_fixture --out-dir tests/fixtures/r2/spatial_live
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageDraw

WIDTH, HEIGHT = 1280, 720
FOCAL = WIDTH / 2  # 90 degree horizontal field of view
EYE = 1.6
NEAR = 0.3
HALF_W, ROOM_H, HALF_D = 3.0, 3.0, 4.0

Point = tuple[float, float, float]
Quad = tuple[Point, Point, Point, Point]

# (colour, corners) in room coordinates; drawn back to front in this order.
SURFACES: list[tuple[str, Quad]] = [
    ("#6b5a48", ((-HALF_W, 0, -HALF_D), (HALF_W, 0, -HALF_D), (HALF_W, 0, HALF_D), (-HALF_W, 0, HALF_D))),
    (
        "#e6e2da",
        ((-HALF_W, ROOM_H, -HALF_D), (HALF_W, ROOM_H, -HALF_D), (HALF_W, ROOM_H, HALF_D), (-HALF_W, ROOM_H, HALF_D)),
    ),
    ("#c9cfc3", ((-HALF_W, 0, -HALF_D), (-HALF_W, 0, HALF_D), (-HALF_W, ROOM_H, HALF_D), (-HALF_W, ROOM_H, -HALF_D))),
    ("#bfc6ba", ((HALF_W, 0, -HALF_D), (HALF_W, 0, HALF_D), (HALF_W, ROOM_H, HALF_D), (HALF_W, ROOM_H, -HALF_D))),
    ("#d8d3c4", ((-HALF_W, 0, HALF_D), (HALF_W, 0, HALF_D), (HALF_W, ROOM_H, HALF_D), (-HALF_W, ROOM_H, HALF_D))),
    ("#d3cfc0", ((-HALF_W, 0, -HALF_D), (HALF_W, 0, -HALF_D), (HALF_W, ROOM_H, -HALF_D), (-HALF_W, ROOM_H, -HALF_D))),
]


def _front(x0: float, x1: float, y0: float, y1: float, z: float) -> Quad:
    return ((x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z))


def _side(x: float, z0: float, z1: float, y0: float, y1: float) -> Quad:
    return ((x, y0, z0), (x, y0, z1), (x, y1, z1), (x, y1, z0))


FRONT = HALF_D - 0.01
BACK = -HALF_D + 0.01
OBJECTS: list[tuple[str, Quad]] = [
    # front wall: window (frame, glass) and a red fire-extinguisher cabinet
    ("#4a4a4a", _front(-1.6, 0.6, 1.1, 2.5, FRONT)),
    ("#9fd3f0", _front(-1.5, 0.5, 1.2, 2.4, FRONT - 0.001)),
    ("#c62828", _front(1.7, 2.5, 0.7, 1.7, FRONT)),
    ("#f5f5f5", _front(1.85, 2.35, 1.3, 1.55, FRONT - 0.001)),
    # back wall: blue exit door with a handle, and a brown bookshelf with shelves
    ("#1e4fa3", _front(-2.3, -1.2, 0.0, 2.1, BACK)),
    ("#e0b000", _front(-1.4, -1.3, 1.0, 1.1, BACK + 0.001)),
    ("#7a4a22", _front(0.4, 2.6, 0.0, 2.0, BACK)),
    *[("#4f2f14", _front(0.45, 2.55, y, y + 0.05, BACK + 0.001)) for y in (0.5, 1.0, 1.5)],
    # left wall: a yellow painting; right wall: a whiteboard
    ("#e8c547", _side(-HALF_W + 0.01, 3.0, 3.9, 1.2, 2.0)),
    ("#fafafa", _side(HALF_W - 0.01, -3.9, -3.0, 1.0, 2.0)),
]


def _camera(point: Point, reverse: bool) -> Point:
    x, y, z = point
    return (-x, y - EYE, -z) if reverse else (x, y - EYE, z)


def _clip_near(polygon: Sequence[Point]) -> list[Point]:
    clipped: list[Point] = []
    for index, current in enumerate(polygon):
        previous = polygon[index - 1]
        current_in, previous_in = current[2] >= NEAR, previous[2] >= NEAR
        if current_in != previous_in:
            t = (NEAR - previous[2]) / (current[2] - previous[2])
            clipped.append(tuple(p + t * (c - p) for p, c in zip(previous, current, strict=True)))
        if current_in:
            clipped.append(current)
    return clipped


def _project(point: Point) -> tuple[float, float]:
    x, y, z = point
    return (WIDTH / 2 + FOCAL * x / z, HEIGHT / 2 - FOCAL * y / z)


def render(reverse: bool) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#000000")
    draw = ImageDraw.Draw(image)
    for colour, quad in [*SURFACES, *OBJECTS]:
        polygon = _clip_near([_camera(point, reverse) for point in quad])
        if len(polygon) >= 3:
            draw.polygon([_project(point) for point in polygon], fill=colour, outline="#00000022")
    return image


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, reverse in (("master.png", False), ("reverse.png", True)):
        render(reverse).save(args.out_dir / name, optimize=False)
        print(args.out_dir / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
