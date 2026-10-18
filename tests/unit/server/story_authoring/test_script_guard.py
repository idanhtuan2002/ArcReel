from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from server.story_authoring import _cjk_ranges
from server.story_authoring.script_guard import build_cjk_ranges, find_cjk, has_cjk, is_cjk, no_cjk_pattern

DATA = Path(__file__).resolve().parents[4] / "server" / "story_authoring" / "data" / "unicode" / "16.0.0"
VENDORED = {
    "Scripts.txt": "9e88f0a677df47311106340be8ede2ecdacd9c1c931831218d2be6d5508e0039",
    "Blocks.txt": "f3907b395d410f1b97342292ca6bc83dd12eb4b205f2a0c48efdef99e517d7b0",
}


def test_the_vendored_unicode_files_are_unmodified():
    for name, digest in VENDORED.items():
        assert hashlib.sha256((DATA / name).read_bytes()).hexdigest() == digest


def test_the_committed_table_equals_a_regeneration():
    regenerated = build_cjk_ranges(
        (DATA / "Scripts.txt").read_text(encoding="utf-8"), (DATA / "Blocks.txt").read_text(encoding="utf-8")
    )
    assert regenerated == _cjk_ranges.CJK_RANGES
    assert _cjk_ranges.UNICODE_VERSION == "16.0.0"


@pytest.mark.parametrize(
    "code",
    [
        0x4E00,  # CJK Unified Ideographs
        0x9FFF,
        0x3400,  # Extension A
        0x20000,  # Extension B
        0x2A700,  # Extension C
        0x2B740,  # Extension D
        0x2B820,  # Extension E
        0x2CEB0,  # Extension F
        0x30000,  # Extension G
        0x31350,  # Extension H
        0x2EBF0,  # Extension I
        0xF900,  # Compatibility Ideographs
        0x2F800,  # Compatibility Ideographs Supplement
        0x3041,  # Hiragana
        0x30A1,  # Katakana
        0x1B000,  # Kana Supplement
        0xAC00,  # Hangul Syllables
        0xA960,  # Hangul Jamo Extended-A
        0xD7B0,  # Hangul Jamo Extended-B
        0x3105,  # Bopomofo
        0x3001,  # 、 CJK Symbols and Punctuation
        0x3002,  # 。
        0xFF0C,  # ， fullwidth comma
        0xFF01,  # ！
        0x2F00,  # Kangxi Radicals
        0x2FF0,  # Ideographic Description Characters
        0xFE30,  # CJK Compatibility Forms
        0x1F200,  # Enclosed Ideographic Supplement
    ],
)
def test_cjk_code_points_are_detected(code):
    assert is_cjk(chr(code))


VIETNAMESE = (
    "Minh mở cửa căn nhà cũ, bụi phủ trên bàn thờ cha. “Anh về rồi à?” — Lan hỏi; giọng chị khẽ run… "
    "Ơn trời, ước mơ đã thành! Đường xa, gió lạnh: ỷ, ỹ, ự, ữ, ặ, ẵ, ố, ỗ, ừ. 1.234,5 đồng (≈ 10%)."
)


def test_vietnamese_text_with_punctuation_has_no_hit():
    assert find_cjk(VIETNAMESE) == ()
    assert not has_cjk(VIETNAMESE)


def test_hits_report_positions_and_characters():
    hits = find_cjk("Anh ấy 突然 dừng lại。")
    assert [(hit.index, hit.char) for hit in hits] == [(7, "突"), (8, "然"), (18, "。")]


def test_the_grammar_pattern_rejects_bmp_cjk_and_accepts_vietnamese():
    pattern = re.compile(no_cjk_pattern().encode("utf-8").decode("unicode_escape"))
    assert pattern.match(VIETNAMESE)
    assert not pattern.match("Mưa 突然 rơi")
    assert not pattern.match("Mưa rơi。")


def test_the_default_grammar_pattern_is_bmp_only():
    assert all(ord(ch) <= 0xFFFF for ch in no_cjk_pattern())
    assert any(ord(ch) > 0xFFFF for ch in no_cjk_pattern(include_astral=True))
