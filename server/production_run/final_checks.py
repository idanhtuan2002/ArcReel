"""Fixed technical checks of a final film's subtitles and picture, run as part of every review.

Subtitles must say the narration (normalized text similarity), be Vietnamese, carry no mis-decoded UTF-8 and no
placeholder text. The picture must not be black for long and, in most frames, must fill at least half of the frame. Each failure is a CRITICAL
finding with the stage that repairs it; the checks read only the final, its subtitle sidecar and the narration.
"""

from __future__ import annotations

import re
import subprocess
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from r2.automation.assessment import AssessmentFinding
from r2.contracts.automation import RunStage

MIN_NARRATION_SIMILARITY = 0.85
MIN_VIETNAMESE_MARKED_LETTERS = 0.05
MAX_BLACK_SHARE = 0.2
MIN_PICTURE_AREA = 0.5
MAX_SMALL_PICTURE_SHARE = 0.2

_TIMING = re.compile(r"^\d+$|-->")
_MOJIBAKE = re.compile("[Â-ô][\u0080-¿]|[\u0080-\u009f]")
_PLACEHOLDER = re.compile(r"\[\s*todo|\btodo\b|lorem ipsum|\{\{|\}\}", re.IGNORECASE)
_BLACK = re.compile(r"black_duration:(\d+(?:\.\d+)?)")
_CROP = re.compile(r"crop=(\d+):(\d+):\d+:\d+")
_VIETNAMESE = set("ăâđêôơưĂÂĐÊÔƠƯ")


def subtitle_text(srt: str) -> str:
    return " ".join(line.strip() for line in srt.splitlines() if line.strip() and not _TIMING.search(line))


def _normalized(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFC", text).lower() if ch.isalnum())


def _marked_share(text: str) -> float:
    letters = [ch for ch in unicodedata.normalize("NFC", text) if ch.isalpha()]
    if not letters:
        return 0.0
    marked = sum(1 for ch in letters if ch in _VIETNAMESE or len(unicodedata.normalize("NFD", ch)) > 1)
    return marked / len(letters)


def subtitle_findings(srt: str, narration: str, *, unit_key: str) -> list[AssessmentFinding]:
    text = subtitle_text(srt)
    found: list[AssessmentFinding] = []

    def add(code: str, detail: str) -> None:
        found.append(
            AssessmentFinding(
                code=code, severity="CRITICAL", unit_key=unit_key, repair_stage=RunStage.SCRIPT, detail=detail
            )
        )

    if not text:
        add("CHECK_SUBTITLES_MISSING", "the subtitle sidecar has no text")
        return found
    if _MOJIBAKE.search(text):
        add("CHECK_SUBTITLES_GARBLED", "subtitles contain mis-decoded UTF-8")
    if _PLACEHOLDER.search(text) or _PLACEHOLDER.search(narration):
        add("CHECK_PLACEHOLDER_TEXT", "subtitles or narration contain placeholder text")
    share = _marked_share(text)
    if share < MIN_VIETNAMESE_MARKED_LETTERS:
        add("CHECK_SUBTITLES_NOT_VIETNAMESE", f"{share:.1%} of subtitle letters carry Vietnamese marks")
    similarity = SequenceMatcher(None, _normalized(text), _normalized(narration), autojunk=False).ratio()
    if similarity < MIN_NARRATION_SIMILARITY:
        add("CHECK_SUBTITLES_NOT_NARRATION", f"subtitles match the narration at {similarity:.0%}")
    return found


def picture_findings(final: Path, *, unit_key: str, ffmpeg: str = "ffmpeg") -> list[AssessmentFinding]:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=width,height",
            "-select_streams",
            "v:0",
            "-of",
            "default=noprint_wrappers=1:nokey=0",
            str(final),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout
    values = dict(line.split("=", 1) for line in probe.splitlines() if "=" in line)
    duration, width, height = float(values["duration"]), int(values["width"]), int(values["height"])
    log = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-i",
            str(final),
            "-an",
            "-vf",
            "blackdetect=d=0.5:pix_th=0.10,cropdetect=limit=16:round=2:reset=1",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=True,
    ).stderr
    found: list[AssessmentFinding] = []
    black = sum(float(value) for value in _BLACK.findall(log))
    if duration > 0 and black / duration > MAX_BLACK_SHARE:
        found.append(
            AssessmentFinding(
                code="CHECK_BLACK_PICTURE",
                severity="CRITICAL",
                unit_key=unit_key,
                repair_stage=RunStage.MEDIA,
                detail=f"{black:.1f}s of {duration:.1f}s is black",
            )
        )
    areas = [int(w) * int(h) / (width * height) for w, h in _CROP.findall(log)] if width and height else []
    small = sum(1 for area in areas if area < MIN_PICTURE_AREA)
    if areas and small / len(areas) > MAX_SMALL_PICTURE_SHARE:
        found.append(
            AssessmentFinding(
                code="CHECK_PICTURE_NOT_FILLING_FRAME",
                severity="CRITICAL",
                unit_key=unit_key,
                repair_stage=RunStage.RENDER,
                detail=f"{small / len(areas):.0%} of frames fill less than {MIN_PICTURE_AREA:.0%} of the frame",
            )
        )
    return found


__all__ = ["picture_findings", "subtitle_findings", "subtitle_text"]
