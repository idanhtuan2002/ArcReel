"""Documentary narration from a sourced fact pack (ADR-0162): history, true crime, mysteries, biography.

A topic is researched on public reference pages (Wikipedia, the topic's language first, then English); their
paragraphs are the evidence. The model extracts claims, each with the evidence it rests on and a verbatim quote; a
claim whose quote is not in that evidence is dropped. The model then writes the narration in chapters where every
paragraph cites the claims it states; a paragraph citing nothing, or a claim not in the ledger, sends the draft back.
The result is a ``ResearchPack`` and a ``ClaimLedger`` (``r2/contracts/factual.py``), a manuscript the film and
audiobook paths read, and a citation list. The model never adds a fact that is not in the ledger (vision R-A2.3).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lib.text_backends.base import TextGenerationRequest, TextGenerationResult
from r2.contracts.factual import Claim, ClaimLedger, ClaimStatus, EvidenceRecord, ResearchPack, SourceRecord

type Fetch = Callable[[str, Mapping[str, str]], Awaitable[Mapping[str, Any]]]
type Generate = Callable[[TextGenerationRequest], Awaitable[TextGenerationResult]]

MAX_PAGES = 3
MAX_EVIDENCE = 60
MIN_EVIDENCE_CHARS = 80
MAX_ATTEMPTS = 3


class DocumentaryError(RuntimeError):
    """The topic could not be researched or written; the message names why."""


@dataclass(frozen=True)
class Page:
    title: str
    url: str
    language: str
    text: str


@dataclass(frozen=True)
class Evidence:
    id: str
    page: Page
    locator: str
    text: str


class _ClaimItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=5, max_length=400)
    evidence_id: str = Field(min_length=1, max_length=20)
    quote: str = Field(min_length=5, max_length=400)


class ClaimsDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[_ClaimItem] = Field(min_length=1, max_length=40)
    uncertainties: list[str] = Field(default_factory=list, max_length=10)


class _Paragraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=20, max_length=1500)
    claims: list[str] = Field(max_length=12)


class _Chapter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=2, max_length=120)
    paragraphs: list[_Paragraph] = Field(min_length=1, max_length=12)


class DocumentaryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=2, max_length=150)
    hook: str = Field(min_length=10, max_length=300)
    chapters: list[_Chapter] = Field(min_length=2, max_length=6)


def _api(language: str) -> str:
    return f"https://{language}.wikipedia.org/w/api.php"


async def research_pages(topic: str, languages: Sequence[str], fetch: Fetch) -> list[Page]:
    """The best-matching reference pages for ``topic``: up to ``MAX_PAGES`` per language, in the order given,
    stopping at the first language that has any."""
    for language in languages:
        found = await fetch(
            _api(language),
            {"action": "query", "list": "search", "srsearch": topic, "srlimit": str(MAX_PAGES), "format": "json"},
        )
        titles = [hit["title"] for hit in (found.get("query") or {}).get("search", []) if hit.get("title")]
        pages: list[Page] = []
        for title in titles[:MAX_PAGES]:
            body = await fetch(
                _api(language),
                {
                    "action": "query",
                    "prop": "extracts|info",
                    "explaintext": "1",
                    "inprop": "url",
                    "titles": title,
                    "format": "json",
                },
            )
            for page in ((body.get("query") or {}).get("pages") or {}).values():
                text = str(page.get("extract") or "").strip()
                if text:
                    pages.append(Page(str(page.get("title") or title), str(page.get("fullurl") or ""), language, text))
        if pages:
            return pages
    raise DocumentaryError("NO_SOURCES")


def evidence_from(pages: Sequence[Page]) -> list[Evidence]:
    """Each page's paragraphs (section headings as locators), longest pages first, at most ``MAX_EVIDENCE``."""
    out: list[Evidence] = []
    for page in pages:
        section = "Lead"
        for block in re.split(r"\n\s*\n|\n(?===)", page.text):
            lines = block.strip().splitlines()
            while lines and (heading := re.match(r"^=+\s*(.+?)\s*=+$", lines[0].strip())):
                section = heading.group(1)
                lines = lines[1:]
            text = " ".join(line.strip() for line in lines).strip()
            if len(text) >= MIN_EVIDENCE_CHARS:
                out.append(Evidence(f"E{len(out) + 1}", page, f"{page.title} § {section}", text))
            if len(out) >= MAX_EVIDENCE:
                return out
    return out


