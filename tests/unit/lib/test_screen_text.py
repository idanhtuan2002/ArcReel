"""On-screen text of a short film: captions, title card, next-episode card (ADR-0160)."""

from __future__ import annotations

from lib.screen_text import END_SECONDS, LINE_CHARS, TimedText, ass_script, caption_screens, wrap


def test_a_cue_is_cut_into_two_line_screens_timed_by_length():
    text = "Ông Bảy lau mái chèo bằng một mảnh vải cũ, trên kia cây cầu mới đã sáng đèn rực rỡ cả một khúc sông dài."
    screens = caption_screens(10.0, 16.0, text)
    assert all(len(line) <= LINE_CHARS for s in screens for line in s.text.split("\\N"))
    assert all(len(s.text.split("\\N")) <= 2 for s in screens)
    assert screens[0].start == 10.0
    assert abs(screens[-1].end - 16.0) < 1e-6
    assert " ".join(s.text.replace("\\N", " ") for s in screens) == text
    assert wrap("một") == ["một"]


def test_the_script_has_captions_a_title_card_and_an_end_card_that_does_not_overlap_captions():
    cues = [TimedText(0.0, 3.0, "Câu mở đầu."), TimedText(55.0, 60.0, "Câu cuối cùng của tập.")]
    script = ass_script(
        width=1080,
        height=1920,
        duration=60.0,
        cues=cues,
        title_card="Tập 2 · Bến sông",
        end_card="Tập sau: ai là người khách cuối?",
    )
    assert "PlayResX: 1080" in script
    assert "Style: Caption,Noto Sans" in script
    assert ",Title,,0,0,0,,{\\fad(150,250)}Tập 2 · Bến sông" in script
    end_line = next(line for line in script.splitlines() if ",End," in line)
    assert end_line.startswith(f"Dialogue: 1,0:00:{60 - END_SECONDS:05.2f},0:01:00.00,End")
    last_caption = [line for line in script.splitlines() if ",Caption," in line][-1]
    assert f"0:00:{60 - END_SECONDS:05.2f},Caption" in last_caption


def test_no_cards_when_none_are_given():
    script = ass_script(width=1920, height=1080, duration=10.0, cues=[TimedText(0, 2, "Một câu {lạ}.")])
    assert ",Title," not in script
    assert ",End," not in script
    assert "{lạ}" not in script
