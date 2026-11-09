"""Translate a project's story into another language, paragraph for paragraph (ADR-0120).

Each source file the project's runs read (``discover_sources``) is translated in batches of paragraphs by the
project's script text model. A batch answer must hold exactly as many paragraphs as the batch, keep every protected
name (the project's registered characters, scenes and props that the paragraph writes) verbatim, stay within a
length band of the source, and carry no CJK text unless the target language is written in it; a batch that fails
is retried with the reasons, at most three times. Translations are written under ``translations/<language>/`` with
a record of the source digest per file, so a repeated request skips files whose source has not changed; the story
sources, episodes and films are never touched.

Donor surfaces: OpenMontage ``localization-dub`` script director (glossary and protected terms, structure kept,
review status per language) and DramaClaw ``source_language`` (supplied names kept verbatim, never translated).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lib.episode_ledger import discover_sources
from lib.json_io import atomic_write_bytes, atomic_write_json
from lib.path_safety import PathTraversalError, safe_join
from lib.text_attestation import has_cjk
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult

type Generate = Callable[[TextGenerationRequest], Awaitable[TextGenerationResult]]

LANGUAGES = {
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "vi": "Vietnamese",
    "zh": "Simplified Chinese",
    "ja": "Japanese",
    "ko": "Korean",
}
CJK_TARGETS = frozenset({"zh", "ja", "ko"})
TRANSLATIONS_DIR = "translations"
BATCH_CHARS = 4000
MAX_ATTEMPTS = 3
#: Translated over source length in characters: same-script pairs, into a CJK language, out of one.
LENGTH_BANDS = {"same": (0.4, 3.0), "to_cjk": (0.12, 1.2), "from_cjk": (0.8, 8.0)}
SCHEMA = "r2.story-translation.v1"


class TranslationError(RuntimeError):
    pass


class TranslatedBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paragraphs: list[str] = Field(min_length=1)


def paragraphs_of(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def batches(paragraphs: Sequence[str], size: int = BATCH_CHARS) -> list[list[str]]:
    """Consecutive paragraphs, each batch at most ``size`` characters unless one paragraph is longer."""
    out: list[list[str]] = []
    current: list[str] = []
    length = 0
    for paragraph in paragraphs:
        if current and length + len(paragraph) > size:
            out.append(current)
            current, length = [], 0
        current.append(paragraph)
        length += len(paragraph)
    if current:
        out.append(current)
    return out


def protected_terms(project: Mapping[str, Any]) -> list[str]:
    """The project's registered character names: kept verbatim in every language. Scene and prop names are often
    ordinary nouns that a translation must translate, so they are not protected."""
    registry = project.get("characters")
    names = [str(name) for name in registry] if isinstance(registry, Mapping) else []
    return sorted(set(names), key=lambda n: (-len(n), n))


def _written_as_name(term: str, text: str) -> bool:
    """``term`` occurs in ``text`` as a name: a CJK name as written; any other one capitalized and not part of a
    longer word ("Hoa" names someone in "Hoa cười", not in "vườn hoa"). A name that is also a word and opens a
    sentence ("Hoa nở khắp vườn") is still read as a name; the model is told to keep names, so it rarely matters."""
    if has_cjk(term):
        return term in text
    if not term[:1].isupper():
        return False
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


def build_prompt(
    batch: Sequence[str], *, target: str, terms: Sequence[str], previous: str, problems: Sequence[str] = ()
) -> str:
    language = LANGUAGES[target]
    listed = json.dumps(list(batch), ensure_ascii=False, indent=1)
    retry = (
        "\nYOUR PREVIOUS ANSWER FAILED THESE CHECKS — fix them:\n" + "\n".join(f"- {p}" for p in problems) + "\n"
        if problems
        else ""
    )
    glossary = ", ".join(terms) if terms else "(none)"
    context = f"\nTHE TRANSLATION SO FAR ENDS WITH:\n<<<\n{previous}\n>>>\n" if previous else ""
    return f"""Translate these paragraphs of a published story into {language} for readers of {language}.
