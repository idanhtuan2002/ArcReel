"""Fixed technical checks of a final film's subtitles and picture, run as part of every review.

Subtitles must say the narration (normalized text similarity), be Vietnamese, carry no mis-decoded UTF-8 and no
placeholder text. The picture must not be black for long and, in most frames, must fill at least half of the frame. Each failure is a CRITICAL
finding with the stage that repairs it; the checks read only the final, its subtitle sidecar and the narration.

Delivery checks (loudness against the render contract, dead air, subtitle reading speed and event duration) are MINOR
findings: they are recorded and shown with every review but never send the run back, so reviewer qualification is
unchanged.
"""

from __future__ import annotations

import re
import subprocess
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from lib.presentation_renderer import RenderRefused, measure_loudness
from r2.automation.assessment import AssessmentFinding
from r2.contracts.automation import RunStage

MIN_NARRATION_SIMILARITY = 0.85
MIN_VIETNAMESE_MARKED_LETTERS = 0.05
MAX_BLACK_SHARE = 0.2
MIN_PICTURE_AREA = 0.5
MAX_SMALL_PICTURE_SHARE = 0.2

TARGET_LUFS = -14.0
LOUDNESS_TOLERANCE_LU = 2.0
MAX_TRUE_PEAK_DB = -0.5
DEAD_AIR_SECONDS = 3.0
DEAD_AIR_DB = -50
#: Netflix Timed Text Style Guide: adult reading speed (English; the Vietnamese figure is not published to us) and
#: the general minimum (5/6 s) and maximum (7 s) subtitle event duration.
MAX_CHARACTERS_PER_SECOND = 20.0
MIN_CUE_SECONDS = 5 / 6
MAX_CUE_SECONDS = 7.0

_CUE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
_SILENCE = re.compile(r"silence_duration:\s*([0-9.]+)")
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


def _cues(srt: str) -> list[tuple[float, str]]:
    """``(seconds on screen, text)`` of every cue of ``srt``."""
    cues: list[tuple[float, str]] = []
    for block in re.split(r"\n\s*\n", srt.replace("\r\n", "\n").strip()):
        lines = block.split("\n")
        for index, line in enumerate(lines):
            match = _CUE.search(line)
            if match is None:
                continue
            h1, m1, s1, f1, h2, m2, s2, f2 = (int(v) for v in match.groups())
            start = h1 * 3600 + m1 * 60 + s1 + f1 / 1000
            end = h2 * 3600 + m2 * 60 + s2 + f2 / 1000
            cues.append((end - start, " ".join(text.strip() for text in lines[index + 1 :] if text.strip())))
            break
    return cues


def timing_findings(srt: str, *, unit_key: str) -> list[AssessmentFinding]:
    """MINOR findings for cues read too fast, flashed too briefly or held too long."""
    fast = short = long = 0
    for seconds, text in _cues(srt):
        if not text:
            continue
        if seconds > 0 and len(text) / seconds > MAX_CHARACTERS_PER_SECOND:
            fast += 1
        if seconds < MIN_CUE_SECONDS:
            short += 1
        if seconds > MAX_CUE_SECONDS:
            long += 1
    found: list[AssessmentFinding] = []
    for code, count, detail in (
        ("CHECK_SUBTITLE_TOO_FAST", fast, f"faster than {MAX_CHARACTERS_PER_SECOND:.0f} characters per second"),
        ("CHECK_SUBTITLE_TOO_SHORT", short, f"on screen under {MIN_CUE_SECONDS:.2f}s"),
        ("CHECK_SUBTITLE_TOO_LONG", long, f"on screen over {MAX_CUE_SECONDS:.0f}s"),
    ):
        if count:
            found.append(
                AssessmentFinding(
                    code=code,
                    severity="MINOR",
                    unit_key=unit_key,
                    repair_stage=RunStage.SCRIPT,
                    detail=f"{count} cue(s) {detail}",
                )
            )
    return found


def sound_findings(final: Path, *, unit_key: str, ffmpeg: str = "ffmpeg") -> list[AssessmentFinding]:
    """MINOR findings for a final whose loudness misses the delivery target or that holds dead air."""
    found: list[AssessmentFinding] = []
    try:
        measured = measure_loudness(final, ffmpeg=ffmpeg)
    except RenderRefused:
        measured = None
    if measured is not None:
        try:
            integrated, peak = float(measured["input_i"]), float(measured["input_tp"])
        except ValueError:
            integrated, peak = float("-inf"), float("-inf")
        if abs(integrated - TARGET_LUFS) > LOUDNESS_TOLERANCE_LU or peak > MAX_TRUE_PEAK_DB:
            found.append(
                AssessmentFinding(
                    code="CHECK_LOUDNESS_OFF_TARGET",
                    severity="MINOR",
                    unit_key=unit_key,
                    repair_stage=RunStage.RENDER,
                    detail=f"{integrated:.1f} LUFS, true peak {peak:.1f} dBTP (target {TARGET_LUFS:.0f} LUFS)",
                )
            )
    log = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-i",
            str(final),
            "-vn",
            "-af",
            f"silencedetect=n={DEAD_AIR_DB}dB:d={DEAD_AIR_SECONDS}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    ).stderr
    gaps = [float(value) for value in _SILENCE.findall(log)]
    if gaps:
        found.append(
            AssessmentFinding(
                code="CHECK_DEAD_AIR",
                severity="MINOR",
                unit_key=unit_key,
                repair_stage=RunStage.MEDIA,
                detail=f"{len(gaps)} silence(s) of {DEAD_AIR_SECONDS:.0f}s or more, longest {max(gaps):.1f}s",
            )
        )
    return found


__all__ = ["picture_findings", "sound_findings", "subtitle_findings", "subtitle_text", "timing_findings"]
