"""Pure, deterministic M10-B packaging checks over one candidate, its constraint snapshot and verified facts.

The host supplies facts it measured from verified private snapshots; nothing here reads files, clocks or network.
Every declared rule runs; the six safety checks are mandatory in every snapshot, so they always run.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass

from r2.contracts import quality as q
from r2.contracts.advanced_creative import PackagingCandidate, PackagingChapter
from r2.quality.digests import compute_digest


@dataclass(frozen=True)
class VerifiedAsset:
    """Bytes the host re-hashed from a verified private snapshot of one declared asset."""

    content_digest: str
    byte_size: int
    media_type: str


@dataclass(frozen=True)
class PackagingFacts:
    approved_master_id: str
    approved_master_digest: str
    assessed_subject_digest: str
    profile_id: str
    profile_revision: int
    profile_digest: str
    duration_ms: int
    width: int
    height: int
    assets: Mapping[tuple[str, str | None], VerifiedAsset]


@dataclass(frozen=True)
class RuleOutcome:
    rule_id: str
    check_id: str
    severity: str
    locator: str
    code: str


@dataclass(frozen=True)
class PackagingCheckResult:
    status: q.ObservationStatus
    failures: tuple[RuleOutcome, ...]
    evaluated_rule_ids: tuple[str, ...]


type _Check = Callable[[PackagingCandidate, q.PlatformConstraintSnapshot, PackagingFacts], Iterator[tuple[str, str]]]

_MARKDOWN_INLINE = re.compile(r"\*\*|`|\]\(")
_MARKDOWN_BLOCK = re.compile(r"(?m)^[ \t]{0,3}(#{1,6}[ \t]|[-*+][ \t]|>)")


def _norm(value: str) -> str:
    """Slug-tolerant comparison (Kalinga `seo_lint`): `-`/`_` read as spaces, case-insensitive."""
    return re.sub(r"[-_]+", " ", value).casefold()


def _titles(candidate: PackagingCandidate) -> Iterator[tuple[str, str]]:
    yield "title", candidate.title
    for item in candidate.localization_variants:
        yield f"locales[{item.locale}].title", item.title
    yield from _variant_texts(candidate, "title")


def _descriptions(candidate: PackagingCandidate) -> Iterator[tuple[str, str]]:
    yield "description", candidate.description
    for item in candidate.localization_variants:
        yield f"locales[{item.locale}].description", item.description
    yield from _variant_texts(candidate, "description")


def _variant_texts(candidate: PackagingCandidate, field: str) -> Iterator[tuple[str, str]]:
    for group in candidate.variant_groups:
        if group.field != field:
            continue
        for variant in group.variants:
            text = None if variant.value is None else dict(variant.value.model_dump(mode="python")).get("text")
            yield f"variants[{group.group_id}/{variant.variant_id}]", text if isinstance(text, str) else ""


def _tag_sets(candidate: PackagingCandidate) -> Iterator[tuple[str, tuple[str, ...], tuple[str, ...]]]:
    yield "", candidate.tags, candidate.hashtags
    for item in candidate.localization_variants:
        yield f"locales[{item.locale}].", item.tags, item.hashtags


def _chapter_sets(candidate: PackagingCandidate) -> Iterator[tuple[str, tuple[PackagingChapter, ...]]]:
    yield "chapters", candidate.chapters
    for item in candidate.localization_variants:
        yield f"locales[{item.locale}].chapters", item.chapters


def _asset_integrity(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    roles = {role.role: role for role in constraints.asset_roles}
    seen: set[tuple[str, str | None]] = set()
    for asset in candidate.assets:
        key = (asset.role, asset.variant_id)
        locator = f"assets[{asset.role}/{asset.variant_id or '-'}]"
        role = roles.get(asset.role)
        if key in seen:
            yield locator, "DUPLICATE_ASSET"
            continue
        seen.add(key)
        if role is None:
            yield locator, "UNDECLARED_ROLE"
            continue
        if asset.constraint_rule_id != role.constraint_rule_id:
            yield locator, "RULE_BINDING_MISMATCH"
        if asset.media_type not in role.media_types:
            yield locator, "MEDIA_TYPE_NOT_ALLOWED"
        if asset.byte_size > role.max_bytes:
            yield locator, "ASSET_TOO_LARGE"
        verified = facts.assets.get(key)
        if verified is None:
            yield locator, "ASSET_NOT_VERIFIED"
        elif (verified.content_digest, verified.byte_size, verified.media_type) != (
            asset.content_digest,
            asset.byte_size,
            asset.media_type,
        ):
            yield locator, "ASSET_BYTES_DRIFT"


def _asset_required(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    present = {asset.role for asset in candidate.assets if asset.variant_id is None}
    for role in constraints.asset_roles:
        if role.required and role.role not in present:
            yield f"assets[{role.role}]", "REQUIRED_ASSET_MISSING"


def _closure_content(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    if compute_digest("m10.packaging-content.v1", candidate) != candidate.content_closure_digest:
        yield "content_closure_digest", "CLOSURE_MISMATCH"


def _closure_presentation(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    if compute_digest("m10.packaging-presentation.v1", candidate) != candidate.presentation_closure_digest:
        yield "presentation_closure_digest", "CLOSURE_MISMATCH"


def _closure_subject(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    if candidate.assessed_subject_digest != facts.assessed_subject_digest:
        yield "assessed_subject_digest", "SUBJECT_MISMATCH"
    if candidate.constraint_snapshot_digest != compute_digest("m10.platform-constraints.v1", constraints):
        yield "constraint_snapshot_digest", "CONSTRAINT_SNAPSHOT_MISMATCH"


def _binding_master(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    if (candidate.approved_master_id, candidate.approved_master_digest) != (
        facts.approved_master_id,
        facts.approved_master_digest,
    ):
        yield "approved_master", "MASTER_MISMATCH"


def _binding_profile(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    if (candidate.quality_profile_id, candidate.quality_profile_revision, candidate.quality_profile_digest) != (
        facts.profile_id,
        facts.profile_revision,
        facts.profile_digest,
    ):
        yield "quality_profile", "PROFILE_MISMATCH"
    if (candidate.platform_profile_id, candidate.platform_profile_revision) != (
        constraints.platform_profile_id,
        constraints.platform_profile_revision,
    ):
        yield "platform_profile", "PLATFORM_PROFILE_MISMATCH"


def _duration(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    if not constraints.min_duration_ms <= facts.duration_ms <= constraints.max_duration_ms:
        yield "master.duration", "DURATION_OUT_OF_WINDOW"


def _dimensions(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    if (facts.width, facts.height) != (constraints.width, constraints.height):
        yield "master.dimensions", "DIMENSIONS_MISMATCH"


def _title_length(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    for locator, title in _titles(candidate):
        if not title.strip():
            yield locator, "TITLE_EMPTY"
        elif len(title) > constraints.title_max_chars:
            yield locator, "TITLE_TOO_LONG"


def _title_terms(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    for locator, title in _titles(candidate):
        for term in constraints.title_required_terms:
            if _norm(term) not in _norm(title):
                yield locator, "TITLE_TERM_MISSING"


def _description_length(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    for locator, description in _descriptions(candidate):
        if len(description) < constraints.description_min_chars:
            yield locator, "DESCRIPTION_TOO_SHORT"
        elif len(description) > constraints.description_max_chars:
            yield locator, "DESCRIPTION_TOO_LONG"


def _description_terms(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    for locator, description in _descriptions(candidate):
        for term in constraints.description_required_terms:
            if _norm(term) not in _norm(description):
                yield locator, "DESCRIPTION_TERM_MISSING"


def _plain_text(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    if not constraints.plain_text_only:
        return
    for locator, text in (*_titles(candidate), *_descriptions(candidate)):
        if _MARKDOWN_INLINE.search(text) or _MARKDOWN_BLOCK.search(text):
            yield locator, "MARKDOWN_NOT_ALLOWED"


def _tag_text_ok(text: str, charset: str) -> bool:
    if not text or text.strip() != text:
        return False
    for character in text:
        if character == " ":
            continue
        if charset == "ASCII_LETTERS_DIGITS_SPACE" and not (character.isascii() and character.isalnum()):
            return False
        if unicodedata.category(character)[0] not in {"L", "N", "M"}:
            return False
    return True


def _tags(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    for prefix, tags, _ in _tag_sets(candidate):
        if not constraints.min_tags <= len(tags) <= constraints.max_tags:
            yield f"{prefix}tags", "TAG_COUNT_OUT_OF_BOUNDS"
        if len({tag.casefold() for tag in tags}) != len(tags):
            yield f"{prefix}tags", "DUPLICATE_TAG"
        for index, tag in enumerate(tags):
            if len(tag) > constraints.max_tag_chars:
                yield f"{prefix}tags[{index}]", "TAG_TOO_LONG"
            elif not _tag_text_ok(tag, constraints.tag_charset):
                yield f"{prefix}tags[{index}]", "TAG_CHARSET"


def _hashtags(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    for prefix, _, hashtags in _tag_sets(candidate):
        if not constraints.min_hashtags <= len(hashtags) <= constraints.max_hashtags:
            yield f"{prefix}hashtags", "HASHTAG_COUNT_OUT_OF_BOUNDS"
        if len({tag.casefold() for tag in hashtags}) != len(hashtags):
            yield f"{prefix}hashtags", "DUPLICATE_HASHTAG"
        for index, tag in enumerate(hashtags):
            body = tag.removeprefix("#")
            if len(tag) > constraints.max_hashtag_chars:
                yield f"{prefix}hashtags[{index}]", "HASHTAG_TOO_LONG"
            elif not tag.startswith("#") or " " in body or not _tag_text_ok(body, constraints.tag_charset):
                yield f"{prefix}hashtags[{index}]", "HASHTAG_FORM"


def _banned(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    texts = [*_titles(candidate), *_descriptions(candidate)]
    for prefix, tags, hashtags in _tag_sets(candidate):
        texts.extend((f"{prefix}tags", tag) for tag in (*tags, *hashtags))
    for locator, text in texts:
        if any(phrase.casefold() in text.casefold() for phrase in constraints.banned_phrases):
            yield locator, "BANNED_PHRASE"


def _chapters(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    for locator, chapters in _chapter_sets(candidate):
        if not chapters:
            continue
        if len(chapters) > constraints.max_chapters:
            yield locator, "TOO_MANY_CHAPTERS"
        if chapters[0].start_ms != 0:
            yield locator, "FIRST_CHAPTER_NOT_AT_ZERO"
        bounds = [chapter.start_ms for chapter in chapters] + [facts.duration_ms]
        for index, chapter in enumerate(chapters):
            if not chapter.title.strip():
                yield f"{locator}[{index}]", "CHAPTER_TITLE_EMPTY"
            if bounds[index + 1] - bounds[index] < constraints.chapter_min_ms:
                yield f"{locator}[{index}]", "CHAPTER_TOO_SHORT"


def _locales(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    locales = [item.locale for item in candidate.localization_variants]
    if len(set(locales)) != len(locales):
        yield "localization_variants", "DUPLICATE_LOCALE"
    for locale in constraints.required_locales:
        if locale not in locales:
            yield f"locales[{locale}]", "LOCALE_MISSING"


def _variants(candidate, constraints, facts) -> Iterator[tuple[str, str]]:
    groups = candidate.variant_groups
    if len(groups) > constraints.max_variant_groups:
        yield "variant_groups", "TOO_MANY_VARIANT_GROUPS"
    if len({group.group_id for group in groups}) != len(groups):
        yield "variant_groups", "DUPLICATE_VARIANT_GROUP"
    roles = {role.role for role in constraints.asset_roles}
    asset_keys = {(asset.role, asset.variant_id) for asset in candidate.assets}
    for group in groups:
        locator = f"variant_groups[{group.group_id}]"
        if len(group.variants) > constraints.max_variants_per_group:
            yield locator, "TOO_MANY_VARIANTS"
        if len({variant.variant_id for variant in group.variants}) != len(group.variants):
            yield locator, "DUPLICATE_VARIANT"
        for variant in group.variants:
            item = f"{locator}/{variant.variant_id}"
            if (group.field == "thumbnail") != (variant.asset_role is not None):
                yield item, "VARIANT_SOURCE_MISMATCH"
            elif variant.asset_role is not None and (
                variant.asset_role not in roles or (variant.asset_role, variant.variant_id) not in asset_keys
            ):
                yield item, "VARIANT_ASSET_MISSING"


CHECKS: Mapping[str, _Check] = {
    "asset.integrity": _asset_integrity,
    "asset.required": _asset_required,
    "closure.content": _closure_content,
    "closure.presentation": _closure_presentation,
    "closure.subject": _closure_subject,
    "binding.master": _binding_master,
    "binding.profile": _binding_profile,
    "duration.window": _duration,
    "video.dimensions": _dimensions,
    "title.length": _title_length,
    "title.terms": _title_terms,
    "description.length": _description_length,
    "description.terms": _description_terms,
    "text.plain": _plain_text,
    "tags.bounds": _tags,
    "hashtags.bounds": _hashtags,
    "phrases.banned": _banned,
    "chapters.rules": _chapters,
    "locales.coverage": _locales,
    "variants.bounds": _variants,
}


def check_package(
    candidate: PackagingCandidate, constraints: q.PlatformConstraintSnapshot, facts: PackagingFacts
) -> PackagingCheckResult:
    """Run every declared rule in declaration order; FAIL iff a BLOCKING rule failed."""
    if set(CHECKS) != set(q.PACKAGING_CHECK_CLASSES):
        raise RuntimeError("M10_SCHEMA_CHANGE_REQUIRED")
    failures: list[RuleOutcome] = []
    for rule in constraints.rules:
        for locator, code in CHECKS[rule.check_id](candidate, constraints, facts):
            failures.append(RuleOutcome(rule.rule_id, rule.check_id, rule.severity, locator, code))
    blocking = any(failure.severity == "BLOCKING" for failure in failures)
    return PackagingCheckResult(
        status=q.ObservationStatus.FAIL if blocking else q.ObservationStatus.PASS,
        failures=tuple(failures),
        evaluated_rule_ids=tuple(rule.rule_id for rule in constraints.rules),
    )


__all__ = ["CHECKS", "PackagingCheckResult", "PackagingFacts", "RuleOutcome", "VerifiedAsset", "check_package"]
