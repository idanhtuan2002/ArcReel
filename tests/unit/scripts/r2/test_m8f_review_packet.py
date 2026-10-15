"""The M8-F blind packet hides the key and the calibration items."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.r2.m8f_review_packet import COHORTS, build

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _media(root: Path) -> Path:
    for cohort in COHORTS:
        out = root / cohort
        out.mkdir(parents=True)
        for name in ("SH01", "SH02", "vertical-9x16", "square"):
            subprocess.run(
                [
                    *("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=64x36:d=0.5"),
                    *("-f", "lavfi", "-i", "sine=frequency=440:duration=0.5", "-shortest", str(out / f"{name}.mp4")),
                ],
                check=True,
            )
        spans = [{"view": "MASTER", "x0": 0.1, "y0": 0.2, "x1": 0.2, "y1": 0.8}]
        assertions = [{"evidence_class": "VISIBLE", "subjects": ["red box"], "relation": "red box", "spans": spans}]
        (out / "spatial.json").write_text(json.dumps(assertions), encoding="utf-8")
    return root


def _rms(path: Path) -> float:
    out = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stderr
    return float(next(line for line in out.splitlines() if "mean_volume" in line).split(":")[1].split()[0])


def test_the_packet_hides_the_key_and_calibration_and_mutes_the_format_calibration(tmp_path: Path) -> None:
    media = _media(tmp_path / "media")
    packet, key_file = tmp_path / "packet", tmp_path / "key.json"

    build(media, packet, key_file, seed=7)

    key = json.loads(key_file.read_text(encoding="utf-8"))
    page = (packet / "index.html").read_text(encoding="utf-8")
    assert not (packet / "key.json").exists()
    assert len(key["format"]) == 5
    assert len(key["spatial"]) == 3
    assert [v["calibration"] for v in key["format"].values()].count(True) == 1
    assert [v["calibration"] for v in key["spatial"].values()].count(True) == 1
    for word in ("calibration", "WESTERN", "SHUANGWEN", "expected"):
        assert word.lower() not in page.lower()
    (format_calibration,) = [label for label, v in key["format"].items() if v["calibration"]]
    assert _rms(packet / "m" / f"{format_calibration}-projection.mp4") < -80
    (spatial_calibration,) = [label for label, v in key["spatial"].items() if v["calibration"]]
    section = page[page.index(f"<h2>{spatial_calibration}</h2>") :]
    assert "green sofa" in section[: section.index("</section>")]
