"""L1 deterministic checks of story prose and the shared finding/severity model.

Every check is pure and reproducible. Findings carry a verbatim quote of the text they point at (empty only for
whole-text facts such as length), a stable code, and one of the five severity classes of the amendment's quality
policy (Change G): hard structural and hard integrity findings block; narrative-critical findings need a bounded
repair or an explicit Human exception; stylistic and local-model-limit findings are listed for the Human.

The intra-chapter near-duplicate core is a clean-room port of Huohuo
``workbench-server/src/services/novel/novel-intra-chapter-dedupe.ts`` (pin ``f104b853``, source sha256
``2a633d79…f393``): ``find_intra_chapter_near_duplicate`` and its helpers, branch for branch. The
``DONOR_PUNCTUATION`` profile reproduces the donor's Chinese punctuation exactly and is verified against the
unmodified source by ``tests/integration/donor_parity/test_huohuo_dedupe.py``. At runtime Vietnamese prose uses
``strip_replayed_sentences``, a sentence-level form of the same normalized-fingerprint idea, because the donor's
Han-tuned heuristics over-remove on Vietnamese (recorded deviation). JS ``\\s`` and ``trim()`` are emulated with the explicit ECMAScript
whitespace set. Indices are code points; the donor mixes code points and UTF-16 units, which agree on BMP text.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from server.story_authoring.script_guard import find_cjk


class Severity(StrEnum):
    HARD_STRUCTURAL = "HARD_STRUCTURAL"
    HARD_INTEGRITY = "HARD_INTEGRITY"
    NARRATIVE_CRITICAL = "NARRATIVE_CRITICAL"
    STYLISTIC = "STYLISTIC"
    LOCAL_MODEL_LIMIT = "LOCAL_MODEL_LIMIT"


BLOCKING = frozenset({Severity.HARD_STRUCTURAL, Severity.HARD_INTEGRITY})


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    node_id: str
    message: str
    quote: str = ""

    @property
    def blocking(self) -> bool:
        return self.severity in BLOCKING


# --- ECMAScript whitespace -------------------------------------------------------------------------

_JS_WS_CHARS = "".join(
    chr(cp)
    for cp in (
        0x09,
        0x0A,
        0x0B,
        0x0C,
        0x0D,
        0x20,
        0xA0,
        0x1680,
        *range(0x2000, 0x200B),
        0x2028,
        0x2029,
        0x202F,
        0x205F,
        0x3000,
        0xFEFF,
    )
)
_JS_WS = "[" + re.escape(_JS_WS_CHARS) + "]"


def _js_trim(value: str) -> str:
    return value.strip(_JS_WS_CHARS)


# --- syllables and foreign words -------------------------------------------------------------------

_TOKEN = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")
_TONE_MARKS = {"̀", "́", "̃", "̉", "̣"}
_ONSETS = (
    "ngh",
    "ng",
    "nh",
    "ch",
    "gh",
    "gi",
    "kh",
    "ph",
    "qu",
    "th",
    "tr",
    "b",
    "c",
    "d",
    "đ",
    "g",
    "h",
    "k",
    "l",
    "m",
    "n",
    "p",
    "r",
    "s",
    "t",
    "v",
    "x",
    "",
)
_RHYME = re.compile(r"^(?:o|u)?(?:iê|yê|uô|ươ|ia|ya|ua|ưa|a|ă|â|e|ê|i|y|o|ô|ơ|u|ư)(?:ch|ng|nh|c|m|n|p|t|i|y|o|u)?$")
_FOREIGN_LETTERS = set("fjwz")


def syllable_tokens(text: str) -> list[str]:
    return [part for token in _TOKEN.findall(text) for part in token.split("-")]


def count_syllables(text: str) -> int:
    return len(syllable_tokens(text))


def _without_tone(syllable: str) -> str:
    decomposed = unicodedata.normalize("NFD", syllable.lower())
    return unicodedata.normalize("NFC", "".join(ch for ch in decomposed if ch not in _TONE_MARKS))


def is_vietnamese_syllable(token: str) -> bool:
    base = _without_tone(token)
    if not base or set(base) & _FOREIGN_LETTERS:
        return False
    for onset in _ONSETS:
        if base.startswith(onset) and _RHYME.match(base[len(onset) :]):
            return True
    return base == "gi"


def foreign_words(text: str) -> list[str]:
    """Latin-letter tokens that cannot be Vietnamese syllables (F25 code-mixing)."""
    return [token for token in syllable_tokens(text) if token.isascii() and not is_vietnamese_syllable(token)]


def repeated_trigram_excess(text: str) -> int:
    words = [w.lower() for w in syllable_tokens(text)]
    counts = Counter(tuple(words[i : i + 3]) for i in range(len(words) - 2))
    return sum(count - 1 for count in counts.values() if count > 2)


# --- intra-chapter near-duplicate core (Huohuo port) -----------------------------------------------


@dataclass(frozen=True)
class PunctuationProfile:
    name: str
    removed: str  # characters dropped by norm(), besides whitespace
    sentence_end: str  # sentence terminators


DONOR_PUNCTUATION = PunctuationProfile(name="donor", removed="，。！？、；：…—-~·\"'「」『』“”'", sentence_end="。！？")
VIETNAMESE_PUNCTUATION = PunctuationProfile(name="vi", removed=",.!?;:…—–-~·\"'“”‘’()«»", sentence_end=".!?…")


@dataclass(frozen=True)
class DupHit:
    remove_start: int
    remove_end: int
    fingerprint_len: int
    excerpt: str


class _Dedupe:
    def __init__(self, profile: PunctuationProfile) -> None:
        removed = re.escape(profile.removed)
        ends = re.escape(profile.sentence_end)
        self._ws_run = re.compile(_JS_WS + "+")
        self._removed = re.compile("[" + removed + "]")
        self._ends_at = re.compile("[" + ends + "]\\Z")
        self._sentence = re.compile("[^\n" + ends + "]+[" + ends + "]?")
        self._ends = set(profile.sentence_end)
        self._ends_or_nl = set(profile.sentence_end) | {"\n"}
        self._rest_clause = re.compile("^[^" + ends + "]{0,120}[" + ends + "]?")
        self._lazy_sentence = re.compile("^[\\s\\S]*?[" + ends + "]")
        self._removed_chars = set(profile.removed)

    def norm(self, s: str) -> str:
        return self._removed.sub("", self._ws_run.sub("", s))

    @staticmethod
    def shared_prefix_len(a: str, b: str) -> int:
        n = min(len(a), len(b))
        i = 0
        while i < n and a[i] == b[i]:
            i += 1
        return i

    def ends_sentence(self, s: str) -> bool:
        return bool(self._ends_at.search(_js_trim(s)))

    def broken_variant_of(self, earlier: str, later: str) -> bool:
        na, nb = self.norm(earlier), self.norm(later)
        if len(na) < 12 or len(nb) < 12:
            return False
        if na == nb:
            return True
        sp = self.shared_prefix_len(na, nb)
        need = max(10, math.floor(min(len(na), len(nb)) * 0.45))
        if sp >= need:
            if nb.startswith(na) and self.ends_sentence(earlier):
                return False
            if sp < min(len(na), len(nb)):
                return True
        return self.broken_core_variant(na, nb)

    def broken_core_variant(self, na: str, nb: str) -> bool:
        def probe(short: str, long: str) -> bool:
            if len(short) < 10 or len(long) < 10:
                return False
            core_need = 6
            for i in range(len(long) - core_need + 1):
                sp = self.shared_prefix_len(short, long[i:])
                if sp < core_need or sp >= len(short):
                    continue
                if short[sp] != (long[i + sp] if i + sp < len(long) else None):
                    return True
            return False

        return probe(na, nb) or probe(nb, na)

    def find_divergent_core(self, na: str, nb: str) -> tuple[int, str, str] | None:
        core_need = 6
        best: tuple[int, str, str] | None = None
        for i in range(len(nb) - core_need + 1):
            sp = self.shared_prefix_len(na, nb[i:])
            if sp < core_need or sp >= len(na):
                continue
            if i + sp < len(nb) and na[sp] == nb[i + sp]:
                continue
            if best is None or sp > best[0]:
                best = (sp, na[sp:], nb[i + sp :])
        for i in range(len(na) - core_need + 1):
            sp = self.shared_prefix_len(nb, na[i:])
            if sp < core_need or sp >= len(nb):
                continue
            if i + sp < len(na) and nb[sp] == na[i + sp]:
                continue
            if best is None or sp > best[0]:
                best = (sp, na[i + sp :], nb[sp:])
        return best

    def prefer_complete_sentence(self, a: str, b: str) -> str:
        na, nb = self.norm(a), self.norm(b)
        if na == nb:
            return "b"
        head_sp = self.shared_prefix_len(na, nb)
        if head_sp >= 10:
            if nb.startswith(na) and self.ends_sentence(a):
                return "a"
            if na.startswith(nb) and self.ends_sentence(b):
                return "b"
            sa, sb = na[head_sp:], nb[head_sp:]
            if len(sa) <= 2 and len(sb) > 4:
                return "a"
            if len(sb) <= 2 and len(sa) > 4:
                return "b"
            if len(sa) != len(sb):
                return "a" if len(sa) < len(sb) else "b"
        core = self.find_divergent_core(na, nb)
        if core is not None:
            _, sa, sb = core
            if len(sa) <= 2 and len(sb) > 4:
                return "a"
            if len(sb) <= 2 and len(sa) > 4:
                return "b"
            if len(sa) != len(sb):
                return "a" if len(sa) < len(sb) else "b"
        return "a" if len(na) <= len(nb) else "b"

    def looks_broken_against(self, prev: str, reference_norm: str) -> bool:
        prev_n = self.norm(prev)
        if len(prev_n) < 12 or not reference_norm:
            return False
        if prev_n in reference_norm:
            return False
        if self.broken_core_variant(prev_n, reference_norm):
            return True
        prefix_hint = prev_n[: min(8, len(prev_n))]
        return len(prefix_hint) >= 4 and prefix_hint in reference_norm

    def sentences_of(self, chunk: str) -> list[str]:
        return [s for s in self._sentence.findall(chunk) if len(s) >= 8]

    def sentence_spans_in(self, raw: str, start: int, end: int) -> list[tuple[int, int, str]]:
        piece = raw[start:end]
        return [
            (start + m.start(), start + m.end(), m.group(0))
            for m in self._sentence.finditer(piece)
            if len(m.group(0)) >= 8
        ]

    def is_skippable(self, ch: str) -> bool:
        return ch in _JS_WS_CHARS or ch in self._removed_chars

    def find(self, content: str, min_fingerprint: int = 36) -> DupHit | None:
        raw = content or ""
        if len(raw) < min_fingerprint * 3:
            return None
        n = self.norm(raw)
        if len(n) < min_fingerprint * 3:
            return None

        best: tuple[int, int] | None = None
        max_len = min(96, len(n) // 3)
        length = max_len
        while length >= min_fingerprint:
            step = 6 if length >= 48 else 3
            search_limit = len(n) - length * 2
            i = 0
            while i <= search_limit:
                fp = n[i : i + length]
                j = n.find(fp, i + length)
                if j >= 0:
                    best = (length, j)
                    break
                i += step
            if best is not None:
                break
            length -= 2
        if best is None:
            return None

        best_len, best_b = best
        fp = n[best_b : best_b + best_len]
        offset = math.floor(best_len * 0.15)
        anchor_n = fp[offset : offset + min(28, max(16, math.floor(best_len * 0.3)))]
        if len(anchor_n) < 12:
            return None

        first_end = -1
        second_start = -1
        second_end = -1
        chars = raw
        i = 0
        while i < len(chars):
            if first_end >= 0 and i < first_end:
                i += 1
                continue
            acc = ""
            j = i
            while j < len(chars) and len(acc) < len(anchor_n) + 12:
                ch = chars[j]
                if self.is_skippable(ch):
                    j += 1
                    continue
                acc += ch
                if len(acc) >= len(anchor_n) and anchor_n in acc:
                    if first_end < 0:
                        first_end = j + 1
                        break
                    second_start = i
                    second_end = j + 1
                    break
                j += 1
            if second_start >= 0:
                break
            i += 1
        if second_start < 0 or second_end < 0:
            return None

        while second_start > 0 and raw[second_start - 1] not in self._ends_or_nl:
            second_start -= 1
        anchor_second_start = second_start

        end = second_end
        match = self._rest_clause.match(raw[end:])
        if match:
            end += len(match.group(0))

        head_chunk = raw[:anchor_second_start]
        head_n = self.norm(head_chunk)
        head_sents = self.sentences_of(head_chunk)
        guard = 0
        while guard < 10:
            guard += 1
            more = raw[end : end + 320]
            if not _js_trim(more):
                break
            m2 = self._lazy_sentence.match(more)
            if not m2 or len(m2.group(0)) < 12:
                break
            sentence = m2.group(0)
            sn = self.norm(sentence)
            head_fp = fp[: min(20, len(fp))]
            if any(
                self.broken_variant_of(s, sentence) and self.prefer_complete_sentence(s, sentence) == "b"
                for s in head_sents
            ):
                break
            dup_of_head = len(sn) >= 16 and sn in head_n
            broken_of_head = any(
                self.broken_variant_of(sentence, s) and self.prefer_complete_sentence(sentence, s) == "b"
                for s in head_sents
            )
            same_scene = head_fp in self.norm(sentence)
            if not same_scene and not dup_of_head and not broken_of_head:
                nxt = self._lazy_sentence.match(raw[end + len(sentence) :])

                def replays(s: str, nxt_text: str) -> bool:
                    nn, sn0 = self.norm(nxt_text), self.norm(s)
                    return nn == sn0 or nn.startswith(sn0) or sn0.startswith(nn[: min(12, len(nn))])

                next_is_replay = nxt is not None and any(replays(s, nxt.group(0)) for s in head_sents)
                if next_is_replay and len(sentence) < 100:
                    end += len(sentence)
                    continue
                break
            end += len(sentence)

        window_from = max(first_end, anchor_second_start - 280)
        after_sents = self.sentences_of(raw[end:])
        earliest = anchor_second_start
        for sp_start, _sp_end, sp_text in self.sentence_spans_in(raw, window_from, anchor_second_start):
            before_n = self.norm(raw[:sp_start])
            vs_after = any(
                self.norm(sp_text) != self.norm(s)
                and self.broken_variant_of(sp_text, s)
                and self.prefer_complete_sentence(sp_text, s) == "b"
                for s in after_sents
            )
            vs_before = self.looks_broken_against(sp_text, before_n) or any(
                self.norm(sp_text) != self.norm(s)
                and self.broken_variant_of(sp_text, s)
                and self.prefer_complete_sentence(sp_text, s) == "b"
                for s in self.sentences_of(raw[:sp_start])
            )
            if vs_after or vs_before:
                earliest = sp_start
                break
        second_start = earliest

        while second_start > 0 and raw[second_start - 1] in _JS_WS_CHARS:
            second_start -= 1

        if end - second_start < min_fingerprint:
            return None
        remove_end = min(len(raw), end)
        excerpt = self._ws_run.sub(" ", raw[second_start : min(len(raw), second_start + 56)])
        return DupHit(remove_start=second_start, remove_end=remove_end, fingerprint_len=best_len, excerpt=excerpt)


_DEDUPE = {
    DONOR_PUNCTUATION.name: _Dedupe(DONOR_PUNCTUATION),
    VIETNAMESE_PUNCTUATION.name: _Dedupe(VIETNAMESE_PUNCTUATION),
}


def find_intra_chapter_near_duplicate(
    content: str, min_fingerprint: int = 36, *, profile: PunctuationProfile = VIETNAMESE_PUNCTUATION
) -> DupHit | None:
    return _DEDUPE[profile.name].find(content, min_fingerprint)


_TRIPLE_NEWLINES = re.compile(r"\n{3,}")


def strip_intra_chapter_near_duplicate(
    content: str, *, profile: PunctuationProfile = DONOR_PUNCTUATION
) -> tuple[str, tuple[DupHit, ...]]:
    """The donor's two-round removal around ``find``; a round that would remove half the text is not applied."""
    text = content
    hits: list[DupHit] = []
    for _ in range(2):
        hit = find_intra_chapter_near_duplicate(text, profile=profile)
        if hit is None:
            break
        nxt = _js_trim(_TRIPLE_NEWLINES.sub("\n\n", text[: hit.remove_start] + text[hit.remove_end :]))
        if len(nxt) < len(text) * 0.5:
            break
        text = nxt
        hits.append(hit)
    return text, tuple(hits)


