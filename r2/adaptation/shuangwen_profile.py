"""Bounded Python port of the pinned Huohuo outline-drama-fields surface (plan
Task 10; R2-DEC-031). Donor pin: ``appolloqin/huohuo-drama@f104b853b3563e124d9cde25f9331d323fb483b9``,
``workbench-server/src/services/novel/novel-outline-drama-fields.ts`` and its three
runtime dependencies (``novel-commercial-appeal-isomorph.ts``,
``novel-commercial-appeal-audit.ts`` -> ``novel-stakes-common-sense.ts``,
``novel-emotion-core-contract.ts``) — see
``docs/r2/evidence/R2_M6_DONOR_BASELINE.json``'s ``huohuo_drama_fields`` entry for
the exact vendored files, hashes, selected/excluded exports and why.

Ported: ``extractTagBlock`` (last-occurrence 【label】 extraction),
``sliceOutlineChapterSection`` (第N章 boundary slicing), the chapter 1-8 emotion-beat
and 爽型-vocabulary validation ``assertOutlineChapterFields`` composes, and the pinned
stakes-common-sense check (``detectStakesMismatchText`` and its full
Chinese-numeral-amount chain). NOT ported: book-level fields, the ten non-Shuangwen
chapter narrative fields, the prompt-block builders, and
``resolveWritingChapterOutline``/``upgradePromptToDramaOutline`` completion/repair
orchestration — none has an R2 consumer (spec section 5.3).

This module imports no donor source, no Node runtime, and no completion/repair or
persistence code — ``tests/unit/r2/test_m6_architecture_boundaries.py`` enforces the
first two structurally.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from r2.adaptation.errors import AdaptationProfileMismatchError
from r2.adaptation.hashing import compute_adaptation_hash
from r2.adaptation.profiles import ProfilePack
from r2.contracts.adaptation import (
    AdaptationProfileId,
    FindingDisposition,
    ProfileFinding,
    ScreenplayArtifactV2,
    ShuangwenAnalysis,
    ShuangwenType,
)
from r2.contracts.common import NonEmptyStr, R2ContractModel

# --- extractTagBlock / sliceOutlineChapterSection -----------------------------------

_CHAPTER_HEADER_RE = re.compile(r"第\s*(\d+)\s*章")
_NEXT_CHAPTER_RE = re.compile(r"第\s*\d+\s*章")
_SHUANG_TYPE_SPLIT_RE = re.compile(r"[|｜、，,\s]")
_MIN_BEAT_CODEPOINTS = 4


def extract_tag_block(text: str, label: str) -> str | None:
    """Port of ``extractTagBlock``: the content after the LAST ``【label】`` occurrence,
    up to the next ``【`` or ``第N章`` or end of text (repeated tags: last one wins)."""
    src = text or ""
    start_needle = f"【{label}】"
    last_end = -1
    search_from = 0
    while True:
        idx = src.find(start_needle, search_from)
        if idx < 0:
            break
        last_end = idx + len(start_needle)
        search_from = idx + 1
    if last_end < 0:
        return None
    rest = src[last_end:]
    next_tag = rest.find("【")
    next_ch_match = _NEXT_CHAPTER_RE.search(rest)
    end = len(rest)
    if next_tag >= 0:
        end = min(end, next_tag)
    if next_ch_match is not None:
        end = min(end, next_ch_match.start())
    value = rest[:end].strip()
    return value or None


def slice_outline_chapter_section(outline: str, chapter_number: int) -> str:
    """Port of ``sliceOutlineChapterSection``: the ``第chapter_number章`` header line
    through the line before the next strictly-greater chapter header, or end of text."""
    lines = (outline or "").split("\n")
    start = -1
    end = len(lines)
    for index, line in enumerate(lines):
        match = _CHAPTER_HEADER_RE.search(line)
        if match is None:
            continue
        number = int(match.group(1))
        if number == chapter_number and start < 0:
            start = index
        elif start >= 0 and number > chapter_number:
            end = index
            break
    if start < 0:
        return ""
    return "\n".join(lines[start:end])


def _code_point_length(value: str) -> int:
    return len(value)


def _non_empty(value: str | None, minimum: int = 2) -> bool:
    return bool(value) and _code_point_length((value or "").strip()) >= minimum


# --- pinned stakes-common-sense check (port of novel-stakes-common-sense.ts) --------

STAKES_COMMON_SENSE_MIN_MULTIPLIER = 20

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_SINGLE_TEN_PLUS_RE = re.compile(r"^十[一二三四五六七八九]$")
_TENS_RE = re.compile(r"^[一二两三四五六七八九]十$")
_TENS_PLUS_RE = re.compile(r"^[一二两三四五六七八九]十[一二三四五六七八九]$")

_AMOUNT_LEFT_BOUND = r"(?<![一二两三四五六七八九十百千万零廿两\d])"
_CN_OR_NUM = r"(?:\d{1,8}|[一二两三四五六七八九十百千万零廿几]+(?:来)?)"

_ANCHOR_PATTERNS = [
    re.compile(r"【常识锚】[^【】×]{0,100}?(?:约|大概|左右)?(\d{1,8})(?:块|元|工分|灵石|钱)"),
    re.compile(
        r"【常识锚】[^【】×]{0,100}?(?:约|大概|左右)?([一二两三四五六七八九十百千万零廿几]+(?:来)?)(?:块|元|工分|灵石|钱)"
    ),
    re.compile(r"(?:壮劳力)?月余[^。！？；×]{0,12}?(?:约|大概|左右)?(\d{1,8})(?:块|元|钱)"),
    re.compile(
        r"(?:壮劳力)?月余[^。！？；×]{0,12}?(?:约|大概|左右)?([一二两三四五六七八九十百千万零廿几]+)(?:块|元|钱)"
    ),
    re.compile(r"月薪[^。！？；×]{0,12}?(?:约|大概|左右)?(\d{1,8})(?:元|块|钱)"),
    re.compile(r"(?:一袋口粮|口粮价)[^。！？；×]{0,12}?(?:约|大概|左右)?(\d{1,8})(?:块|元|钱)"),
    re.compile(r"同阶[^。！？；]{0,12}?代价[^。！？；×]{0,10}?(?:约|大概|左右)?(\d{1,8})"),
]

_DEMAND_PATTERNS = [
    re.compile(
        rf"(?:要清|催缴|催|逼|拿不出|必须还|拍出来|顶账|抵账|现钱|交清|凑齐)[^。！？；]{{0,8}}?{_AMOUNT_LEFT_BOUND}({_CN_OR_NUM})(?:块|元|钱|工分|灵石)"
    ),
    re.compile(rf"(?:要|还){_AMOUNT_LEFT_BOUND}({_CN_OR_NUM})(?:块|元|钱|工分|灵石)"),
    re.compile(rf"欠(?:他的|下的|着|队里)?{_AMOUNT_LEFT_BOUND}({_CN_OR_NUM})(?:块|元|钱|工分|灵石)"),
    re.compile(rf"欠[^。！？；块元]{{0,6}}?{_AMOUNT_LEFT_BOUND}({_CN_OR_NUM})(?:块|元|钱|工分|灵石)"),
    re.compile(
        rf"{_AMOUNT_LEFT_BOUND}({_CN_OR_NUM})(?:块|元)(?:[零一二三四五六七八九十两\d毛分角]+)?(?:今天|今儿|天亮前|天黑前)?"
        r"(?:必须还|拍出来|拿不出|顶账|抵账|不还就|交清|凑齐)"
    ),
    re.compile(
        rf"{_AMOUNT_LEFT_BOUND}({_CN_OR_NUM})(?:块|元)钱?(?:今天|今儿|三日(?:内|里)?|限期|天亮前|天黑前)[^。！？]{{0,12}}?"
        r"(?:还|拿不出|卸(?:门|走)|顶账|交清|凑齐|扣粮)"
    ),
]


def _split2(value: str, separator: str) -> tuple[str, str]:
    """Matches JS ``const [hi, rest = ''] = value.split(separator)``: a full split on
    every occurrence, keeping only the first two parts and silently dropping any
    further ones."""
    parts = value.split(separator)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def _cn_debt_token_to_number(token: str) -> int | None:
    t = token.replace("钱", "")
    if not t:
        return None
    if t in ("几", "十几"):
        return 15
    if t in ("二十来", "廿"):
        return 20
    if t == "十":
        return 10
    if len(t) == 1 and t in _CN_DIGITS:
        return _CN_DIGITS[t]
    if _SINGLE_TEN_PLUS_RE.match(t):
        return 10 + _CN_DIGITS.get(t[1], 0)
    if _TENS_RE.match(t):
        return _CN_DIGITS.get(t[0], 0) * 10
    if _TENS_PLUS_RE.match(t):
        return _CN_DIGITS.get(t[0], 0) * 10 + _CN_DIGITS.get(t[2], 0)
    if "百" in t:
        hi, rest = _split2(t, "百")
        hundreds = 1 if (not hi or hi == "一") else _CN_DIGITS.get(hi, 1)
        low = _cn_debt_token_to_number(rest) if rest else 0
        return hundreds * 100 if low is None else hundreds * 100 + low
    if "千" in t:
        hi, rest = _split2(t, "千")
        thousands = 1 if (not hi or hi == "一") else _CN_DIGITS.get(hi, 1)
        low = _cn_debt_token_to_number(rest) if rest else 0
        return thousands * 1000 if low is None else thousands * 1000 + low
    if "万" in t:
        hi, rest = _split2(t, "万")
        if not hi or hi == "一":
            wan = 1
        else:
            recursive = _cn_debt_token_to_number(hi)
            wan = recursive if recursive is not None else _CN_DIGITS.get(hi, 1)
        low = _cn_debt_token_to_number(rest) if rest else 0
        return wan * 10000 if low is None else wan * 10000 + low
    return None


def _match_amount_token(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _cn_debt_token_to_number(token)


def extract_common_sense_anchor_amount(text: str) -> int | None:
    body = re.sub(r"\s+", "", text or "")
    if not body:
        return None
    for pattern in _ANCHOR_PATTERNS:
        match = pattern.search(body)
        if match is None:
            continue
        value = _match_amount_token(match.group(1))
        if value is not None and value > 0:
            return value
    return None


def extract_active_demand_amounts(text: str) -> list[int]:
    body = re.sub(r"\s+", "", text or "")
    out: list[int] = []
    for pattern in _DEMAND_PATTERNS:
        for match in pattern.finditer(body):
            value = _match_amount_token(match.group(1))
            if value is not None and value > 0:
                out.append(value)
    seen: set[int] = set()
    deduped: list[int] = []
    for value in out:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def infer_default_anchor_amount(text: str) -> int:
    t = text or ""
    if re.search(r"修真|玄幻|仙侠|灵石|功法|宗门", t):
        return 10
    if re.search(r"都市|职场|公司|月薪|白领|霸总", t):
        return 5000
    return 2


@dataclass(frozen=True)
class StakesCommonSenseResult:
    ok: bool
    message: str | None
    anchor: int | None
    demands: tuple[int, ...]
    min_required: int | None


def evaluate_stakes_common_sense(text: str) -> StakesCommonSenseResult:
    body = (text or "").strip()
    if len(body) < 12:
        return StakesCommonSenseResult(ok=True, message=None, anchor=None, demands=(), min_required=None)
    demands = extract_active_demand_amounts(body)
    if not demands:
        return StakesCommonSenseResult(ok=True, message=None, anchor=None, demands=(), min_required=None)
    explicit = extract_common_sense_anchor_amount(body)
    anchor = explicit if explicit is not None else infer_default_anchor_amount(body)
    min_required = anchor * STAKES_COMMON_SENSE_MIN_MULTIPLIER
    too_small = [d for d in demands if d < min_required]
    if too_small:
        shown = max(too_small)
        message = (
            f"赌注错位：恨场压迫主催须≥常识锚×{STAKES_COMMON_SENSE_MIN_MULTIPLIER}"
            f"（锚{anchor}→至少{min_required}）；当前主催约{shown}，压迫性不足。"
            "须抬主催或改锚；禁止旁衬大数字洗白；勿把「常识锚×N」里的N当成锚。"
        )
        return StakesCommonSenseResult(
            ok=False, message=message, anchor=anchor, demands=tuple(demands), min_required=min_required
        )
    return StakesCommonSenseResult(
        ok=True, message=None, anchor=anchor, demands=tuple(demands), min_required=min_required
    )


def detect_stakes_mismatch_text(text: str) -> str | None:
    return evaluate_stakes_common_sense(text).message


# --- ShuangwenFields: bounded parse over one outline document -----------------------


@dataclass(frozen=True)
class ShuangwenBookFields:
    """Empty in M6 v1: no book-level Huohuo field (theme, worldRules, castCores, ...)
    has an R2 consumer. Exists only so ``ShuangwenFields`` keeps the plan's fixed
    two-field shape."""


@dataclass(frozen=True)
class ShuangwenChapterFields:
    chapter_number: int
    hate: str | None
    shuang: str | None
    ji: str | None
    pan: str | None
    shuang_type_raw: str | None
    missing: tuple[str, ...]
    invalid: tuple[str, ...]

    @property
    def applicable(self) -> bool:
        return 1 <= self.chapter_number <= 8

    @property
    def ok(self) -> bool:
        return not self.missing and not self.invalid


@dataclass(frozen=True)
class ShuangwenFields:
    book_fields: ShuangwenBookFields
    chapter_fields: tuple[ShuangwenChapterFields, ...]

    def chapter(self, chapter_number: int) -> ShuangwenChapterFields | None:
        for fields in self.chapter_fields:
            if fields.chapter_number == chapter_number:
                return fields
        return None


def _shuang_type_head(raw: str) -> str:
    parts = _SHUANG_TYPE_SPLIT_RE.split(raw)
    return parts[0].strip() if parts else ""


def _parse_chapter_fields(outline: str, chapter_number: int) -> ShuangwenChapterFields:
    section = slice_outline_chapter_section(outline, chapter_number)
    hate = extract_tag_block(section, "恨")
    shuang = extract_tag_block(section, "爽")
    ji = extract_tag_block(section, "急")
    pan = extract_tag_block(section, "盼")
    shuang_type_raw = extract_tag_block(section, "爽型")

    if not (1 <= chapter_number <= 8):
        return ShuangwenChapterFields(
            chapter_number=chapter_number,
            hate=hate,
            shuang=shuang,
            ji=ji,
            pan=pan,
            shuang_type_raw=shuang_type_raw,
            missing=(),
            invalid=(),
        )

    missing: list[str] = []
    invalid: list[str] = []
    for label, value in (("恨", hate), ("爽", shuang), ("急", ji), ("盼", pan)):
        if not _non_empty(value, _MIN_BEAT_CODEPOINTS):
            missing.append(label)

    shuang_raw_trimmed = (shuang_type_raw or "").strip()
    if not _non_empty(shuang_raw_trimmed, 1):
        missing.append("爽型")
    else:
        head = _shuang_type_head(shuang_raw_trimmed)
        if head not in {member.value for member in ShuangwenType}:
            invalid.append(f"爽型:{shuang_raw_trimmed}")

    stake_blob = "\n".join(
        part
        for part in (
            extract_tag_block(outline, "常识锚"),
            extract_tag_block(section, "常识锚"),
            extract_tag_block(section, "本章起因"),
            extract_tag_block(section, "恨"),
            extract_tag_block(section, "急"),
            extract_tag_block(section, "局面变化"),
            extract_tag_block(section, "阻碍"),
        )
        if part
    )
    stake_bad = detect_stakes_mismatch_text(stake_blob)
    if stake_bad:
        invalid.append(f"赌注错位:{stake_bad}")

    return ShuangwenChapterFields(
        chapter_number=chapter_number,
        hate=hate,
        shuang=shuang,
        ji=ji,
        pan=pan,
        shuang_type_raw=shuang_type_raw,
        missing=tuple(missing),
        invalid=tuple(invalid),
    )


def parse_shuangwen_fields(text: str) -> ShuangwenFields:
    """Bounded port of the donor's chapter-scoped field parsing and 1-8 validation,
    over every ``第N章`` header found in ``text``, in ascending chapter-number order."""
    chapter_numbers = sorted({int(match.group(1)) for match in _CHAPTER_HEADER_RE.finditer(text or "")})
    chapter_fields = tuple(_parse_chapter_fields(text, number) for number in chapter_numbers)
    return ShuangwenFields(book_fields=ShuangwenBookFields(), chapter_fields=chapter_fields)


# --- evaluate_shuangwen: ShuangwenSourceScope -> ShuangwenAnalysis -------------------


class ShuangwenSourceScope(R2ContractModel):
    """Task-local, not a public domain contract (plan Task 10 fixed shape)."""

    chapter_start: int
    chapter_end: int
    source_refs: list[NonEmptyStr]


_DISPOSITION_SEVERITY = {
    FindingDisposition.INTEGRITY_BLOCK: "BLOCKING",
    FindingDisposition.PROFILE_BLOCK: "BLOCKING",
    FindingDisposition.ADVISORY: "ADVISORY",
    FindingDisposition.NOT_APPLICABLE: "NONE",
}


def _rule(profile_pack: ProfilePack, rule_id: str):
    for rule in profile_pack.rules:
        if rule.rule_id == rule_id:
            return rule
    raise AdaptationProfileMismatchError(
        f"profile pack for {profile_pack.ref.profile_id.value!r} does not declare required rule {rule_id!r}"
    )


def _finding(
    profile_pack: ProfilePack,
    *,
    rule_id: str,
    finding_id: str,
    disposition_override: FindingDisposition | None = None,
    target_path: str,
    source_span: str,
    **message_params: str,
) -> ProfileFinding:
    rule = _rule(profile_pack, rule_id)
    disposition = disposition_override if disposition_override is not None else rule.disposition
    return ProfileFinding(
        finding_id=finding_id,
        rule_id=rule.rule_id,
        rule_version=rule.rule_version,
        disposition=disposition,
        applicability=rule.applicability.value,
        severity=_DISPOSITION_SEVERITY[disposition],
        target_path=target_path,
        source_span=source_span,
        evidence_refs=[target_path],
        message_params=dict(message_params),
    )


def _combined_outline_text(screenplay: ScreenplayArtifactV2) -> str:
    """``evaluate_shuangwen``'s one text source: every scene's ``dramatic_text``, in
    scene order — screenplays adapted under this profile carry the same 【tag】
    outline markup the donor parses, authored directly into scene content. There is
    no separate raw-outline field on ``ScreenplayArtifactV2``."""
    return "\n".join(scene.dramatic_text for scene in screenplay.scenes)


def evaluate_shuangwen(
    screenplay: ScreenplayArtifactV2, *, source_scope: ShuangwenSourceScope, profile_pack: ProfilePack
) -> ShuangwenAnalysis:
    if profile_pack.ref.profile_id != AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN:
        raise AdaptationProfileMismatchError(
            f"evaluate_shuangwen requires a CN_SHORT_DRAMA_SHUANGWEN profile pack, got "
            f"{profile_pack.ref.profile_id.value!r}"
        )

    combined = _combined_outline_text(screenplay)
    fields = parse_shuangwen_fields(combined)
    chapters = [
        chapter
        for chapter in fields.chapter_fields
        if source_scope.chapter_start <= chapter.chapter_number <= source_scope.chapter_end
    ]

    applicable = source_scope.chapter_start <= 8
    findings: list[ProfileFinding] = []

    if not applicable or not chapters:
        findings.append(
            _finding(
                profile_pack,
                rule_id="SHUANGWEN_CHAPTER_1_8_SCOPE",
                finding_id="SHUANGWEN_CHAPTER_1_8_SCOPE:not-applicable",
                disposition_override=FindingDisposition.NOT_APPLICABLE,
                target_path=f"chapters[{source_scope.chapter_start}:{source_scope.chapter_end}]",
                source_span="n/a",
                chapter_start=str(source_scope.chapter_start),
                chapter_end=str(source_scope.chapter_end),
            )
        )
        hate = shuang = ji = pan = None
        shuang_type: ShuangwenType | None = None
    else:
        merged_missing: set[str] = set()
        merged_invalid: list[str] = []
        hate = shuang = ji = pan = None
        shuang_type_raw: str | None = None
        for chapter in chapters:
            merged_missing.update(chapter.missing)
            merged_invalid.extend(chapter.invalid)
            hate = chapter.hate or hate
            shuang = chapter.shuang or shuang
            ji = chapter.ji or ji
            pan = chapter.pan or pan
            shuang_type_raw = chapter.shuang_type_raw or shuang_type_raw

        if {"恨", "爽", "急", "盼"} & merged_missing:
            findings.append(
                _finding(
                    profile_pack,
                    rule_id="SHUANGWEN_FIELD_PARSING",
                    finding_id="SHUANGWEN_FIELD_PARSING:missing",
                    target_path=f"chapters[{source_scope.chapter_start}:{source_scope.chapter_end}]",
                    source_span=",".join(sorted(merged_missing & {"恨", "爽", "急", "盼"})),
                    missing_labels=",".join(sorted(merged_missing & {"恨", "爽", "急", "盼"})),
                )
            )
        if "爽型" in merged_missing or any(item.startswith("爽型:") for item in merged_invalid):
            findings.append(
                _finding(
                    profile_pack,
                    rule_id="SHUANGWEN_TYPE_VOCABULARY",
                    finding_id="SHUANGWEN_TYPE_VOCABULARY:invalid",
                    target_path=f"chapters[{source_scope.chapter_start}:{source_scope.chapter_end}]",
                    source_span=shuang_type_raw or "",
                )
            )
        stakes_invalid = [item for item in merged_invalid if item.startswith("赌注错位:")]
        if stakes_invalid:
            findings.append(
                _finding(
                    profile_pack,
                    rule_id="SHUANGWEN_STAKES_COMMON_SENSE",
                    finding_id="SHUANGWEN_STAKES_COMMON_SENSE:mismatch",
                    target_path=f"chapters[{source_scope.chapter_start}:{source_scope.chapter_end}]",
                    source_span=stakes_invalid[0],
                )
            )

        shuang_type = None
        if shuang_type_raw:
            head = _shuang_type_head(shuang_type_raw.strip())
            if head in {member.value for member in ShuangwenType}:
                shuang_type = ShuangwenType(head)

    draft = ShuangwenAnalysis(
        schema_version="r2-shuangwen-analysis-v1",
        content_hash="pending",
        chapter_start=source_scope.chapter_start,
        chapter_end=source_scope.chapter_end,
        hen_evidence=hate,
        shuang_evidence=shuang,
        ji_evidence=ji,
        pan_evidence=pan,
        shuang_type=shuang_type,
        findings=findings,
    )
    return draft.model_copy(update={"content_hash": compute_adaptation_hash(draft)})


__all__ = [
    "STAKES_COMMON_SENSE_MIN_MULTIPLIER",
    "ShuangwenBookFields",
    "ShuangwenChapterFields",
    "ShuangwenFields",
    "ShuangwenSourceScope",
    "StakesCommonSenseResult",
    "detect_stakes_mismatch_text",
    "evaluate_shuangwen",
    "evaluate_stakes_common_sense",
    "extract_active_demand_amounts",
    "extract_common_sense_anchor_amount",
    "extract_tag_block",
    "infer_default_anchor_amount",
    "parse_shuangwen_fields",
    "slice_outline_chapter_section",
]