def _fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).lower().replace("“", '"').replace("”", '"').split())


def verified_claims(draft: ClaimsDraft, evidence: Mapping[str, Evidence]) -> list[tuple[str, _ClaimItem]]:
    """The drafted claims whose quote occurs verbatim (case and spacing aside) in the evidence they cite."""
    kept: list[tuple[str, _ClaimItem]] = []
    for item in draft.claims:
        source = evidence.get(item.evidence_id)
        if source is not None and _fold(item.quote) in _fold(source.text):
            kept.append((f"C{len(kept) + 1}", item))
    return kept


def draft_problems(draft: DocumentaryDraft, claim_ids: set[str]) -> list[str]:
    problems: list[str] = []
    for chapter in draft.chapters:
        for index, paragraph in enumerate(chapter.paragraphs, start=1):
            if not paragraph.claims:
                problems.append(f"chapter '{chapter.title}' paragraph {index} cites no claim")
            unknown = [c for c in paragraph.claims if c not in claim_ids]
            if unknown:
                problems.append(f"chapter '{chapter.title}' paragraph {index} cites unknown claims {unknown}")
    return problems


def _claims_prompt(topic: str, evidence: Sequence[Evidence], language: str) -> str:
    listing = "\n\n".join(f"[{e.id}] ({e.locator})\n{e.text}" for e in evidence)
    return (
        f"Topic: {topic}\nWrite in: {language}\n\n"
        "From the evidence below, list the factual claims a documentary about the topic needs (who, what, when, "
        "where, how, numbers, outcomes). For each claim give: statement (one sentence in the output language), "
        "evidence_id (the [E..] it rests on) and quote (a passage copied character for character from that "
        "evidence). Use only the evidence; leave out anything it does not state. List what the evidence leaves "
        "uncertain or disputed in uncertainties.\n\n"
        f"EVIDENCE\n{listing}"
    )


def _writing_prompt(topic: str, claims: Sequence[tuple[str, _ClaimItem]], language: str, problems: list[str]) -> str:
    listing = "\n".join(f"[{cid}] {item.statement}" for cid, item in claims)
    fix = ("\n\nThe previous draft had these problems; fix them:\n- " + "\n- ".join(problems)) if problems else ""
    return (
        f"Write a narrated documentary about: {topic}\nLanguage: {language}\n\n"
        "Rules:\n"
        "- State only the claims listed below; never add a fact, date, name or number that is not in them.\n"
        "- Every paragraph lists in `claims` the ids of the claims it states.\n"
        "- A hook line first (a question or the most striking fact), then 2–6 chapters that tell it as a story: "
        "setting, people, events in order, turning point, outcome, what is still unknown.\n"
        "- Narration voice: vivid and concrete, spoken sentences of varied length, no lists, no headings inside "
        "paragraphs; where the claims disagree, say so.\n"
        "- Never name the structure (no 'chapter one', 'in this section', 'the story begins'); open each chapter "
        "on a person, a place or a moment.\n"
        "- At most three numbers in a paragraph; turn the rest into what they mean for the people involved.\n\n"
        f"CLAIMS\n{listing}{fix}"
    )


@dataclass
class Documentary:
    title: str
    manuscript: str
    citations: str
    research_pack: ResearchPack
    ledger: ClaimLedger
    sources: list[SourceRecord]
    evidence: list[EvidenceRecord]