_VI_SENTENCE = re.compile(r"[^.!?…\n]+[.!?…]*[”\"’»)]?")
_VI_NORM_DROP = re.compile(r"[\W_]+")
REPLAY_MIN_SYLLABLES = 8


def strip_replayed_sentences(content: str) -> tuple[str, tuple[DupHit, ...]]:
    """Vietnamese runtime form of the dedupe core: a sentence of at least ``REPLAY_MIN_SYLLABLES`` syllables whose
    normalized fingerprint already occurred earlier is removed; the first occurrence always stays.

    The donor's anchor-and-extend heuristics are tuned to Han characters and, applied to Vietnamese, remove
    sentences that are not repeated (recorded deviation, ``R2_STORY_DONOR_BASELINE.json`` S08).
    """
    seen: set[str] = set()
    removals: list[tuple[int, int]] = []
    for match in _VI_SENTENCE.finditer(content):
        sentence = match.group(0)
        if count_syllables(sentence) < REPLAY_MIN_SYLLABLES:
            continue
        key = _VI_NORM_DROP.sub("", sentence.lower())
        if key in seen:
            removals.append((match.start(), match.end()))
        else:
            seen.add(key)
    if not removals:
        return content, ()
    pieces: list[str] = []
    cursor = 0
    hits: list[DupHit] = []
    for start, end in removals:
        pieces.append(content[cursor:start])
        cursor = end
        hits.append(DupHit(start, end, end - start, " ".join(content[start:end].split())[:56]))
    pieces.append(content[cursor:])
    text = re.sub(r"[ \t]{2,}", " ", "".join(pieces))
    text = re.sub(r"[ \t]+\n", "\n", text)
    return _TRIPLE_NEWLINES.sub("\n\n", text).strip(), tuple(hits)


