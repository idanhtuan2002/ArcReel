"""Whether a model's descriptive text is clean: no reasoning, schema scaffolding or broken bytes leaked into it.

Small and free models sometimes answer a field with their working ("* Input: …", "Let us reason step by step", "Người
dùng yêu cầu …"), a schema field name, a code fence or tool tag, or mis-decoded bytes. Written into a title, a
description or an image prompt, it travels to the film. These rules are DramaClaw's appearance validator
(``agents/identity_planner.py`` ``_appearance_corruption_reason`` at b299bfd), extended with the leaks seen on our
own routes (Gemma's "* Input:", thinking tags, Vietnamese and Chinese openings of reasoning).

They are for descriptive fields only — titles, hooks, loglines, asset descriptions, prompts — never for prose or
dialogue, where "let's" or "để tôi" is ordinary speech.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_SCAFFOLDING = re.compile(r"```|</?tool|</?think|@returns|/\* *empty *\*/", re.IGNORECASE)
_REASONING = re.compile(
    r"\blet(?:'s| us) (?:reason|think|analy[sz]e|check|count|break|consider)\b|\bstep by step\b|\banalysis\s*:"
    r"|\bthinking\s*:|\breasoning\s*:|\bcount\s*:|\bcheck (?:the )?length\b|\bthat's about\b|^\s*\*\s*input\s*:"
    r"|\bthe user (?:asks|wants|requested)\b"
    r"|người dùng (?:yêu cầu|muốn)|yêu cầu của người dùng|hãy phân tích|phân tích yêu cầu"
    r"|用户(?:要求|希望|想要)|让我(?:们)?(?:来|先)?(?:分析|思考|检查)|首先分析",
    re.IGNORECASE | re.MULTILINE,
)


def leak_reason(text: object, *, schema_fields: Iterable[str] = ()) -> str | None:
    """Why ``text`` is not a clean description, in a few words; ``None`` when it is clean or empty."""
    value = str(text or "").strip()
    if not value:
        return None
    if "�" in value:
        return "it contains a broken character (U+FFFD)"
    lowered = value.casefold()
    if any(len(field) > 3 and field.casefold() in lowered for field in schema_fields):
        return "it contains a field name of the answer's schema"
    if _SCAFFOLDING.search(value):
        return "it contains code or tool markup"
    if _REASONING.search(value):
        return "it contains the model's reasoning instead of the answer"
    return None


__all__ = ["leak_reason"]
