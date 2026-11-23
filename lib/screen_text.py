"""Text burned into a short-form film (ADR-0160): captions, the episode title card and the next-episode card.

Most short-video viewers watch muted, so the narration is also shown on screen: each cue is cut into lines of at most
``LINE_CHARS`` characters and screens of at most two lines, timed in proportion to their length inside the cue, in a
bold outlined face inside the lower safe area. The episode opens with a title card at the top and, when another
episode follows, ends on a card that names the question it answers. Everything is one ASS script rendered by libass.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

LINE_CHARS = 32
LINES_PER_SCREEN = 2
TITLE_SECONDS = 1.8
TITLE_LINES = 2
END_SECONDS = 2.8
#: A face with Vietnamese and Chinese glyphs that the host has (``fc-list``); libass falls back when missing.
FONT = "Noto Sans"


@dataclass(frozen=True)
class TimedText:
    start: float
    end: float
    text: str


def wrap(text: str, width: int = LINE_CHARS) -> list[str]:
    """Words into lines of at most ``width`` characters (a longer word is a line of its own)."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def title_lines(text: str) -> str:
    """The title card in at most ``TITLE_LINES`` lines inside the frame; a longer title ends in an ellipsis."""
    lines = wrap(text, width=LINE_CHARS - 4)
    if len(lines) > TITLE_LINES:
        lines = [*lines[: TITLE_LINES - 1], lines[TITLE_LINES - 1].rstrip(".,;:!?…") + "…"]
    return "\\N".join(lines)


def caption_screens(start: float, end: float, text: str) -> list[TimedText]:
    """A cue's screens of at most two lines, each shown for a share of the cue proportional to its length."""
    lines = wrap(text)
    screens = ["\\N".join(lines[i : i + LINES_PER_SCREEN]) for i in range(0, len(lines), LINES_PER_SCREEN)]
    if not screens:
        return []
    weights = [max(1, len(s.replace("\\N", " "))) for s in screens]
    total = sum(weights)
    out: list[TimedText] = []
    cursor = start
    for screen, weight in zip(screens, weights, strict=True):
        share = (end - start) * weight / total
        out.append(TimedText(cursor, cursor + share, screen))
        cursor += share
    return out


def _clock(seconds: float) -> str:
    centis = max(0, round(seconds * 100))
    hours, rest = divmod(centis, 360000)
    minutes, rest = divmod(rest, 6000)
    secs, cs = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ")


def ass_script(
    *,
    width: int,
    height: int,
    duration: float,
    cues: Sequence[TimedText],
    title_card: str | None = None,
    end_card: str | None = None,
) -> str:
    """The ASS script of a film's on-screen text; sizes follow the frame's short side."""
    short = min(width, height)
    caption_size = round(short * 0.07)
    title_size = round(short * 0.058)
    end_size = round(short * 0.055)
    margin_v = round(height * 0.16)
    styles = [
        f"Style: Caption,{FONT},{caption_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,"
        f"{max(2, round(caption_size * 0.09))},1,2,{round(width * 0.06)},{round(width * 0.06)},{margin_v},1",
        f"Style: Title,{FONT},{title_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,3,"
        f"{round(title_size * 0.35)},0,8,{round(width * 0.08)},{round(width * 0.08)},{round(height * 0.08)},1",
        f"Style: End,{FONT},{end_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&HAA000000,-1,0,0,0,100,100,0,0,3,"
        f"{round(end_size * 0.4)},0,5,{round(width * 0.1)},{round(width * 0.1)},0,1",
    ]
    events: list[str] = []
    end_start = max(0.0, duration - END_SECONDS) if end_card else duration
    for cue in cues:
        stop = min(cue.end, end_start)
        if stop - cue.start > 0.05:
            events.append(f"Dialogue: 0,{_clock(cue.start)},{_clock(stop)},Caption,,0,0,0,,{_escape(cue.text)}")
    if title_card:
        events.append(
            f"Dialogue: 1,{_clock(0.0)},{_clock(min(TITLE_SECONDS, duration))},Title,,0,0,0,,"
            f"{{\\fad(150,250)}}{title_lines(_escape(title_card))}"
        )
    if end_card:
        text = "\\N".join(wrap(_escape(end_card), width=LINE_CHARS - 4))
        events.append(f"Dialogue: 1,{_clock(end_start)},{_clock(duration)},End,,0,0,0,,{{\\fad(250,0)}}{text}")
    return "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding",
            *styles,
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *events,
            "",
        ]
    )


__all__ = ["END_SECONDS", "LINE_CHARS", "TITLE_SECONDS", "TimedText", "ass_script", "caption_screens", "wrap"]