Answer with JSON {{"paragraphs": [...]}}: exactly {len(batch)} paragraphs, the n-th translating the n-th source
paragraph. Translate everything, add nothing, keep dialogue as dialogue and the author's voice and rhythm.
Keep these names exactly as written, never translated or transliterated: {glossary}.
{retry}{context}
SOURCE PARAGRAPHS:
{listed}"""


def check_batch(source: Sequence[str], translated: Sequence[str], *, target: str, terms: Sequence[str]) -> list[str]:
    problems: list[str] = []
    if len(translated) != len(source):
        return [f"the answer has {len(translated)} paragraphs; it must have exactly {len(source)}"]
    for index, (src, out) in enumerate(zip(source, translated, strict=True), start=1):
        missing = [term for term in terms if _written_as_name(term, src) and term not in out]
        if missing:
            problems.append(f"paragraph {index} must keep the name(s) {', '.join(missing)} verbatim")
        bare = out
        for term in terms:  # a protected name may itself be written in CJK
            bare = bare.replace(term, "")
        if target not in CJK_TARGETS and has_cjk(bare):
            problems.append(f"paragraph {index} contains Chinese, Japanese or Korean characters")
    source_cjk = _mostly_cjk("".join(source), terms)
    kind = "same" if source_cjk == (target in CJK_TARGETS) else ("to_cjk" if target in CJK_TARGETS else "from_cjk")
    low, high = LENGTH_BANDS[kind]
    ratio = sum(len(t) for t in translated) / max(1, sum(len(s) for s in source))
    if not low <= ratio <= high:
        problems.append(f"the translation is {ratio:.1f} times the source length; translate fully and only")
    return problems


CJK_SHARE = 0.3


def _mostly_cjk(text: str, terms: Sequence[str]) -> bool:
    """Whether the text is written in a CJK script: a stray Han character or a CJK name does not make it so."""
    for term in terms:
        text = text.replace(term, "")
    letters = [c for c in text if not c.isspace()]
    return bool(letters) and sum(1 for c in letters if has_cjk(c)) / len(letters) > CJK_SHARE


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _paths(project_path: Path, target: str, rel_path: str) -> tuple[Path, Path]:
    # The whole file name, so ``a.txt`` and ``a.md`` never share a translation.
    stem = Path(rel_path).name
    try:
        folder = safe_join(project_path, f"{TRANSLATIONS_DIR}/{target}")
        folder.mkdir(parents=True, exist_ok=True)
        return safe_join(project_path, f"{TRANSLATIONS_DIR}/{target}/{stem}.md"), safe_join(
            project_path, f"{TRANSLATIONS_DIR}/{target}/{stem}.json"
        )
    except PathTraversalError as error:
        raise TranslationError(f"translation path leaves the project: {error}") from None


async def _translate_text(text: str, *, target: str, terms: Sequence[str], generate: Generate) -> tuple[str, int]:
    done: list[str] = []
    calls = 0
    for batch in batches(paragraphs_of(text)):
        problems: list[str] = []
        for _ in range(MAX_ATTEMPTS):
            calls += 1
            prompt = build_prompt(
                batch, target=target, terms=terms, previous=(done[-1] if done else ""), problems=problems
            )
            result = await generate(TextGenerationRequest(prompt=prompt, response_schema=TranslatedBatch))
            try:
                answer = TranslatedBatch.model_validate(json.loads(result.text))
            except (ValueError, ValidationError) as error:
                problems = [f"the answer is not valid JSON for the schema: {str(error)[:200]}"]
                continue
            problems = check_batch(batch, answer.paragraphs, target=target, terms=terms)
            if not problems:
                done.extend(p.strip() for p in answer.paragraphs)
                break
        else:
            raise TranslationError(f"a batch failed its checks after {MAX_ATTEMPTS} attempts: " + "; ".join(problems))
    return "\n\n".join(done) + "\n", calls


async def translate_story(
    project_path: Path, project: Mapping[str, Any], target: str, *, generate: Generate
) -> dict[str, Any]:
    """Translate every story source of the project into ``target``; files already translated from the same source
    text are skipped."""
    if target not in LANGUAGES:
        raise TranslationError(f"unsupported language {target!r}")
    if project.get("source_language") == target:
        raise TranslationError("the story is already written in that language")
    docs = discover_sources(project_path)
    if not docs:
        raise TranslationError("the project has no story text to translate")
    terms = protected_terms(project)
    files: list[dict[str, Any]] = []
    for doc in docs:
        text_path, record_path = _paths(project_path, target, doc.rel_path)
        source_digest = _digest(doc.text)
        if record_path.is_file():
            try:
                previous = json.loads(record_path.read_text(encoding="utf-8"))
            except ValueError:
                previous = {}
            if not isinstance(previous, dict):
                previous = {}
            if previous.get("source_digest") == source_digest and text_path.is_file():
                files.append({"source": doc.rel_path, "skipped": True})
                continue
        translated, calls = await _translate_text(doc.text, target=target, terms=terms, generate=generate)
        data = translated.encode("utf-8")
        atomic_write_bytes(text_path, data)
        atomic_write_json(
            record_path,
            {
                "schema": SCHEMA,
                "source_relpath": doc.rel_path,
                "source_digest": source_digest,
                "target_language": target,
                "text_digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                "protected_terms": terms,
                "calls": calls,
            },
        )
        files.append({"source": doc.rel_path, "skipped": False, "calls": calls})
    return {"target_language": target, "files": files}


__all__ = [
    "LANGUAGES",
    "TranslatedBatch",
    "TranslationError",
    "batches",
    "build_prompt",
    "check_batch",
    "protected_terms",
    "translate_story",
]
