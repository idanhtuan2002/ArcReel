"""Build the M8-F blind review packet from exported review media (protocol v3, ADR-0108 amendment 1).

    uv run python scripts/r2/m8f_review_packet.py <review-media-dir> <packet-dir> <key-file>

The packet holds neutral copies of each cohort's source and projections, spatial frames with every
VISIBLE span drawn, and a rubric form. Labels are shuffled; one format and one spatial calibration item
are mixed in unlabelled (a muted projection; a candidate with an added VISIBLE claim over bare wall).
The label key, including which items calibrate, is written to ``key-file`` outside the packet.
"""

from __future__ import annotations

import argparse
import html
import json
import random
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

COHORTS = ("WESTERN_GENERIC", "CN_SHORT_DRAMA_SHUANGWEN")
FORMAT_ITEMS = ("focal_subject", "action", "shot_intent", "on_screen_text", "captions", "timing", "audio")
SPATIAL_ITEMS = (
    "pairing_matches_master_reverse",
    "visible_assertions_supported_by_frames",
    "gaps_not_stated_as_facts",
    "seam_and_direction_locks_plausible",
)
PLANTED = {
    "assertion_id": "planted",
    "evidence_class": "VISIBLE",
    "subjects": ["green sofa"],
    "relation": "green sofa against the front wall",
    "confidence": None,
    "spans": [{"view": "MASTER", "x0": 0.3, "y0": 0.45, "x1": 0.5, "y1": 0.8}],
}


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def _radios(label: str, items: Sequence[str]) -> str:
    rows = "".join(
        f'<tr><td><code>{item}</code></td><td><label><input type="radio" name="{label}.{item}" value="PASS"> PASS'
        f'</label> <label><input type="radio" name="{label}.{item}" value="FAIL"> FAIL</label></td></tr>'
        for item in items
    )
    return f'<table>{rows}</table><textarea name="{label}.note"></textarea>'


def _span_boxes(assertions: list[dict], view: str) -> str:
    return "".join(
        f'<div class="span" style="left:{s["x0"] * 100}%;top:{s["y0"] * 100}%;width:{(s["x1"] - s["x0"]) * 100}%;'
        f'height:{(s["y1"] - s["y0"]) * 100}%"><span>{html.escape(a["subjects"][0])}</span></div>'
        for a in assertions
        for s in a.get("spans", [])
        if s.get("view") == view
    )


def build(media: Path, out: Path, key_file: Path, *, seed: int) -> None:
    rng = random.Random(seed)
    shutil.rmtree(out, ignore_errors=True)
    (out / "m").mkdir(parents=True)
    formats = [(cohort, profile, False) for cohort in COHORTS for profile in ("vertical-9x16", "square")]
    formats.append((rng.choice(COHORTS), rng.choice(("vertical-9x16", "square")), True))
    rng.shuffle(formats)
    spatial = [(cohort, False) for cohort in COHORTS] + [(rng.choice(COHORTS), True)]
    rng.shuffle(spatial)
    key: dict[str, dict] = {"format": {}, "spatial": {}}
    sections = []
    for index, (cohort, profile, calibration) in enumerate(formats):
        label = f"F{index + 1}"
        shutil.copyfile(media / cohort / "SH01.mp4", out / "m" / f"{label}-source.mp4")
        projection = media / cohort / f"{profile}.mp4"
        target = out / "m" / f"{label}-projection.mp4"
        if calibration:
            _ffmpeg("-i", str(projection), "-c:v", "copy", "-af", "volume=0", "-c:a", "aac", str(target))
        else:
            shutil.copyfile(projection, target)
        key["format"][label] = {"cohort": cohort, "profile": f"{profile}@1", "calibration": calibration}
        sections.append(
            f'<section><h2>{label}</h2><div class="pair"><figure><figcaption>source</figcaption>'
            f'<video src="m/{label}-source.mp4" controls loop></video></figure><figure><figcaption>projection'
            f'</figcaption><video src="m/{label}-projection.mp4" controls loop></video></figure></div>'
            f"{_radios(label, FORMAT_ITEMS)}</section>"
        )
    for index, (cohort, calibration) in enumerate(spatial):
        label = f"S{index + 1}"
        assertions = json.loads((media / cohort / "spatial.json").read_text(encoding="utf-8"))
        if calibration:
            assertions = [*assertions, PLANTED]
        rng.shuffle(assertions)
        for shot, view in (("SH01", "master"), ("SH02", "reverse")):
            _ffmpeg("-i", str(media / cohort / f"{shot}.mp4"), "-frames:v", "1", str(out / "m" / f"{label}-{view}.png"))
        key["spatial"][label] = {"cohort": cohort, "calibration": calibration}
        listing = "".join(
            f"<li><b>{a['evidence_class']}</b> {html.escape(a['relation'])}"
            + (f" (confidence {a['confidence']})" if a.get("confidence") is not None else "")
            + "</li>"
            for a in assertions
        )
        frames = "".join(
            f'<figure><figcaption>{view.upper()}</figcaption><div class="frame"><img src="m/{label}-{view}.png">'
            f"{_span_boxes(assertions, view.upper())}</div></figure>"
            for view in ("master", "reverse")
        )
        sections.append(
            f'<section><h2>{label}</h2><div class="pair">{frames}</div><ul>{listing}</ul>'
            f"{_radios(label, SPATIAL_ITEMS)}</section>"
        )
    style = (
        "body{font-family:system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px}"
        "section{border:1px solid #ccc;border-radius:8px;padding:16px;margin:16px 0}"
        ".pair{display:flex;gap:16px;flex-wrap:wrap}figure{margin:0;flex:1;min-width:280px}"
        "video,img{max-width:100%;max-height:360px;display:block;background:#000}"
        ".frame{position:relative;display:inline-block}.span{position:absolute;border:2px dashed #0af}"
        ".span span{background:#0af;color:#fff;font-size:11px}textarea{width:100%}"
    )
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>M8-F blind review</title>'
        f"<style>{style}</style></head><body><h1>M8-F blind review</h1>"
        "<p>Format items (format-semantic@1): compare each projection with its source. Spatial items "
        "(m8f-spatial-review@1): dashed boxes are the regions VISIBLE assertions claim; judge each item from "
        "the frames. Give PASS or FAIL for every item.</p>"
        f"<form>{''.join(sections)}</form></body></html>"
    )
    (out / "index.html").write_text(page, encoding="utf-8")
    key_file.write_text(json.dumps(key, indent=2), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("media", type=Path)
    parser.add_argument("packet", type=Path)
    parser.add_argument("key", type=Path)
    parser.add_argument("--seed", type=int, default=20261015)
    args = parser.parse_args(argv)
    build(args.media, args.packet, args.key, seed=args.seed)
    print(args.packet / "index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