async def make_documentary(topic: str, *, language: str, fetch: Fetch, generate: Generate) -> Documentary:
    """Research ``topic``, extract verified claims and write the cited narration; raises
    :class:`DocumentaryError` when no source, no verified claim or no passing draft is found."""
    languages = [language] + (["en"] if language != "en" else [])
    pages = await research_pages(topic, languages, fetch)
    evidence = evidence_from(pages)
    if not evidence:
        raise DocumentaryError("NO_EVIDENCE")
    by_id = {e.id: e for e in evidence}
    claims_result = await generate(
        TextGenerationRequest(prompt=_claims_prompt(topic, evidence, language), response_schema=ClaimsDraft)
    )
    try:
        claims_draft = ClaimsDraft.model_validate(json.loads(claims_result.text))
    except (ValueError, ValidationError) as error:
        raise DocumentaryError(f"CLAIMS_INVALID: {str(error)[:200]}") from error
    claims = verified_claims(claims_draft, by_id)
    if len(claims) < 3:
        raise DocumentaryError("TOO_FEW_VERIFIED_CLAIMS")
    claim_ids = {cid for cid, _ in claims}
    problems: list[str] = []
    draft: DocumentaryDraft | None = None
    for _attempt in range(MAX_ATTEMPTS):
        result = await generate(
            TextGenerationRequest(
                prompt=_writing_prompt(topic, claims, language, problems), response_schema=DocumentaryDraft
            )
        )
        try:
            candidate = DocumentaryDraft.model_validate(json.loads(result.text))
        except (ValueError, ValidationError) as error:
            problems = [f"the answer is not valid JSON for the schema: {str(error)[:300]}"]
            continue
        problems = draft_problems(candidate, claim_ids)
        if not problems:
            draft = candidate
            break
    if draft is None:
        raise DocumentaryError("NO_PASSING_DRAFT: " + "; ".join(problems)[:300])

    now = datetime.now(UTC)
    sources = [
        SourceRecord(
            id=f"S{i + 1}",
            source_type="web_reference",
            title=page.title,
            origin=page.url or _api(page.language),
            captured_at=now,
            source_fingerprint="sha256:" + hashlib.sha256(page.text.encode("utf-8")).hexdigest(),
            provenance={"language": page.language, "api": "mediawiki"},
        )
        for i, page in enumerate(pages)
    ]
    source_of = {page.title: f"S{i + 1}" for i, page in enumerate(pages)}
    records = [
        EvidenceRecord(
            id=e.id,
            source_ref=source_of[e.page.title],
            locator=e.locator,
            excerpt_or_structured_fact=e.text,
            evidence_type="paragraph",
            captured_at=now,
            provenance={},
        )
        for e in evidence
    ]
    ledger_claims = [
        Claim(
            id=cid,
            version=1,
            statement=item.statement,
            evidence_refs=[item.evidence_id],
            confidence=0.9,
            status=ClaimStatus.VERIFIED,
            provenance={"quote": item.quote},
        )
        for cid, item in claims
    ]
    digest = hashlib.sha256(topic.encode("utf-8")).hexdigest()[:12]
    pack = ResearchPack(
        id=f"research-{digest}",
        version=1,
        topic=topic,
        scope=f"public reference pages, {language}",
        source_refs=[s.id for s in sources],
        evidence_refs=[e.id for e in records],
        synthesis=draft.hook,
        uncertainties=list(claims_draft.uncertainties),
        open_questions=[],
        provenance={"pages": [p.url for p in pages]},
    )
    ledger = ClaimLedger(id=f"ledger-{digest}", version=1, research_pack_ref=pack.id, claims=ledger_claims)
    lines = [f"# {draft.title}", "", draft.hook, ""]
    for chapter in draft.chapters:
        lines += [f"## {chapter.title}", ""]
        for paragraph in chapter.paragraphs:
            lines += [paragraph.text.strip(), ""]
    citations = "\n".join(
        [f"# {draft.title} — sources", ""]
        + [f"- [{s.id}] {s.title}: {s.origin}" for s in sources]
        + ["", "## Claims", ""]
        + [f"- [{c.id}] {c.statement} — {by_id[c.evidence_refs[0]].locator}" for c in ledger_claims]
    )
    return Documentary(
        title=draft.title,
        manuscript="\n".join(lines).rstrip() + "\n",
        citations=citations + "\n",
        research_pack=pack,
        ledger=ledger,
        sources=sources,
        evidence=records,
    )


__all__ = [
    "ClaimsDraft",
    "Documentary",
    "DocumentaryDraft",
    "DocumentaryError",
    "Evidence",
    "Page",
    "draft_problems",
    "evidence_from",
    "make_documentary",
    "research_pages",
    "verified_claims",
]
