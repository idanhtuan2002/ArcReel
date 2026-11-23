"""Vietnamese narration for narrated films: DramaClaw's own rewrite, then our translation of its lines (D29).

DramaClaw's rewriter (`agents/content_rewriter.py`, route `rewrite/generate`, task `content_rewrite`) writes zh/en
only (`utils/source_language.py`). Asked for Vietnamese output directly, the free text model spent its whole token
budget reasoning and returned nothing (three probes, 8 000-12 000 reasoning tokens, 2026-11-24), while the donor's
own Chinese route completes. So the donor rewrite runs unchanged and its lines are translated back to Vietnamese:
one line in, one line out, the dialogue format `Tên + cách nói + ：“…”` kept for DramaClaw's speaker parser, the
characters' Vietnamese names restored, checked with `lib.story_translation.check_batch` (line count, no CJK left,
length band) and retried.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any

import httpx

from lib.story_translation import check_batch

MAX_ATTEMPTS = 3


def build_prompt(lines: Sequence[str], names: Sequence[str], problems: Sequence[str] = ()) -> str:
    retry = (
        "\nYOUR PREVIOUS ANSWER FAILED THESE CHECKS — fix them:\n" + "\n".join(f"- {p}" for p in problems)
        if problems
        else ""
    )
    return f"""Translate these narration lines of a short video from Chinese into natural spoken Vietnamese.
Each line is read aloud over one shot (3-5 seconds), so keep every line short and in the same order.
The story is Vietnamese; its characters are: {", ".join(names) or "(none)"}. Every Chinese name, nickname or
form of address for one of them (e.g. a transliteration, 姑娘, 老人) must come back as that Vietnamese name or a
natural Vietnamese form of address for that person.
Dialogue lines look like `说话人 + 说话方式 + ：“原句”`; keep that shape: `Tên + cách nói + ：“câu nói”` with the
full-width colon "：" and the quotes “ ”.
Narrate in the third person (no "tôi" for the narrator).
Answer with JSON {{"paragraphs": [...]}}: exactly {len(lines)} lines, the n-th translating the n-th source line.{retry}

SOURCE LINES:
{json.dumps(list(lines), ensure_ascii=False, indent=1)}"""


def _parse(content: str) -> list[str]:
    start, end = content.find("{"), content.rfind("}")
    data: Any = json.loads(content[start : end + 1])
    return [str(p or "").strip() for p in data.get("paragraphs", [])]


# DramaClaw model names on its NewAPI: the translator slot (free ERNIE chain) first; the vision slot (Gemini Flash)
# when the first returns nothing usable — the free reasoning model sometimes spends its whole budget thinking.
MODELS = ("DC-freezone-translator-LLM", "DC-freezone-vision-LLM")
_ASCII_PUNCT = str.maketrans(
    {"？": "?", "！": "!"}
)  # the full-width colon "：" stays: DramaClaw's speaker parser reads it


def translate_lines(lines: Sequence[str], names: Sequence[str], *, newapi_url: str, token: str) -> list[str]:
    problems: list[str] = []
    for model in MODELS:
        problems = []
        for attempt in range(MAX_ATTEMPTS):
            response = httpx.post(
                f"{newapi_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": build_prompt(lines, names, problems)}],
                    "max_tokens": 12000,
                },
                timeout=600,
            )
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(30 * (attempt + 1))
                continue
            response.raise_for_status()
            content = str(response.json()["choices"][0]["message"].get("content") or "")
            try:
                out = [line.translate(_ASCII_PUNCT) for line in _parse(content)]
            except (ValueError, json.JSONDecodeError) as error:
                problems = [f"the answer is not valid JSON: {str(error)[:200]}"]
                continue
            problems = check_batch(list(lines), out, target="vi", terms=list(names))
            problems = [p for p in problems if "must keep the name" not in p]  # source names are Chinese forms
            if not problems:
                return out
    raise RuntimeError("translating the narration failed its checks: " + "; ".join(problems))
