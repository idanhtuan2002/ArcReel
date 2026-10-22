"""分集规划服务：读源文窗口 → 调项目配置的文本模型 → 写分集账本并派生集文件。

plan() 从 planning_cursor 起取一个源文窗口，由文本模型一次规划出窗口内所有
剧情弧完整的集（标题/钩子/切分锚点；drama 另含分集大纲），schema 强约束 +
锚点存在性/唯一性/连续性机械校验，失败自动重试并附上一轮失败原因。用户需要
调整已规划内容时走「重置 + 重新规划」：先用 :mod:`lib.episode_reset` 把账本
退回到最早受影响的集（保留其前），再带 instructions 分批重新调用 plan()。

写入阶段在同一把项目锁内完成：写账本 + 按账本重写派生集文件 + 清理账本之外
的残留派生文件（含余文文件），下游读到的 ``source/episode_N.txt`` 永远与账本
一致。窗口字数与每批集数上限为内部默认，project.json 顶层
``planning_window_chars`` / ``planning_max_episodes`` 可覆盖。新提交的集号若
在磁盘上已有下游产物（该集实际已被消费过，见重置+重新规划场景），标 stale
而非直接覆盖状态，产物不删除。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import statistics
from bisect import bisect_left
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lib import script_review
from lib.async_thread import run_noninterruptible_sync, run_sync_transaction
from lib.episode_ledger import (
    SOURCE_FINGERPRINTS_KEY,
    SourceDoc,
    compute_source_fingerprints,
    discover_episode_files,
    discover_sources,
    episodes_without_source_range,
    has_downstream_products,
    mismatched_source_fingerprints,
    normalize_source_text,
    parse_episode_num,
    register_orphan_episode_entries,
)
from lib.episode_paths import episode_script_relpath, episode_source_path
from lib.episode_target_volume import EpisodeTargetVolume, resolve_episode_target_volume
from lib.formal_write import FormalWriteReceipt, project_metadata_lock
from lib.path_safety import PathTraversalError, safe_join
from lib.project_manager import ProjectManager, resolve_source_kind
from lib.prompt_builders_script import USER_INSTRUCTIONS_HEADER
from lib.text_backends.base import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    StructuredOutputExhaustedError,
    TextGenerationRequest,
    TextOutputTruncatedError,
    TextTaskType,
    truncate_for_log,
)
from lib.text_generator import TextGenerator
from lib.text_metrics import count_reading_units, reading_unit_noun
from lib.text_utils import strip_json_code_fences

logger = logging.getLogger(__name__)

# 窗口/批量内部默认值；project.json 顶层同名字段可覆盖
DEFAULT_PLANNING_WINDOW_CHARS = 30000
DEFAULT_PLANNING_MAX_EPISODES = 20

# LLM 输出未通过 schema / 机械校验时的总尝试次数（含首次）
_MAX_PLAN_ATTEMPTS = 3

# 注入 prompt 的已规划上下文条数上限（保持续写连贯，不膨胀 prompt）
_CONTEXT_EPISODES_LIMIT = 5

# 缺位置记录的集号在拒绝信息里最多逐个列出的条数（整本老项目可能每一集都缺，逐个列
# 会把错误信息撑成几百集的清单）
_MISSING_RANGE_LISTED_LIMIT = 10


class EpisodePlanningError(RuntimeError):
    """分集规划失败（源文缺失、校验重试耗尽等）。"""


class PlanningConflictError(EpisodePlanningError):
    """规划期间账本被并发修改，提交被拒绝；重新调用即可基于新状态规划。"""


@dataclass
class EpisodePlanSummary:
    """单集摘要：标题 + 钩子 + 体量（按 source_language 计的阅读单位）。"""

    episode: int
    title: str
    hook: str
    reading_units: int
    ledger_status: str


@dataclass
class LedgerStats:
    """全账本体量分布快照（机械现算，不做「多小算畸小」之类的阈值判断）。

    语义判断（是否与用户结构性偏好如「一章一集」「共 32 集」有出入）留给主 Agent 做——
    这里只报分布事实。
    """

    total_episodes: int
    smallest: list[tuple[int, int]]  # (集号, 体量) 体量最小的最多 5 集，按体量升序
    median_units: int | None
    target_volume: EpisodeTargetVolume | None


@dataclass
class PlanResult:
    episodes: list[EpisodePlanSummary]
    cursor: dict[str, Any] | None
    source_exhausted: bool = False
    stale_episodes: list[int] = field(default_factory=list)
    total_planned: int = 0
    ledger_stats: LedgerStats | None = None


@dataclass
class _PlanningProgress:
    """本批规划时的全局进度快照，仅在 instructions 非空时注入 prompt（供模型换算切分节奏）。"""

    planned_count: int
    remaining_units: int
    window_units: int


_DRAFT_CONFIG = ConfigDict(extra="forbid")


class NarrationEpisodeDraft(BaseModel):
    """narration 条目：精确切分锚点 + 钩子。"""

    model_config = _DRAFT_CONFIG

    title: str = Field(min_length=1)
    hook: str = Field(min_length=1)
    end_anchor: str = Field(min_length=2)


class DramaEpisodeDraft(NarrationEpisodeDraft):
    """drama 条目加厚为分集大纲：故事节点 + 下集预告语。"""

    story_beats: list[str] = Field(min_length=1)
    next_episode_teaser: str | None = None


class NarrationPlanDraft(BaseModel):
    model_config = _DRAFT_CONFIG

    episodes: list[NarrationEpisodeDraft] = Field(min_length=1)


class DramaPlanDraft(BaseModel):
    model_config = _DRAFT_CONFIG

    episodes: list[DramaEpisodeDraft] = Field(min_length=1)


class _DraftRejected(Exception):
    """单轮 LLM 输出被 schema / 机械校验拒绝；reasons 注入下一轮重试 prompt。"""

    def __init__(self, reasons: list[str], *, valid_prefix_ends: list[int] | None = None):
        super().__init__("; ".join(reasons))
        self.reasons = reasons
        # 首个失败条目之前、已通过存在/唯一/递增校验的各集结束偏移；schema 层拒绝时为空
        self.valid_prefix_ends = valid_prefix_ends or []


# 全/半角标点折叠表：把同一标点的全角 / 表意形态映射到半角规范形，引号不分单双一律折成半角
# 双引号，仅供匹配时构造折叠副本用，绝不落库。逐字符 1:1 映射（长度不变），折叠坐标即 NFC 精确坐标。
_PUNCT_FOLD: dict[str, str] = {
    "。": ".",  # U+3002 表意句号
    "．": ".",  # U+FF0E 全角句点
    "，": ",",  # U+FF0C 全角逗号
    "！": "!",  # U+FF01 全角叹号
    "？": "?",  # U+FF1F 全角问号
    "：": ":",  # U+FF1A 全角冒号
    "；": ";",  # U+FF1B 全角分号
    "（": "(",  # U+FF08 全角左括号
    "）": ")",  # U+FF09 全角右括号
    "～": "~",  # U+FF5E 全角波浪号
    "〜": "~",  # U+301C CJK 波浪号（与 U+FF5E 同族，一并折向半角 ~）
    "“": '"',  # U+201C 左弯双引号
    "”": '"',  # U+201D 右弯双引号
    "‘": '"',  # U+2018 左弯单引号
    "’": '"',  # U+2019 右弯单引号
    "＂": '"',  # U+FF02 全角直双引号
    "＇": '"',  # U+FF07 全角直单引号
    "'": '"',  # 半角直单引号
}
# 折叠值必须是单字符：_fold_for_match 的逐字符 1:1 等长依赖于此。一旦某条映射折成多字符，
# 折叠串偏移就相对 NFC 原文漂移，end = start + len(anchor) 会算出错误切点。导入期即拦截违例。
assert all(len(dst) == 1 for dst in _PUNCT_FOLD.values()), "折叠表的值必须是单字符以保证等长映射"


def _fold_for_match(text: str) -> str:
    """构造匹配用折叠副本：折叠全/半角标点 + 把每个空白字符折成一个半角空格（逐字符等长，不合并连续空白）。

    严格逐字符 1:1 映射（每个字符映射为恰好一个字符，连续空白按原数量逐个保留、不压缩），
    长度与原文一致，因而折叠串上的偏移即原文 NFC 坐标系内的精确偏移。容差只限定在标点
    全/半角与单个空白字符的宽度，不做编辑距离 / 语义级模糊匹配。
    """
    out: list[str] = []
    for ch in text:
        folded = _PUNCT_FOLD.get(ch)
        if folded is not None:
            out.append(folded)
        elif ch.isspace():
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def _find_all_overlapping(haystack: str, needle: str) -> list[int]:
    """收集 needle 在 haystack 内的全部起点（允许重叠）。

    str.count 只统计非重叠匹配，会把重叠出现（如 "aaaa" 中的 "aaa"）误判为唯一；
    步进 1 滑动查找，按允许重叠的口径判定 0/1/多次。空 needle 直接返回空列表
    （调用方的 anchor 受 min_length=2 约束不会为空，此处仅作 helper 的防御边界）。
    """
    if not needle:
        return []
    starts: list[int] = []
    found = haystack.find(needle)
    while found != -1:
        starts.append(found)
        found = haystack.find(needle, found + 1)
    return starts


# 锚两端可剥离的字符（折叠后的形态）：模型回显时常在片段外补引号、颠倒收尾引号与句末标点
_EDGE_QUOTES = '"'
_EDGE_TAIL = '"' + ".,!?;:"
# 省略号：模型常用它在锚首 / 锚中 / 锚尾缩写原文
_ELLIPSIS_RE = re.compile(r"\.{3,}|…+|。{3,}")
_SENTENCE_TERMINATORS = frozenset("。！？!?….")
# 句末标点之后仍属于本句的收尾引号与括号；其中直引号可能是下一句的开引号，需看上下文
_CLOSING_MARKS = frozenset("\"'”’»）)」』】＂＇")
_STRAIGHT_QUOTES = frozenset("\"'＂＇")
# 只由这些字符构成的句末标点串要看上下文才能判定收句（半角句点、省略号）
_PAUSE_CHARS = frozenset(".…")
# 句点之后不收句的常见缩写（小写比较）：英文称谓 / 拉丁缩写与越南语机构、头衔缩写
_ABBREVIATIONS = frozenset(
    {"dr", "mr", "mrs", "ms", "st", "jr", "sr", "prof", "vs", "etc", "no", "tp", "ts", "ths", "gs", "pgs", "bs", "ks"}
)
# 结束点不在句末时向后贴齐句末 / 段落换行的最大距离（字符）；超出则保留原结束点
_SENTENCE_SNAP_LIMIT = 400
# 字母数字骨架层的最短骨架长度；更短的锚只走逐字 / 折叠 / 剥边层
_MIN_SKELETON_LEN = 6
# 近似层：最短骨架长度、接受阈值、与次优候选的最小差距、拒绝时给出最接近原文的阈值
_FUZZY_MIN_LEN = 12
_FUZZY_ACCEPT = 0.85
_FUZZY_MARGIN = 0.08
_FUZZY_HINT = 0.5
_HINT_MAX_CHARS = 80


def _edge_trimmed(folded_anchor: str) -> tuple[int, str, str] | None:
    """剥掉折叠锚首部的引号与尾部的引号 / 句末标点，返回（首部剥离长度, 正文, 尾部剥离串）。

    正文不足 2 个字符或两端无可剥离字符时返回 None。
    """
    body = folded_anchor.lstrip(_EDGE_QUOTES + " ")
    lead = len(folded_anchor) - len(body)
    core = body.rstrip(_EDGE_TAIL + " ")
    if len(core) < 2 or len(core) == len(folded_anchor):
        return None
    return lead, core, body[len(core) :]


def _absorb_closing_marks(text: str, j: int) -> int:
    """从 j 起越过收尾引号 / 括号；紧贴字母数字的直引号是下一句的开引号，不吸收。"""
    while j < len(text) and text[j] in _CLOSING_MARKS:
        if text[j] in _STRAIGHT_QUOTES and j + 1 < len(text) and text[j + 1].isalnum():
            break
        j += 1
    return j


def _sentence_close_at(text: str, i: int) -> int | None:
    """text[i] 所在的句末标点串确实收句时，返回句子结束偏移（越过标点串与收尾引号 / 括号），否则 None。

    半角句点与省略号要看上下文：句点之后紧跟非空白（3.5、TP.HCM）、句点前是常见缩写或单个大写首字母
    （Dr.、TP.、A.）、或之后的下一个字是小写字母时都不收句；只由省略号构成的标点串紧贴下文
    （我们……不知道）或下一个字是小写字母时视为句中停顿。
    """
    if text[i] not in _SENTENCE_TERMINATORS:
        return None
    start = i
    while start > 0 and text[start - 1] in _SENTENCE_TERMINATORS:
        start -= 1
    j = i + 1
    while j < len(text) and text[j] in _SENTENCE_TERMINATORS:
        j += 1
    run = text[start:j]
    close = _absorb_closing_marks(text, j)
    if close >= len(text):
        return close
    if set(run) <= _PAUSE_CHARS or run.startswith("。。。"):
        nxt = text[close]
        if close == j and not nxt.isspace() and nxt not in _CLOSING_MARKS:
            return None
        if run == ".":
            token_start = start
            while token_start > 0 and text[token_start - 1].isalpha():
                token_start -= 1
            token = text[token_start:start]
            if token.lower() in _ABBREVIATIONS or (len(token) == 1 and token.isupper()):
                return None
        following = text[close:].lstrip()
        if following and following[0].islower():
            return None
    return close


def _ends_at_sentence_close(text: str) -> bool:
    """text（去掉尾部空白）是否以收句的句末标点（可带收尾引号 / 括号）结尾。"""
    stripped = text.rstrip()
    k = len(stripped)
    while k > 0 and stripped[k - 1] in _CLOSING_MARKS:
        k -= 1
    return k > 0 and _sentence_close_at(stripped, k - 1) is not None


def _sentence_pieces(text: str) -> list[str]:
    """按收句的句末标点（含收尾引号 / 括号）把 text 切成句子，末尾不成句的残段单独成一段。"""
    pieces: list[str] = []
    start = 0
    i = 0
    while i < len(text):
        close = _sentence_close_at(text, i)
        if close is not None and (i + 1 >= len(text) or text[i + 1] not in _SENTENCE_TERMINATORS):
            pieces.append(text[start:close])
            start = i = close
            continue
        i += 1
    if text[start:].strip():
        pieces.append(text[start:])
    return [piece for piece in pieces if piece.strip()]


def _snap_to_sentence_end(text: str, end: int) -> int | None:
    """返回 end 处或其后最近的句子结束偏移（含收尾引号 / 括号）或段落换行位置。

    end 已在句末时只补齐紧随其后的收尾引号 / 括号；_SENTENCE_SNAP_LIMIT 内找不到时返回 None。
    """
    if end >= len(text) or text[end] == "\n" or (end > 0 and text[end - 1] == "\n"):
        return end
    k = end
    while k > 0 and text[k - 1] in _CLOSING_MARKS:
        k -= 1
    if k > 0 and (close := _sentence_close_at(text, k - 1)) is not None:
        return max(end, close)
    for i in range(end, min(len(text), end + _SENTENCE_SNAP_LIMIT)):
        if text[i] == "\n":
            return i
        if (close := _sentence_close_at(text, i)) is not None:
            return close
    return None


def _skeleton(text: str) -> tuple[str, list[int]]:
    """只保留字母与数字（小写）的骨架串，以及骨架每个字符在 text 中的偏移。"""
    chars: list[str] = []
    origin: list[int] = []
    for i, ch in enumerate(text):
        if ch.isalnum():
            low = ch.lower()
            chars.append(low if len(low) == 1 else ch)
            origin.append(i)
    return "".join(chars), origin


@dataclass
class _AnchorHit:
    """单条锚点的定位结果。``count`` 为命中处数，唯一命中时 ``end`` 为窗口内结束偏移。"""

    count: int = 0
    end: int = 0
    tolerant: bool = False  # 经容错层命中（拒绝话术须点明计数口径）
    sentence_end_required: bool = False  # 锚以省略号收尾：结束点必须贴齐到句末
    hint: str | None = None  # 落空时原文中最接近的片段


class _AnchorLocator:
    """在一个窗口内定位 end_anchor，逐层放宽，首个命中（≥1 处）的层决定结果。

    1. 逐字精确；2. 归一 + 标点全/半角、引号种类、空白宽度折叠；3. 剥去锚两端补加的引号 / 句末标点；
    4. 只比对字母数字骨架（忽略全部标点与空白、不分大小写）；5. 锚含省略号时取省略号之后（锚尾省略时取之前）
    的片段重走 1–4；6. 按句子近似匹配（相似度 ≥ _FUZZY_ACCEPT 且领先次优候选 _FUZZY_MARGIN），结束于该句句末。
    折叠与骨架都保留到原文的偏移映射，切片始终取原文，不改写源文。
    """

    def __init__(self, window: str):
        self.window = window
        self._folded: str | None = None
        self._skeleton: tuple[str, list[int]] | None = None
        self._sentence_ends: list[int] | None = None

    @property
    def folded(self) -> str:
        if self._folded is None:
            self._folded = _fold_for_match(self.window)
        return self._folded

    @property
    def skeleton(self) -> tuple[str, list[int]]:
        if self._skeleton is None:
            self._skeleton = _skeleton(self.window)
        return self._skeleton

    @property
    def sentence_ends(self) -> list[int]:
        if self._sentence_ends is None:
            text = self.window
            found: set[int] = set()
            for i, ch in enumerate(text):
                if ch == "\n":
                    if i > 0 and text[i - 1] != "\n":
                        found.add(i)
                elif (
                    not (i + 1 < len(text) and text[i + 1] in _SENTENCE_TERMINATORS)
                    and (close := _sentence_close_at(text, i)) is not None
                ):
                    found.add(close)
            found.add(len(text))
            self._sentence_ends = sorted(found)
        return self._sentence_ends

    def locate(self, anchor: str) -> _AnchorHit:
        hit = self._locate_text(anchor)
        if hit.count:
            return hit
        normalized = normalize_source_text(anchor)
        fuzzy_target = normalized
        segments = _ELLIPSIS_RE.split(normalized)
        if len(segments) > 1:
            if len(_skeleton(segments[-1])[0]) >= _MIN_SKELETON_LEN:
                fuzzy_target = segments[-1]
                hit = self._locate_text(segments[-1])
                if hit.count:
                    hit.tolerant = True
                    return hit
            else:
                body = next((seg for seg in reversed(segments) if len(_skeleton(seg)[0]) >= _MIN_SKELETON_LEN), None)
                if body is not None:
                    fuzzy_target = body
                    hit = self._locate_text(body)
                    if hit.count:
                        hit.tolerant = True
                        hit.sentence_end_required = True
                        return hit
        return self._locate_fuzzy(fuzzy_target)

    def _locate_text(self, anchor: str) -> _AnchorHit:
        window = self.window
        starts = _find_all_overlapping(window, anchor)
        if starts:
            return _AnchorHit(count=len(starts), end=starts[0] + len(anchor))
        # normalize_source_text 非长度保持，后续各层的跨度一律取归一后的锚长
        normalized = normalize_source_text(anchor)
        folded_anchor = _fold_for_match(normalized)
        starts = _find_all_overlapping(self.folded, folded_anchor)
        if starts:
            return _AnchorHit(count=len(starts), end=starts[0] + len(normalized), tolerant=True)
        trimmed = _edge_trimmed(folded_anchor)
        if trimmed is not None:
            # 结束点越过源文紧随正文、且属于被剥尾部字符集的收尾标点与引号，吸收「补了源文没有的
            # 收尾引号」与「引号与句号顺序颠倒」两类回显
            _, core, tail = trimmed
            starts = _find_all_overlapping(self.folded, core)
            if starts:
                end = starts[0] + len(core)
                tail_chars = set(tail) - {" "}
                while end < len(window) and self.folded[end] in tail_chars:
                    if window[end] in _STRAIGHT_QUOTES and end + 1 < len(window) and window[end + 1].isalnum():
                        break
                    end += 1
                return _AnchorHit(count=len(starts), end=end, tolerant=True)
        anchor_skeleton, _ = _skeleton(normalized)
        if len(anchor_skeleton) >= _MIN_SKELETON_LEN:
            skeleton, origin = self.skeleton
            starts = _find_all_overlapping(skeleton, anchor_skeleton)
            if starts:
                end = origin[starts[0] + len(anchor_skeleton) - 1] + 1
                while end < len(window) and window[end] in _SENTENCE_TERMINATORS:
                    end += 1
                end = _absorb_closing_marks(window, end)
                return _AnchorHit(count=len(starts), end=end, tolerant=True)
        return _AnchorHit()

    def _locate_fuzzy(self, anchor: str) -> _AnchorHit:
        """按句子对齐近似匹配整条锚：对比原文以每个句末收尾的同数（及多一）句，结束点即该句末。

        整条锚优先；整条锚落空时，末句单独近似命中且锚首各句没有在末句之后强命中（顺序不矛盾）才接受末句，
        覆盖模型把原文中不相邻的两句拼进同一条锚的回显；锚首强命中在末句之后时拒绝，避免末句误配到更早的段落。
        """
        pieces = _sentence_pieces(anchor)
        anchor_skeleton = _skeleton(anchor)[0]
        if not pieces or len(anchor_skeleton) < _FUZZY_MIN_LEN:
            return _AnchorHit()
        scored = self._fuzzy_scores(anchor_skeleton, len(pieces), mid_sentence=not _ends_at_sentence_close(anchor))
        best, best_end, best_start = scored[0] if scored else (0.0, 0, 0)
        if best >= _FUZZY_ACCEPT:
            # 只有与最佳候选不重叠的原文区段才算另一处出现；重叠的是同一处的不同对齐方式
            rivals = [
                end
                for score, end, start in scored[1:]
                if score > best - _FUZZY_MARGIN and (end <= best_start or start >= best_end)
            ]
            return _AnchorHit(count=1 + len(rivals), end=best_end, tolerant=True)
        tail_skeleton = _skeleton(pieces[-1])[0]
        if len(pieces) > 1 and len(tail_skeleton) >= _FUZZY_MIN_LEN:
            tail_scored = self._fuzzy_scores(tail_skeleton, 1, mid_sentence=False)
            if tail_scored:
                tail_best, tail_end, tail_start = tail_scored[0]
                if tail_best >= _FUZZY_ACCEPT and not self._head_contradicts(pieces[:-1], tail_start):
                    rivals = [
                        end
                        for score, end, start in tail_scored[1:]
                        if score > tail_best - _FUZZY_MARGIN and (end <= tail_start or start >= tail_end)
                    ]
                    return _AnchorHit(count=1 + len(rivals), end=tail_end, tolerant=True)
                if tail_best > best:
                    best, best_end = tail_best, tail_end
        if best >= _FUZZY_HINT:
            return _AnchorHit(hint=self._sentence_ending_at(best_end))
        return _AnchorHit()

    def _head_contradicts(self, head_pieces: list[str], tail_start: int) -> bool:
        """锚首各句在原文中强命中（≥ _FUZZY_ACCEPT）且位置在末句命中区段起点之后。"""
        head_skeleton = _skeleton("".join(head_pieces))[0]
        if len(head_skeleton) < _FUZZY_MIN_LEN:
            return False
        head_scored = self._fuzzy_scores(head_skeleton, len(head_pieces), mid_sentence=False)
        return bool(head_scored) and head_scored[0][0] >= _FUZZY_ACCEPT and head_scored[0][1] > tail_start

    def _fuzzy_scores(
        self, anchor_skeleton: str, sentence_count: int, *, mid_sentence: bool
    ) -> list[tuple[float, int, int]]:
        """各候选句末的（最高相似度, 句末偏移, 取得该相似度的区段起点），按相似度降序。

        同一段骨架（句末之间只隔标点 / 空白）只计一个候选、取最靠前的句末；锚停在句中时同句数候选另取
        「段首等长前缀相似度」，覆盖锚停在句中、又改了字的回显。
        """
        skeleton, origin = self.skeleton
        ends = self.sentence_ends
        matcher = SequenceMatcher(None, autojunk=False)
        matcher.set_seq2(anchor_skeleton)
        best_by_span: dict[int, tuple[float, int, int]] = {}
        for i, end in enumerate(ends):
            k1 = bisect_left(origin, end)
            if k1 in best_by_span:
                continue
            score = 0.0
            best_start = end
            for count in (sentence_count, sentence_count + 1):
                start = ends[i - count] if i - count >= 0 else 0
                candidate = skeleton[bisect_left(origin, start) : k1]
                if not candidate:
                    continue
                texts = [candidate]
                if mid_sentence and count == sentence_count:
                    texts.append(candidate[: len(anchor_skeleton)])
                for text in texts:
                    matcher.set_seq1(text)
                    if matcher.real_quick_ratio() >= _FUZZY_HINT and matcher.quick_ratio() >= _FUZZY_HINT:
                        ratio = matcher.ratio()
                        if ratio > score:
                            score, best_start = ratio, start
            best_by_span[k1] = (score, end, best_start)
        return sorted((pair for pair in best_by_span.values() if pair[0] > 0), key=lambda pair: (-pair[0], pair[1]))

    def _sentence_ending_at(self, end: int) -> str:
        ends = self.sentence_ends
        idx = bisect_left(ends, end)
        start = ends[idx - 1] if idx > 0 else 0
        sentence = self.window[start:end].strip()
        return sentence if len(sentence) <= _HINT_MAX_CHARS else "…" + sentence[-_HINT_MAX_CHARS:]


def _resolve_boundaries(
    window: str,
    drafts: list[NarrationEpisodeDraft],
    *,
    snap_whitespace_tail: bool,
) -> list[int]:
    """把每集 end_anchor 解析为窗口内相对结束偏移，校验存在/唯一/连续。

    范围由锚点构造性保证连续不重叠：第 i 集 = [第 i-1 集末尾, 第 i 集锚点末尾)。锚点定位分层见
    :class:`_AnchorLocator`；任一层命中多处都按「无法唯一定位」拒绝，不静默挑第一处。

    校验通过后每集结束点向后贴齐到句末（含收尾引号 / 括号）或段落换行；相邻两条锚落在同一句内时拒绝后一条。
    末尾只剩空白时（``snap_whitespace_tail=True``，即 plan 命中全文结尾窗口）把最后一集贴齐到窗口末尾，
    贴齐后每个字符都归属某一集。拒绝时附带首个失败条目之前的有效结束偏移（同样贴齐句末），
    供重试耗尽后提交最长有效前缀。
    """
    locator = _AnchorLocator(window)
    reasons: list[str] = []
    ends: list[int] = []
    prefix_len = 0  # 首个失败条目之前的有效集数
    pos = 0
    ordering_valid = True
    for idx, ep in enumerate(drafts, start=1):
        if ordering_valid:
            prefix_len = len(ends)
        anchor = ep.end_anchor
        hit = locator.locate(anchor)
        if hit.count == 0:
            reason = f"第 {idx} 条的 end_anchor 在原文窗口中不存在（必须逐字摘抄，含标点）: {anchor!r}"
            if _ELLIPSIS_RE.search(anchor):
                reason += "；不要用省略号（... 或 …）缩写原文"
            if hit.hint:
                reason += f"；原文中最接近的片段是 {hit.hint!r}，请从原文逐字摘抄"
            reasons.append(reason)
            ordering_valid = False
            continue
        if hit.count > 1:
            if hit.tolerant:
                # 容错层的「出现 N 次」是对齐后的计数；模型按字面 anchor 逐字数往往是 0 次，必须点明
                # 计数口径，否则模型对不上、可能反复重交同一 anchor 耗尽重试
                reasons.append(
                    f"第 {idx} 条的 end_anchor 在原文窗口中按容错对齐（归一、标点 / 引号 / 空白折叠、去两端引号、"
                    f"只比对字母数字或近似句子）后出现 {hit.count} 次（逐字精确匹配可能为 0 次），无法唯一定位，"
                    f"请改用更长或更独特、与原文逐字一致的片段: {anchor!r}"
                )
            else:
                reasons.append(
                    f"第 {idx} 条的 end_anchor 在原文窗口中出现 {hit.count} 次，无法唯一定位，"
                    f"请改用更长或更独特的片段: {anchor!r}"
                )
            ordering_valid = False
            continue
        end = hit.end
        if hit.sentence_end_required:
            snapped = _snap_to_sentence_end(window, end)
            if snapped is None:
                reasons.append(
                    f"第 {idx} 条的 end_anchor 以省略号缩写，找不到它所在句子的句末：请逐字摘抄完整片段，"
                    f"不要用省略号（... 或 …）代替原文: {anchor!r}"
                )
                ordering_valid = False
                continue
            end = snapped
        if ordering_valid and end <= pos:
            reasons.append(
                f"第 {idx} 条的 end_anchor 位置不在上一集结尾之后（各集范围必须连续推进、不重叠）: {anchor!r}"
            )
            ordering_valid = False
            continue
        ends.append(end)
        pos = end
    if reasons:
        prefix, _ = _finalize_ends(window, ends[:prefix_len], snap_whitespace_tail=snap_whitespace_tail)
        raise _DraftRejected(reasons, valid_prefix_ends=prefix)
    final, conflict = _finalize_ends(window, ends, snap_whitespace_tail=snap_whitespace_tail)
    if conflict is not None:
        raise _DraftRejected(
            [
                f"第 {conflict + 2} 条的 end_anchor 与第 {conflict + 1} 条落在原文同一句内（各集须止于不同的句末，"
                f"不能把一句话切成两集）: {drafts[conflict + 1].end_anchor!r}"
            ],
            valid_prefix_ends=final,
        )
    return final


def _finalize_ends(window: str, ends: list[int], *, snap_whitespace_tail: bool) -> tuple[list[int], int | None]:
    """把每集结束点向后贴齐到句末，返回（贴齐后的结束点, 冲突集下标）。

    第 i 集贴齐后会追上第 i+1 集的结束点，说明两条锚落在同一句内：返回第 i 集之前已贴齐的结束点与 i。
    无冲突且命中全文结尾窗口、最后一集之后只剩空白时，把最后一集贴齐到窗口末尾。
    """
    snapped: list[int] = []
    for i, end in enumerate(ends):
        target = _snap_to_sentence_end(window, end)
        if target is None:
            target = end
        if i + 1 < len(ends) and target >= ends[i + 1]:
            return snapped, i
        snapped.append(target)
    if snap_whitespace_tail and snapped and snapped[-1] < len(window) and not window[snapped[-1] :].strip():
        snapped[-1] = len(window)
    return snapped, None


def _ledger_entry_from_draft(
    draft_ep: NarrationEpisodeDraft,
    *,
    num: int,
    source_rel: str,
    start: int,
    end: int,
    status: str,
) -> dict[str, Any]:
    """把单集草稿物化为账本条目。"""
    entry: dict[str, Any] = {
        "episode": num,
        "title": draft_ep.title,
        "script_file": episode_script_relpath(num),
        "source_range": {"source_file": source_rel, "start": start, "end": end},
        "hook": draft_ep.hook,
        "ledger_status": status,
    }
    if isinstance(draft_ep, DramaEpisodeDraft):
        entry["outline"] = {
            "story_beats": list(draft_ep.story_beats),
            "next_episode_teaser": draft_ep.next_episode_teaser,
        }
    return entry


def _language_of(project: Mapping[str, Any]) -> str | None:
    language = project.get("source_language")
    return language if isinstance(language, str) else None


def _source_changed_error(paths: list[str]) -> EpisodePlanningError:
    """构造源文已变动的拒绝错误：指名变动文件并指路全量重置。"""
    return EpisodePlanningError(
        f"源文件已被修改或移除：{'、'.join(paths)}。账本坐标绑定的是修改前的原文内容，继续规划会静默切出"
        "错误内容；请先调用 reset_episode_planning 做全量重置，再重新规划。"
    )


def _missing_source_range_error(nums: list[int]) -> EpisodePlanningError:
    """构造账本缺位置记录的拒绝错误：指名集号并指路全量重置。"""
    listed = "、".join(str(num) for num in nums[:_MISSING_RANGE_LISTED_LIMIT])
    if len(nums) > _MISSING_RANGE_LISTED_LIMIT:
        listed += f" 等 {len(nums)} 集"
    return EpisodePlanningError(
        f"账本中第 {listed} 没有原文范围记录（source_range），无法据此续接规划——这类条目的物理集文件"
        "就是它们的最终记录，既无法重造也无法确定下一批的起点。若这些集是用户自行拆好上传的，"
        "不需要规划：按 get_workflow_plan 逐集直接做脚本规划即可。确需重新切分时才调用 "
        "reset_episode_planning 做全量重置（这些集的集文件会改名留底、下游产物不删），再重新规划。"
    )


# plan_episodes 开篇定位：novel 走「切分 / 创作」，screenplay 翻为「尊重作者分集 / 提取」。
# screenplay 二分支——剧本自带分集（任意形态）照用作者边界，无分集才按剧情弧语义切，
# 绝不按字数机械切；不依赖任何固定分集标记，靠模型语义识别作者写下的分集形态。
_PLAN_INTRO_NOVEL: tuple[str, ...] = (
    "你是短视频分集规划师。请把下面的小说原文片段切分为若干集，每一集都必须是一个完整的剧情弧，",
    "并在集尾留下让观众想看下一集的钩子。",
)
_PLAN_INTRO_SCREENPLAY: tuple[str, ...] = (
    "你是短视频分集规划师。下面是作者已写好的成品剧本片段，请尊重作者自带的分集、提取而非重切：",
    "- 若剧本自带分集（任意形态——分集标记、结构表、标题体系、分隔等，不要依赖任何固定标记或正则识别），",
    "  照用作者划定的每一集边界，title、hook 与分集大纲都取自剧本原文。",
    "- 若剧本没有任何分集线索，再按完整剧情弧语义切分，每一集都是一个完整的故事段落，绝不按字数机械切碎。",
)
# screenplay 在「切分规则」段补一条把上述意图落到 end_anchor 层的具体指令。
_PLAN_RULE_SCREENPLAY: str = (
    "- 优先照用作者的分集：剧本已划定每集边界时，end_anchor 取作者每集结尾处的原文片段，"
    "title / hook 也取自剧本（作者写明的集标题、集尾钩子）；剧本未分集时才按剧情弧自行切，绝不按字数硬凑集数。"
)
# drama 大纲条目说明：screenplay 优先照搬作者写下的故事节点 / 下集预告。
_PLAN_DRAMA_OUTLINE_NOVEL: str = (
    "- 每一集另给出 story_beats（本集故事节点列表，按顺序）"
    "与 next_episode_teaser（下集预告语；最后一集若后续未知可为 null）。"
)
_PLAN_DRAMA_OUTLINE_SCREENPLAY: str = (
    "- 每一集另给出 story_beats（本集故事节点列表，按顺序）"
    "与 next_episode_teaser（下集预告语；最后一集若后续未知可为 null）；"
    "剧本已写明本集节点 / 下集预告时照搬其原文，未写明再自行提炼。"
)


class EpisodePlanner:
    """分集规划器。``generator`` 为 None 时仅可构造，调用 plan() 会报错。"""

    def __init__(
        self,
        project_path: str | Path,
        generator: TextGenerator | None = None,
        *,
        max_attempts: int = _MAX_PLAN_ATTEMPTS,
    ):
        self.project_path = Path(project_path)
        self.project_name = self.project_path.name
        self.generator = generator
        self.max_attempts = max_attempts
        self.pm = ProjectManager(str(self.project_path.parent))

    @classmethod
    async def create(cls, project_path: str | Path) -> EpisodePlanner:
        """异步工厂：按项目配置创建文本后端（与剧本生成同一条 SCRIPT 任务配置链）。"""
        project_name = Path(project_path).name
        generator = await TextGenerator.create(TextTaskType.SCRIPT, project_name)
        return cls(project_path, generator)

    # ---------------------------------------------------------------- plan

    async def plan(
        self,
        instructions: str | None = None,
        *,
        cancellation_receipts: list[FormalWriteReceipt] | None = None,
    ) -> PlanResult:
        """规划下一批集：从 planning_cursor 起的窗口产出剧情弧完整的集并提交账本。

        当前源文件已无剩余有效内容时按文件名序自动推进到下一个源文件；
        ``source_exhausted=True`` 表示全部源文件都已规划完毕。

        ``instructions`` 是可选的用户分集附加指令（如按章节对齐切分），strip 后为空视同未传；
        非空则原样注入规划 prompt 的中性「附加指令」分节，遵循强度由附加指令正文自行表达。规划按窗口
        分多批、附加指令不持久化，调用方须在每批 plan 调用都重复带上。

        新提交的集号若在磁盘上已有下游产物（剧本/script_plan/媒体，见
        :func:`lib.episode_ledger.has_downstream_products`），说明该集实际已被消费过
        （典型场景：先 ``reset_episode_planning`` 部分重置到更早集号、再带新 ``instructions``
        重新规划，新布局与原消费范围重叠）；这类集提交时直接标 ``stale``（产物不删除），
        随 ``PlanResult.stale_episodes`` 返回，不再需要额外确认——重置阶段已完成过一次
        已消费集确认。
        """
        planning_instructions = (instructions or "").strip() or None
        project = self.pm.load_project(self.project_name)
        # 手动预拆分上传等场景下磁盘可能已有账本无条目的孤儿派生集文件：不先补建条目，
        # 门禁看见空账本会直接放行，规划随后会把该集内容当无主原文重新生成并覆盖
        project = register_orphan_episode_entries(self.project_path, project)
        self._check_source_ranges(project)
        pre_call_sources = discover_sources(self.project_path)
        self._check_source_fingerprints(project, sources=pre_call_sources)
        # 提交时复核的基线只留指纹摘要，不为暂不参与本批规划的源文件常驻其全文：
        # discover_sources 已读入全部候选源文的原文用于计算这批指纹，本函数下方
        # 显式 del 释放该列表，避免大型多源项目在跨模型调用的等待期间叠加持有整套原文
        used_fingerprints = compute_source_fingerprints(pre_call_sources)

        def _pre_call_text(rel: str) -> str | None:
            return next((doc.text for doc in pre_call_sources if doc.rel_path == rel), None)

        start_ref = self._effective_start(project)
        source_rel, start = start_ref
        text = _pre_call_text(source_rel)
        if text is None:
            text = self._load_normalized_source(source_rel)
            used_fingerprints[source_rel] = compute_source_fingerprints([SourceDoc(rel_path=source_rel, text=text)])[
                source_rel
            ]
        if start > len(text):
            raise EpisodePlanningError(f"规划起点越界：{source_rel} 长度 {len(text)}，起点 {start}；请检查账本")
        while not text[start:].strip():
            next_rel = self._next_source_rel(source_rel)
            if next_rel is None:
                project = await self._backfill_source_fingerprints_if_missing(
                    project,
                    used_fingerprints=used_fingerprints,
                    cancellation_receipts=cancellation_receipts,
                )
                return PlanResult(
                    episodes=[],
                    cursor=project.get("planning_cursor"),
                    source_exhausted=True,
                    total_planned=_count_planned_episodes(project),
                    ledger_stats=self._compute_ledger_stats(project),
                )
            source_rel, start = next_rel, 0
            text = _pre_call_text(source_rel)
            if text is None:
                text = self._load_normalized_source(source_rel)
                used_fingerprints[source_rel] = compute_source_fingerprints(
                    [SourceDoc(rel_path=source_rel, text=text)]
                )[source_rel]
        pre_call_sources = []  # 之后只需 used_fingerprints（摘要）与本批实际使用的 text，显式释放原文引用

        window_chars = self._setting_int(project, "planning_window_chars", DEFAULT_PLANNING_WINDOW_CHARS)
        max_episodes = self._setting_int(project, "planning_max_episodes", DEFAULT_PLANNING_MAX_EPISODES)
        remaining_chars = len(text) - start
        # 窗口弹性：剩余全文不足 1.2 倍窗口时直接吃到底，避免下一批只剩孤儿残余
        # 被迫单独成集（畸小集的机械成因）。系数 1.2 换来的浮动幅度足够小，
        # 不会让常规批次显著超出窗口设置的预期体量。
        window_end = len(text) if remaining_chars <= window_chars * 1.2 else start + window_chars
        window = text[start:window_end]
        window_is_final = window_end >= len(text)
        content_mode = str(project.get("content_mode") or "narration")
        draft_model: type[NarrationPlanDraft | DramaPlanDraft] = (
            DramaPlanDraft if content_mode == "drama" else NarrationPlanDraft
        )
        language = _language_of(project)
        # 全局进度仅在有 instructions 时算、仅在有 instructions 时注入 prompt：
        # 无指令路径的 prompt 必须逐字保持不变：分批规划要求同一批次内的无附加指令路径行为可复现，
        # 注入全局进度会改写 prompt，因此只在有 instructions 时才计算并注入。
        progress: _PlanningProgress | None = None
        if planning_instructions:
            progress = _PlanningProgress(
                planned_count=_count_planned_episodes(project),
                remaining_units=self._remaining_units_from(source_rel, start, text, language),
                window_units=count_reading_units(window, language),
            )

        def _prompt(failure: list[str] | None) -> str:
            return _build_planning_prompt(
                project=project,
                window=window,
                window_is_final=window_is_final,
                max_episodes=max_episodes,
                content_mode=content_mode,
                context_entries=_context_entries(project),
                instructions=planning_instructions,
                progress=progress,
                failure=failure,
            )

        drafts, ends = await self._request_validated_drafts(
            draft_model,
            _prompt,
            window,
            snap_whitespace_tail=window_is_final,
            max_episodes=max_episodes,
        )

        summaries: list[EpisodePlanSummary] = []
        committed: dict[str, Any] = {"stale": []}

        def _commit(p: dict) -> None:
            # 锁内复核缺位置记录的条目：与指纹复核同一套逃生口——模型调用期间账本可能被
            # 并发写入（如另一条链路补建了手动预拆分集的条目），锁外那次快照不足以放行提交；
            # 先重跑一次孤儿登记补齐同一并发窗口内新出现的孤儿派生文件，再校验
            healed = register_orphan_episode_entries(self.project_path, p)
            p.clear()
            p.update(healed)
            self._check_source_ranges(p)
            if self._effective_start(p) != start_ref:
                raise PlanningConflictError("规划期间账本进度被并发修改，本次结果作废；请重新调用规划")
            # 锁内复核：模型调用期间源文件可能被外部改动，与锁外预检查同一套逃生口，
            # 复用同一错误提示——重试只会再次命中同一比对，须先重置
            current_sources = discover_sources(self.project_path)
            self._check_source_fingerprints(p, sources=current_sources)
            # 指纹比对只覆盖「已记录」的文件，存量项目补记路径上恒为空；而切分坐标与派生
            # 文件都基于本次调用读入的 used_fingerprints（覆盖入口快照 + 循环中途新发现的
            # 源文件），故直接比指纹堵住补记路径裸露的窗口——本次调用之前已锚定其它集号
            # 的源文、以及 _next_source_rel() 在快照之后才发现并读入的新源文件，若在模型
            # 调用期间被改动，同样会被这里拦下
            current_fingerprints = compute_source_fingerprints(current_sources)
            changed = sorted(rel for rel, fp in used_fingerprints.items() if current_fingerprints.get(rel) != fp)
            if changed:
                raise _source_changed_error(changed)
            episodes_list = [e for e in (p.get("episodes") or []) if e is not None]
            nums = [parse_episode_num(e.get("episode")) for e in episodes_list if isinstance(e, dict)]
            # 集号只在正整数域上推进：负数/0 集号属脏数据，不让它把新集编号拖成非正数
            next_num = max((n for n in nums if n is not None and n > 0), default=0) + 1
            prev = start
            for offset_idx, (draft_ep, rel_end) in enumerate(zip(drafts, ends, strict=True)):
                num = next_num + offset_idx
                abs_end = start + rel_end
                entry = _ledger_entry_from_draft(
                    draft_ep, num=num, source_rel=source_rel, start=prev, end=abs_end, status="planned"
                )
                # 新集号若在磁盘上已有剧本/script_plan/媒体产物（如重置到更早集号后重新规划、
                # 新布局与原消费范围重叠），说明该集实际已被消费过；标 stale 提示主 Agent
                # 需重做下游产物，产物本身不删除
                if has_downstream_products(self.project_path, num, entry):
                    entry["ledger_status"] = "stale"
                    script_plan_path = script_review.script_plan_path(self.project_path, p, num)
                    entry[script_review.STALE_SCRIPT_PLAN_REVISION_FIELD] = (
                        script_review.content_fingerprint(script_plan_path) if script_plan_path is not None else None
                    )
                    committed["stale"].append(num)
                episodes_list.append(entry)
                summaries.append(
                    EpisodePlanSummary(
                        episode=num,
                        title=draft_ep.title,
                        hook=draft_ep.hook,
                        reading_units=count_reading_units(text[prev:abs_end], language),
                        ledger_status=entry["ledger_status"],
                    )
                )
                prev = abs_end
            _sort_episodes_if_possible(episodes_list)
            p["episodes"] = episodes_list
            p["planning_cursor"] = {"source_file": source_rel, "offset": start + ends[-1]}
            p[SOURCE_FINGERPRINTS_KEY] = current_fingerprints
            self._reconcile_derived_files(p, {source_rel: text})
            committed["cursor"] = p["planning_cursor"]
            committed["exhausted"] = (
                window_is_final and not text[start + ends[-1] :].strip() and self._next_source_rel(source_rel) is None
            )

        existing_derived = set(discover_episode_files(self.project_path).values())
        ledger_nums = {
            parse_episode_num(entry.get("episode"))
            for entry in project.get("episodes") or []
            if isinstance(entry, Mapping)
        }
        ledger_nums = {num for num in ledger_nums if num is not None and num > 0}
        next_num = max(ledger_nums, default=0) + 1
        formal_paths = existing_derived | {
            episode_source_path(self.project_path, num)
            for num in (*sorted(ledger_nums), *range(next_num, next_num + len(drafts)))
        }
        formal_paths.add(self.project_path / "source" / "_remaining.txt")
        final_project = await self._update_project_compensably(
            _commit,
            formal_paths=tuple(sorted(formal_paths)),
            cancellation_receipts=cancellation_receipts,
        )
        exhausted = bool(committed["exhausted"])
        return PlanResult(
            episodes=summaries,
            cursor=committed["cursor"],
            source_exhausted=exhausted,
            stale_episodes=list(committed["stale"]),
            total_planned=_count_planned_episodes(final_project),
            # 全局核对材料只在末批即耗尽时附上；常规批次只报「累计已规划 N 集」，
            # 避免主 Agent 上下文被逐批膨胀（工具层渲染 total_planned 的那一行）
            ledger_stats=self._compute_ledger_stats(final_project) if exhausted else None,
        )

    # ------------------------------------------------------------- helpers

    async def _request_validated_drafts(
        self,
        draft_model: type[NarrationPlanDraft | DramaPlanDraft],
        prompt_builder: Callable[[list[str] | None], str],
        window: str,
        *,
        snap_whitespace_tail: bool,
        max_episodes: int | None,
    ) -> tuple[list[NarrationEpisodeDraft], list[int]]:
        """LLM 调用 + schema/机械校验循环；重试 prompt 附上一轮失败原因。

        结构化输出被输出上限截断时 :class:`TextOutputTruncatedError` 直接短路本循环——
        重发同一份必然再截断的请求没有意义；追加本规划器特有的杠杆提示（调小窗口字数 /
        每批集数）后转为 :class:`EpisodePlanningError` 冒泡（见 docs/adr/0044）。

        后端结构化输出降级链耗尽的 :class:`StructuredOutputExhaustedError` 同样短路本循环，
        转为 :class:`EpisodePlanningError`，让 Agent 拿到「供应商结构化输出能力不足」的可读
        话术而非后端内部异常原文。
        """
        if self.generator is None:
            raise RuntimeError("TextGenerator 未初始化，请使用 EpisodePlanner.create() 工厂方法")
        failure: list[str] | None = None
        best_prefix: tuple[list[NarrationEpisodeDraft], list[int]] | None = None
        for attempt in range(1, self.max_attempts + 1):
            drafts: list[NarrationEpisodeDraft] = []
            try:
                result = await self.generator.generate(
                    TextGenerationRequest(
                        prompt=prompt_builder(failure),
                        response_schema=draft_model,
                        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
                    ),
                    project_name=self.project_name,
                )
            except TextOutputTruncatedError as exc:
                raise EpisodePlanningError(
                    f"{exc}也可调小项目设置 planning_window_chars（单批窗口字数）或 "
                    "planning_max_episodes（单批集数上限）以缩小本批输出体量后重试。"
                ) from exc
            except StructuredOutputExhaustedError as exc:
                # 后端的降级链已把各档与档内重试都走完，本层再重试只是重复同一条必败路径。
                raise EpisodePlanningError(str(exc)) from exc
            try:
                draft = self._parse_draft(result.text, draft_model)
                drafts = list(draft.episodes)
                if max_episodes is not None and len(drafts) > max_episodes:
                    logger.warning(
                        "规划输出 %d 集超过每批上限 %d，截断保留前 %d 集（其余留给下一批）",
                        len(drafts),
                        max_episodes,
                        max_episodes,
                    )
                    drafts = drafts[:max_episodes]
                ends = _resolve_boundaries(window, drafts, snap_whitespace_tail=snap_whitespace_tail)
                return drafts, ends
            except _DraftRejected as exc:
                failure = exc.reasons
                if exc.valid_prefix_ends and (best_prefix is None or len(exc.valid_prefix_ends) > len(best_prefix[1])):
                    best_prefix = (drafts[: len(exc.valid_prefix_ends)], exc.valid_prefix_ends)
                logger.warning("分集规划第 %d/%d 次尝试未通过校验：%s", attempt, self.max_attempts, exc)
        if best_prefix is not None:
            # 重试耗尽：提交各轮中最长的有效前缀集，失败条目及其后的原文留给下一批规划，
            # 与超出每批上限时截断保留前 N 集同一口径
            logger.warning(
                "分集规划连续 %d 次未全部通过校验，提交最长有效前缀 %d 集（其余留给下一批）；最后一轮原因：%s",
                self.max_attempts,
                len(best_prefix[1]),
                "; ".join(failure or []),
            )
            return best_prefix
        raise EpisodePlanningError(
            f"分集规划连续 {self.max_attempts} 次未通过校验，最后一轮原因：{'; '.join(failure or [])}"
        )

    @staticmethod
    def _parse_draft(
        response_text: str, draft_model: type[NarrationPlanDraft | DramaPlanDraft]
    ) -> NarrationPlanDraft | DramaPlanDraft:
        text = strip_json_code_fences(response_text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("分集规划输出不是合法 JSON（%s）；模型原始输出：%s", exc, truncate_for_log(response_text))
            raise _DraftRejected([f"输出不是合法 JSON：{exc}"]) from exc
        try:
            return draft_model.model_validate(data)
        except ValidationError as exc:
            issues = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
            logger.warning("分集规划输出不符合 schema（%s）；模型原始输出：%s", issues, truncate_for_log(response_text))
            raise _DraftRejected([f"输出不符合 schema：{issues}"]) from exc

    def _effective_start(self, project: Mapping[str, Any]) -> tuple[str, int]:
        """下一批规划起点：以账本中最后一个锚定集的范围末尾为准，游标更靠后时取游标。"""
        last: tuple[str, int] | None = None
        best_num: int | None = None
        for entry in project.get("episodes") or []:
            if not isinstance(entry, dict):
                continue
            num = parse_episode_num(entry.get("episode"))
            source_range = entry.get("source_range")
            if num is None or not isinstance(source_range, Mapping):
                continue
            rel = source_range.get("source_file")
            end = source_range.get("end")
            if (
                isinstance(rel, str)
                and isinstance(end, int)
                and not isinstance(end, bool)
                and (best_num is None or num > best_num)
            ):
                best_num = num
                last = (rel, end)
        cursor = project.get("planning_cursor")
        cur: tuple[str, int] | None = None
        if isinstance(cursor, Mapping):
            rel = cursor.get("source_file")
            offset = cursor.get("offset")
            # 负 offset 会让后续切片静默从尾部取段，按非法游标忽略
            if isinstance(rel, str) and isinstance(offset, int) and not isinstance(offset, bool) and offset >= 0:
                cur = (rel, offset)
        if last is not None and cur is not None:
            if cur[0] == last[0]:
                return (last[0], max(last[1], cur[1]))
            # 文件不同时按源文件顺序取更靠后者，与同文件 max 语义一致：游标滞后取账本末尾，
            # 游标已合法推进到后一个文件则取游标，避免重复规划该文件前缀
            rels = [doc.rel_path for doc in discover_sources(self.project_path)]
            last_idx = rels.index(last[0]) if last[0] in rels else None
            cur_idx = rels.index(cur[0]) if cur[0] in rels else None
            if last_idx is None:
                return cur if cur_idx is not None else last
            if cur_idx is None or cur_idx < last_idx:
                return last
            return cur
        if last is not None:
            return last
        if cur is not None:
            return cur
        sources = discover_sources(self.project_path)
        if not sources:
            raise EpisodePlanningError("source/ 下没有可规划的源文件（.txt/.md），请先上传小说原文")
        return (sources[0].rel_path, 0)

    def _remaining_units_from(self, source_rel: str, start: int, text: str, language: str | None) -> int:
        """当前源文窗口起点之后全部 + 后续源文件总量，按阅读单位计（全局进度提示用）。

        ``discover_sources`` 只调一次：它已返回全部源文件的归一化全文，定位到
        ``source_rel`` 后直接复用后续文件的 ``doc.text``，避免按源文件数循环重复
        调用 ``discover_sources``（每次都会重新读取并归一化目录下全部源文件）。
        """
        total = count_reading_units(text[start:], language)
        sources = discover_sources(self.project_path)
        rels = [doc.rel_path for doc in sources]
        try:
            idx = rels.index(source_rel)
        except ValueError:
            return total
        for doc in sources[idx + 1 :]:
            total += count_reading_units(doc.text, language)
        return total

    def _next_source_rel(self, rel: str) -> str | None:
        """按文件名序返回 ``rel`` 之后的下一个候选源文件；``rel`` 不在候选或已是最后一个时返回 None。"""
        rels = [doc.rel_path for doc in discover_sources(self.project_path)]
        try:
            idx = rels.index(rel)
        except ValueError:
            return None
        return rels[idx + 1] if idx + 1 < len(rels) else None

    def _load_normalized_source(self, rel: str) -> str:
        try:
            path = safe_join(self.project_path, rel, allow_base=True)
        except PathTraversalError as exc:
            raise EpisodePlanningError(f"源文件路径越出项目目录：{rel}") from exc
        if not path.is_file():
            raise EpisodePlanningError(f"源文件不存在：{rel}")
        try:
            return normalize_source_text(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            raise EpisodePlanningError(f"源文件读取失败：{rel}: {exc}") from exc

    def _check_source_fingerprints(self, project: Mapping[str, Any], *, sources: list[SourceDoc] | None = None) -> None:
        """比对账本记录的源文指纹与当前源文，不一致（含记录文件已消失）即拒绝规划。

        存量项目无记录 / 新源文件尚未记录时不比对（首次 plan 只补记不报错）。``sources`` 由
        调用方传入以复用已读取的源文快照，缺省时现读一次。
        """
        docs = sources if sources is not None else discover_sources(self.project_path)
        mismatched = mismatched_source_fingerprints(project.get(SOURCE_FINGERPRINTS_KEY), docs)
        if mismatched:
            raise _source_changed_error(mismatched)

    @staticmethod
    def _check_source_ranges(project: Mapping[str, Any]) -> None:
        """账本存在无位置记录的条目即拒绝规划（老项目遗留，指路全量重置）。

        没有 ``source_range`` 的集既无法重造派生文件、也无法证明其覆盖的原文范围，
        续接规划只会与它重叠或遗漏。消费链路（剧本 / 媒体 / 状态 / 导出）不受影响。
        """
        missing = episodes_without_source_range(project)
        if missing:
            raise _missing_source_range_error(missing)

    async def _backfill_source_fingerprints_if_missing(
        self,
        project: Mapping[str, Any],
        *,
        used_fingerprints: dict[str, str],
        cancellation_receipts: list[FormalWriteReceipt] | None = None,
    ) -> dict:
        """存量项目在 ``source_exhausted`` 早退路径上补记指纹：该路径不经过 ``plan()`` 的
        提交闭包，若跳过会让「首次 plan 补记指纹」对已耗尽游标的存量项目失效——后续等长
        编辑旧正文都因无基线可比而放行。已有指纹的项目直接原样返回，不重复计算。

        ``used_fingerprints`` 是本次 plan() 调用锁外读入的源文摘要基线（入口快照 + 循环
        中途新发现的源文件）：锁内复核与常规提交路径同一套逃生口——若 plan() 保存快照后、
        本闭包读取前源文被改动，直接把变更内容登记为基线会让这次变更永久失去可比对象，
        须先拒绝。
        """
        if project.get(SOURCE_FINGERPRINTS_KEY) is not None:
            return dict(project)

        def _commit(p: dict) -> None:
            current_sources = discover_sources(self.project_path)
            self._check_source_fingerprints(p, sources=current_sources)
            current_fingerprints = compute_source_fingerprints(current_sources)
            changed = sorted(rel for rel, fp in used_fingerprints.items() if current_fingerprints.get(rel) != fp)
            if changed:
                raise _source_changed_error(changed)
            p[SOURCE_FINGERPRINTS_KEY] = current_fingerprints

        return await self._update_project_compensably(
            _commit,
            cancellation_receipts=cancellation_receipts,
        )

    async def _update_project_compensably(
        self,
        mutate: Callable[[dict], None],
        *,
        formal_paths: tuple[Path, ...] = (),
        cancellation_receipts: list[FormalWriteReceipt] | None = None,
    ) -> dict:
        receipts = cancellation_receipts if cancellation_receipts is not None else []
        try:
            return await run_sync_transaction(
                self.pm.update_project,
                self.project_name,
                mutate,
                formal_paths=formal_paths,
                cancellation_receipts=receipts,
            )
        except asyncio.CancelledError:
            if receipts:
                receipt = receipts[0]

                def _compensate_cancelled() -> None:
                    with project_metadata_lock(self.project_path):
                        receipt.compensate_cancelled()

                await run_noninterruptible_sync(_compensate_cancelled)
            raise

    @staticmethod
    def _setting_int(project: Mapping[str, Any], key: str, default: int) -> int:
        value = project.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
        if value is not None:
            logger.warning("项目设置 %s=%r 非法，回退内部默认 %d", key, value, default)
        return default

    def _reconcile_derived_files(self, project: Mapping[str, Any], text_cache: dict[str, str]) -> None:
        """按账本全量对账派生集文件：重写每一集、删除账本之外的残留。

        账本条目此刻必然都带 source_range（提交前经 ``_check_source_ranges`` 门禁），
        缺记录仍按损坏中止提交。余文文件 ``_remaining.txt`` 已由账本游标取代，一并
        清理。每次提交全量对账使中途崩溃后重跑即可自愈。

        两阶段执行：先全量校验并构建写入计划，全部通过后再统一落盘——锚定集
        原文范围非法或源文不可读时在校验阶段抛错中止提交（账本写回随之回滚，
        派生文件未动），保证"提交成功 ⇒ 账本内每一集的派生文件已按账本重写"；
        落盘阶段的环境性失败（磁盘等）靠重跑自愈。残留文件删除失败仅告警——
        残留不在账本中，账本驱动的下游不会读到它。
        """
        source_dir = self.project_path / "source"
        # source/ 是符号链接时拒绝写入：派生文件会落到链接目标（可能在项目外）
        if source_dir.is_symlink():
            raise EpisodePlanningError("source/ 不能是符号链接，拒绝派生集文件")
        keep: set[int] = set()
        writes: list[tuple[Path, str]] = []
        for entry in project.get("episodes") or []:
            if not isinstance(entry, dict):
                continue
            num = parse_episode_num(entry.get("episode"))
            if num is None:
                continue
            keep.add(num)
            source_range = entry.get("source_range")
            if not isinstance(source_range, Mapping):
                raise EpisodePlanningError(f"第 {num} 集缺少原文范围记录，无法完成派生文件对账，提交已中止")
            rel = source_range.get("source_file")
            seg_start = source_range.get("start")
            seg_end = source_range.get("end")
            if (
                not isinstance(rel, str)
                or not isinstance(seg_start, int)
                or not isinstance(seg_end, int)
                or isinstance(seg_start, bool)
                or isinstance(seg_end, bool)
            ):
                raise EpisodePlanningError(f"第 {num} 集原文范围记录非法，无法完成派生文件对账，提交已中止")
            text = text_cache.get(rel)
            if text is None:
                try:
                    text = self._load_normalized_source(rel)
                except EpisodePlanningError as exc:
                    raise EpisodePlanningError(f"第 {num} 集派生文件重写失败，提交已中止：{exc}") from exc
                text_cache[rel] = text
            # Python 切片对负值/越界静默容忍，脏坐标会写出与账本不符的内容，必须显式拦截
            if not 0 <= seg_start <= seg_end <= len(text):
                raise EpisodePlanningError(
                    f"第 {num} 集原文范围越界（start={seg_start}，end={seg_end}，源文长度 {len(text)}），"
                    "无法完成派生文件对账，提交已中止"
                )
            episode_path = episode_source_path(self.project_path, num)
            # 文件级符号链接同样拒绝：write_text 会跟随链接把内容写到链接目标（可能在项目外）
            if episode_path.is_symlink():
                raise EpisodePlanningError(f"第 {num} 集派生文件是符号链接，拒绝写入，提交已中止")
            writes.append((episode_path, text[seg_start:seg_end]))
        # 校验全部通过后统一落盘：校验类失败不会留下按新布局部分重写的派生文件
        source_dir.mkdir(exist_ok=True)
        for episode_path, content in writes:
            # 派生文件的字节与账本切片文本一致：不做平台换行翻译，Manifest 依据按字节重算才稳定。
            episode_path.write_text(content, encoding="utf-8", newline="\n")
        for num, path in discover_episode_files(self.project_path).items():
            if num not in keep:
                try:
                    path.unlink()
                except OSError as exc:
                    logger.warning("残留派生文件清理失败（不阻断提交）：%s: %s", path, exc)
        remaining = source_dir / "_remaining.txt"
        if remaining.is_file():
            try:
                remaining.unlink()
            except OSError as exc:
                logger.warning("余文文件清理失败（不阻断提交）：%s: %s", remaining, exc)

    def _compute_ledger_stats(self, project: Mapping[str, Any]) -> LedgerStats:
        """账本现算全局体量分布：累计集数、最小 5 集、体量中位数（供偏差核对用）。

        读原文按 source_range 切片计体量。无位置记录或原文读取失败的条目跳过，
        不阻断整体统计（核对材料本身是尽力而为、非提交前置校验）。
        """
        language = _language_of(project)
        text_cache: dict[str, str] = {}
        units_by_episode: dict[int, int] = {}
        for entry in project.get("episodes") or []:
            if not isinstance(entry, dict):
                continue
            num = parse_episode_num(entry.get("episode"))
            if num is None:
                continue
            source_range = entry.get("source_range")
            if not isinstance(source_range, Mapping):
                continue
            rel = source_range.get("source_file")
            start = source_range.get("start")
            end = source_range.get("end")
            if (
                not isinstance(rel, str)
                or not isinstance(start, int)
                or not isinstance(end, int)
                or isinstance(start, bool)
                or isinstance(end, bool)
            ):
                continue
            text = text_cache.get(rel)
            if text is None:
                try:
                    text = self._load_normalized_source(rel)
                except EpisodePlanningError:
                    continue
                text_cache[rel] = text
            if not 0 <= start <= end <= len(text):
                continue
            units_by_episode[num] = count_reading_units(text[start:end], language)

        ordered = sorted(units_by_episode.items(), key=lambda pair: (pair[1], pair[0]))
        values = sorted(units_by_episode.values())
        return LedgerStats(
            total_episodes=_count_planned_episodes(project),
            smallest=ordered[:5],
            median_units=round(statistics.median(values)) if values else None,
            target_volume=resolve_episode_target_volume(project, language=language),
        )


def _sort_episodes_if_possible(episodes: list[Any]) -> None:
    """全部集号可解析时按集号排序，否则保持原序。"""
    if all(isinstance(e, dict) and parse_episode_num(e.get("episode")) is not None for e in episodes):
        episodes.sort(key=lambda e: parse_episode_num(e["episode"]) or 0)


def _count_planned_episodes(project: Mapping[str, Any]) -> int:
    """账本现算已规划集数（含全部 ledger_status），供全局进度提示使用。"""
    return sum(
        1
        for entry in (project.get("episodes") or [])
        if isinstance(entry, dict) and parse_episode_num(entry.get("episode")) is not None
    )


def _context_entries(project: Mapping[str, Any]) -> list[dict[str, Any]]:
    """已规划末尾若干集的 标题+钩子，作为续写连贯性上下文。

    只取有位置记录的条目：没有 source_range 的集不是本机制规划出来的，它的标题/钩子
    未必出自同一套分集口径，不拿来当续写基准。
    """
    anchored: list[tuple[int, dict[str, Any]]] = []
    for entry in project.get("episodes") or []:
        if not isinstance(entry, dict):
            continue
        num = parse_episode_num(entry.get("episode"))
        if num is None or not isinstance(entry.get("source_range"), Mapping):
            continue
        anchored.append((num, entry))
    anchored.sort(key=lambda pair: pair[0])
    return [e for _, e in anchored[-_CONTEXT_EPISODES_LIMIT:]]


def _target_volume_line(volume: EpisodeTargetVolume | None) -> str:
    """规划 prompt 的「每集目标体量」行，按来源分三种措辞。

    折算来源的措辞写明目标时长与换算语速：模型据此知道这个数是估出来的、可为剧情完整性
    浮动，而不是用户逐字给定的体量。
    """
    if volume is None:
        return "- 每集目标体量：未设置，请按短视频节奏自行把握（以剧情弧完整优先）"
    if volume.source == "duration":
        return (
            f"- 每集目标体量：约 {volume.units} {volume.unit_noun}"
            f"（按单集目标时长 {volume.seconds} 秒、口播语速约 {volume.units_per_second:g} "
            f"{volume.unit_noun}/秒粗略折算，允许为剧情完整性上下浮动）"
        )
    return f"- 每集目标体量：约 {volume.units} {volume.unit_noun}（允许为剧情完整性上下浮动）"


def _build_planning_prompt(
    *,
    project: Mapping[str, Any],
    window: str,
    window_is_final: bool,
    max_episodes: int | None,
    content_mode: str,
    context_entries: list[dict[str, Any]],
    instructions: str | None,
    failure: list[str] | None,
    progress: _PlanningProgress | None = None,
) -> str:
    """规划 prompt。仅面向文本模型，不做 i18n。

    ``instructions`` 非空时注入一个中性的「附加指令」分节（遵循强度由附加指令正文自行表达，
    模板不加强度限定词）；为空则不注入，prompt 与无附加指令时逐字一致。``progress`` 非 None 时
    注入「全局进度」分节（调用方只在 instructions 非空时传入）。
    """
    overview = project.get("overview") or {}
    language = _language_of(project)
    unit_name = reading_unit_noun(language)
    target_volume = resolve_episode_target_volume(project, language=language)
    is_screenplay = resolve_source_kind(project) == "screenplay"

    lines: list[str] = [
        *(_PLAN_INTRO_SCREENPLAY if is_screenplay else _PLAN_INTRO_NOVEL),
        "",
        "# 项目信息",
        f"- 创作类型：{'剧情演绎（drama）' if content_mode == 'drama' else '旁白/解说（narration）'}",
    ]
    synopsis = overview.get("synopsis") if isinstance(overview, Mapping) else None
    if synopsis:
        lines.append(f"- 故事概述：{synopsis}")
    genre = overview.get("genre") if isinstance(overview, Mapping) else None
    if genre:
        lines.append(f"- 题材：{genre}")
    lines.append(_target_volume_line(target_volume))
    if max_episodes is not None:
        lines.append(f"- 本批最多规划 {max_episodes} 集")

    if context_entries:
        lines += ["", "# 已规划的前情（已定上下文，不可改动，续着它往下规划）"]
        for entry in context_entries:
            title = entry.get("title") or "（无标题）"
            hook = entry.get("hook") or ""
            lines.append(f"- 第 {entry.get('episode')} 集《{title}》 钩子：{hook}")

    if instructions:
        lines += ["", USER_INSTRUCTIONS_HEADER, instructions]
    if progress is not None:
        lines += [
            "",
            "# 全局进度",
            f"- 已规划 {progress.planned_count} 集",
            f"- 未规划余量约 {progress.remaining_units} {unit_name}（含本窗口，含后续源文件）",
            f"- 本窗口为其中前 {progress.window_units} {unit_name}",
            "- 若附加指令含总集数、按章节对齐等全局约束，请结合以上进度与余量换算本批的切分节奏与集数。",
        ]

    lines += [
        "",
        "# 切分规则",
        "- 每一集给出 title（吸引人的短标题）、hook（集尾钩子说明：这一刀为什么切在这、给观众留了什么悬念）、",
        "  end_anchor（本集结尾处的原文片段，10~30 个字符，必须从下方原文中逐字摘抄、含标点，且在整段原文中唯一出现；",
        "  本集内容 = 上一集结尾之后到该片段末尾为止的全部原文）。",
        "  片段须止于句末标点或段落结尾，不要在片段外另加引号，不要用省略号缩写。",
    ]
    if is_screenplay:
        lines.append(_PLAN_RULE_SCREENPLAY)
    if content_mode == "drama":
        lines.append(_PLAN_DRAMA_OUTLINE_SCREENPLAY if is_screenplay else _PLAN_DRAMA_OUTLINE_NOVEL)
    lines += [
        "- 各集按顺序排列，end_anchor 位置必须严格递增（范围连续、不重叠、不留空洞）。",
    ]
    if window_is_final:
        lines.append("- 这段原文已包含全文结尾：请规划到结尾，最后一集的 end_anchor 取全文结尾处的片段，不要留尾巴。")
    else:
        lines.append("- 这段原文只是全文的一个窗口：窗口尾部剧情弧不完整的内容不要硬凑成集，留给下一批规划即可。")
    lines.append("- 只输出符合 schema 的 JSON，不要输出其他内容。")

    if failure:
        lines += ["", "# 上一轮输出未通过校验，请针对性修正后重新输出"]
        lines += [f"- {reason}" for reason in failure]

    lines += ["", "# 剧本原文片段" if is_screenplay else "# 小说原文片段", "---", window, "---"]
    return "\n".join(lines)