# --- surface checks --------------------------------------------------------------------------------

_META_LINE = re.compile(
    r"^\s*(?:#|\*\*|>|\[|\(|chương\s+\d|cảnh\s+\d|ghi chú|lưu ý|tóm tắt|dưới đây|sau đây là|note\b|scene\b|chapter\b)",
    re.IGNORECASE | re.MULTILINE,
)
_CLOSING = (".", "!", "?", "…", "”", '"', "»", "’")
_DIALOGUE_LINE = re.compile(r"^\s*(?:—|–|-|“|\")", re.MULTILINE)
_SENTENCE_START = re.compile(r"(?:^|[.!?…:][”\"’»)]?\s*|\n\s*|[—–\-“\"(]\s*)$")
_WORD = re.compile(r"[^\W\d_]+")


def meta_leaks(text: str) -> list[str]:
    """Whole lines that open with a heading, label or note marker."""
    lines = text.splitlines()
    starts = {text.count("\n", 0, m.start()) for m in _META_LINE.finditer(text)}
    return [lines[i].strip() for i in sorted(starts) if i < len(lines)]


def ends_cleanly(text: str) -> bool:
    return text.rstrip().endswith(_CLOSING)


def dialogue_lines(text: str) -> int:
    return len(_DIALOGUE_LINE.findall(text))


