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


def test_a_long_title_card_wraps_inside_the_frame_and_ends_in_an_ellipsis():
    # drama smoke run b961dc0a: a hook paragraph saved as the episode title ran past both edges on one line
    title = (
        "Tập 1 · Chiếc đồng hồ dừng ở chín giờ kém năm — nhưng chưa ai mở hộp thiếc. "
        "Hộp thiếc đựng gì mà cô gái phải ôm khư khư trong chiều mưa như thế?"
    )
    script = ass_script(width=576, height=1024, duration=28.0, cues=[], title_card=title)

    text = next(line for line in script.splitlines() if ",Title," in line).split("{\\fad(150,250)}", 1)[1]
    lines = text.split("\\N")
    assert len(lines) == 2
    assert all(len(line) <= LINE_CHARS - 3 for line in lines)
    assert lines[0].startswith("Tập 1 · Chiếc đồng hồ")
    assert lines[1].endswith("…")


def test_a_short_title_card_stays_on_one_line():
    script = ass_script(width=576, height=1024, duration=28.0, cues=[], title_card="Tập 1 · Hộp thiếc")
    assert ",Title,,0,0,0,,{\\fad(150,250)}Tập 1 · Hộp thiếc" in script