def unknown_names(text: str, allowed: set[str]) -> Counter[str]:
    """Capitalized syllable runs that are not sentence-initial and not made only of allowed name syllables."""
    allowed_syllables = {s.lower() for name in allowed for s in name.split()}
    found: Counter[str] = Counter()
    runs: list[tuple[int, int]] = []
    for match in _WORD.finditer(text):
        if not match.group(0)[0].isupper():
            continue
        if runs and text[runs[-1][1] : match.start()] == " ":
            runs[-1] = (runs[-1][0], match.end())
        else:
            runs.append((match.start(), match.end()))
    for start, end in runs:
        if _SENTENCE_START.search(text[:start]):
            continue
        name = text[start:end]
        if all(part.lower() in allowed_syllables for part in name.split()):
            continue
        found[name] += 1
    return found


@dataclass(frozen=True)
class SceneLengthWindow:
    minimum: int = 600
    maximum: int = 1000
    hard_maximum: int = 1400


def check_scene_prose(
    text: str, *, node_id: str, window: SceneLengthWindow, allowed_names: set[str], requires_dialogue: bool = False
) -> tuple[Finding, ...]:
    findings: list[Finding] = [
        Finding(
            "CJK", Severity.HARD_INTEGRITY, node_id, "CJK character in prose", text[max(0, h.index - 20) : h.index + 20]
        )
        for h in find_cjk(text)[:1]
    ]
    if not ends_cleanly(text):
        findings.append(
            Finding(
                "UNTERMINATED", Severity.HARD_INTEGRITY, node_id, "prose does not end a sentence", text.rstrip()[-40:]
            )
        )
    syllables = count_syllables(text)
    if syllables > window.hard_maximum:
        findings.append(
            Finding("LENGTH_HARD", Severity.HARD_STRUCTURAL, node_id, f"{syllables} syllables > {window.hard_maximum}")
        )
    elif not window.minimum <= syllables <= window.maximum:
        findings.append(
            Finding(
                "LENGTH_WINDOW",
                Severity.STYLISTIC,
                node_id,
                f"{syllables} syllables outside {window.minimum}-{window.maximum}",
            )
        )
    findings.extend(
        Finding("META_LEAK", Severity.HARD_STRUCTURAL, node_id, "heading, label or note in prose", leak)
        for leak in meta_leaks(text)[:3]
    )
    foreign = foreign_words(text)
    if foreign:
        severity = Severity.NARRATIVE_CRITICAL if len(foreign) > 2 else Severity.STYLISTIC
        findings.append(
            Finding("FOREIGN_WORDS", severity, node_id, f"{len(foreign)} non-Vietnamese words", " ".join(foreign[:8]))
        )
    _, duplicates = strip_replayed_sentences(text)
    findings.extend(
        Finding("NEAR_DUPLICATE", Severity.NARRATIVE_CRITICAL, node_id, "a passage repeats", hit.excerpt)
        for hit in duplicates
    )
    excess = repeated_trigram_excess(text)
    if syllables and excess * 1000 / syllables > 15:
        findings.append(Finding("REPETITION", Severity.STYLISTIC, node_id, f"repeated trigram excess {excess}"))
    for name, count in unknown_names(text, allowed_names).items():
        severity = Severity.NARRATIVE_CRITICAL if count >= 2 else Severity.STYLISTIC
        findings.append(Finding("UNKNOWN_NAME", severity, node_id, f"name not in the story bible ({count}x)", name))
    if requires_dialogue and dialogue_lines(text) == 0:
        findings.append(Finding("NO_DIALOGUE", Severity.STYLISTIC, node_id, "the scene contract asks for dialogue"))
    return tuple(findings)
