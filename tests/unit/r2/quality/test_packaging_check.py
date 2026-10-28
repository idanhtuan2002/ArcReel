"""The pure packaging check passes a clean package and catches each seeded defect under its own rule."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from r2.contracts import quality as q
from r2.contracts.advanced_creative import PackagingCandidate
from r2.quality.digests import compute_digest
from r2.quality.packaging_check import CHECKS, PackagingFacts, VerifiedAsset, check_package
from tests.unit.r2.contracts.test_packaging import DIGEST, OTHER_DIGEST, UUID, candidate_body, constraints_data, rule

SUBJECT = "sha256:" + "c" * 64


def all_rules_constraints() -> dict[str, Any]:
    data = constraints_data()
    declared = {r["check_id"] for r in data["rules"]}
    for check_id, rule_class in q.PACKAGING_CHECK_CLASSES.items():
        if check_id not in declared:
            data["rules"].append(rule(f"r-{check_id}", check_id, rule_class.value))
    return data


def sealed(body: dict[str, Any], constraints: dict[str, Any]) -> PackagingCandidate:
    body = body | {
        "assessed_subject_digest": SUBJECT,
        "constraint_snapshot_digest": compute_digest("m10.platform-constraints.v1", constraints),
    }
    draft = PackagingCandidate.model_validate(body)
    return PackagingCandidate.model_validate(
        body
        | {
            "content_closure_digest": compute_digest("m10.packaging-content.v1", draft),
            "presentation_closure_digest": compute_digest("m10.packaging-presentation.v1", draft),
        }
    )


def clean_body() -> dict[str, Any]:
    body = candidate_body()
    body["description"] = "How the river shaped the valley over ten thousand years."
    body["localization_variants"][0]["description"] = body["description"]
    body["localization_variants"][0]["title"] = body["title"]
    body["variant_groups"][0]["variants"][1]["value"] = {"text": "The river that made a valley: a history"}
    return body


def facts(candidate: PackagingCandidate, **changes: Any) -> PackagingFacts:
    values: dict[str, Any] = {
        "approved_master_id": "master",
        "approved_master_digest": DIGEST,
        "assessed_subject_digest": SUBJECT,
        "profile_id": UUID,
        "profile_revision": 1,
        "profile_digest": DIGEST,
        "duration_ms": 120000,
        "width": 1920,
        "height": 1080,
        "assets": {
            (a.role, a.variant_id): VerifiedAsset(a.content_digest, a.byte_size, a.media_type) for a in candidate.assets
        },
    }
    return PackagingFacts(**(values | changes))


def run(body: dict[str, Any], constraints: dict[str, Any] | None = None, **fact_changes: Any):
    constraints = constraints or all_rules_constraints()
    candidate = sealed(body, constraints)
    snapshot = q.PlatformConstraintSnapshot.model_validate(constraints)
    return check_package(candidate, snapshot, facts(candidate, **fact_changes))


def test_every_check_id_has_exactly_one_implementation() -> None:
    assert set(CHECKS) == set(q.PACKAGING_CHECK_CLASSES)


def test_a_clean_package_passes_every_declared_rule_deterministically() -> None:
    first = run(clean_body())
    assert first.failures == ()
    assert first.status is q.ObservationStatus.PASS
    assert len(first.evaluated_rule_ids) == len(q.PACKAGING_CHECK_CLASSES)
    assert run(clean_body()) == first


def _seed(defect: str, body: dict[str, Any]) -> dict[str, Any]:
    if defect == "title_too_long":
        body["title"] = "history " * 20
    elif defect == "title_term_missing":
        body["title"] = "A river story"
    elif defect == "description_short":
        body["description"] = "River history."
    elif defect == "description_term":
        body["description"] = "How the valley was shaped, in history, over ten thousand years."
    elif defect == "markdown":
        body["description"] = body["description"] + "\n- see **river** history"
    elif defect == "banned":
        body["description"] = body["description"] + " Click here for history of the river."
    elif defect == "tags_charset":
        body["tags"] = ["history", "river!"]
    elif defect == "duplicate_tag":
        body["tags"] = ["history", "History"]
    elif defect == "hashtag_form":
        body["hashtags"] = ["history"]
    elif defect == "chapter_not_zero":
        body["chapters"] = [{"start_ms": 5000, "title": "Source"}]
    elif defect == "chapter_short":
        body["chapters"] = [{"start_ms": 0, "title": "Source"}, {"start_ms": 5000, "title": "Delta"}]
    elif defect == "locale_missing":
        body["localization_variants"][0]["locale"] = "fr"
    elif defect == "undeclared_role":
        body["assets"].append(copy.deepcopy(body["assets"][0]) | {"role": "poster"})
    elif defect == "missing_required":
        body["assets"] = []
    elif defect == "media_type":
        body["assets"][0]["media_type"] = "video/webm"
    return body


@pytest.mark.parametrize(
    ("defect", "check_id", "code"),
    [
        ("title_too_long", "title.length", "TITLE_TOO_LONG"),
        ("title_term_missing", "title.terms", "TITLE_TERM_MISSING"),
        ("description_short", "description.length", "DESCRIPTION_TOO_SHORT"),
        ("description_term", "description.terms", "DESCRIPTION_TERM_MISSING"),
        ("markdown", "text.plain", "MARKDOWN_NOT_ALLOWED"),
        ("banned", "phrases.banned", "BANNED_PHRASE"),
        ("tags_charset", "tags.bounds", "TAG_CHARSET"),
        ("duplicate_tag", "tags.bounds", "DUPLICATE_TAG"),
        ("hashtag_form", "hashtags.bounds", "HASHTAG_FORM"),
        ("chapter_not_zero", "chapters.rules", "FIRST_CHAPTER_NOT_AT_ZERO"),
        ("chapter_short", "chapters.rules", "CHAPTER_TOO_SHORT"),
        ("locale_missing", "locales.coverage", "LOCALE_MISSING"),
        ("undeclared_role", "asset.integrity", "UNDECLARED_ROLE"),
        ("missing_required", "asset.required", "REQUIRED_ASSET_MISSING"),
        ("media_type", "asset.integrity", "MEDIA_TYPE_NOT_ALLOWED"),
    ],
)
def test_each_seeded_metadata_or_asset_defect_is_caught_by_its_rule(defect: str, check_id: str, code: str) -> None:
    result = run(_seed(defect, clean_body()))
    assert (check_id, code) in {(f.check_id, f.code) for f in result.failures}
    advisory = check_id == "phrases.banned"  # declared ADVISORY in the fixture snapshot
    assert result.status is (q.ObservationStatus.PASS if advisory else q.ObservationStatus.FAIL)


@pytest.mark.parametrize(
    ("changes", "check_id", "code"),
    [
        ({"duration_ms": 30000}, "duration.window", "DURATION_OUT_OF_WINDOW"),
        ({"width": 1080, "height": 1920}, "video.dimensions", "DIMENSIONS_MISMATCH"),
        ({"approved_master_digest": OTHER_DIGEST}, "binding.master", "MASTER_MISMATCH"),
        ({"profile_revision": 2}, "binding.profile", "PROFILE_MISMATCH"),
        ({"assessed_subject_digest": OTHER_DIGEST}, "closure.subject", "SUBJECT_MISMATCH"),
        ({"assets": {}}, "asset.integrity", "ASSET_NOT_VERIFIED"),
    ],
)
def test_facts_drift_is_caught_by_its_safety_or_platform_rule(changes: dict, check_id: str, code: str) -> None:
    result = run(clean_body(), **changes)
    assert (check_id, code) in {(f.check_id, f.code) for f in result.failures}


def test_verified_bytes_that_differ_from_the_declared_asset_are_drift() -> None:
    constraints = all_rules_constraints()
    candidate = sealed(clean_body(), constraints)
    drifted = facts(candidate, assets={("video", None): VerifiedAsset(OTHER_DIGEST, 1048576, "video/mp4")})
    result = check_package(candidate, q.PlatformConstraintSnapshot.model_validate(constraints), drifted)
    assert ("asset.integrity", "ASSET_BYTES_DRIFT") in {(f.check_id, f.code) for f in result.failures}


def test_a_tampered_closure_or_constraint_snapshot_is_refused() -> None:
    constraints = all_rules_constraints()
    candidate = sealed(clean_body(), constraints)
    snapshot = q.PlatformConstraintSnapshot.model_validate(constraints)
    forged = PackagingCandidate.model_validate(candidate.model_dump(mode="python") | {"title": "History, forged"})
    codes = {(f.check_id, f.code) for f in check_package(forged, snapshot, facts(forged)).failures}
    assert ("closure.content", "CLOSURE_MISMATCH") in codes
    other = copy.deepcopy(constraints)
    other["max_tags"] = 14
    codes = {
        (f.check_id, f.code)
        for f in check_package(candidate, q.PlatformConstraintSnapshot.model_validate(other), facts(candidate)).failures
    }
    assert ("closure.subject", "CONSTRAINT_SNAPSHOT_MISMATCH") in codes


def test_advisory_findings_never_fail_the_observation() -> None:
    result = run(_seed("banned", clean_body()), constraints_data())
    assert {(f.check_id, f.severity) for f in result.failures} == {("phrases.banned", "ADVISORY")}
    assert result.status is q.ObservationStatus.PASS


def test_slug_tolerant_terms_match_kalinga_seo_lint() -> None:
    constraints = all_rules_constraints()
    constraints["title_required_terms"] = ["Steve-Jobs"]
    body = clean_body()
    body["title"] = "steve jobs: a history"
    body["localization_variants"][0]["title"] = body["title"]
    body["variant_groups"] = []
    assert not {f.code for f in run(body, constraints).failures} & {"TITLE_TERM_MISSING"}


def _variant(field: str, variant_id: str, value: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "group_id": f"g-{field}",
        "field": field,
        "variants": [
            {
                "variant_id": variant_id,
                "value": value,
                "asset_role": None,
                "provenance": {"author_kind": "AGENT", "actor_id": "agent"},
            }
        ],
    }


def _with_variant(field: str, value: dict[str, Any] | None) -> dict[str, Any]:
    body = clean_body()
    body["variant_groups"] = [_variant(field, "v1", value)]
    return body


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("tags", {"tags": ["river", "River"]}, "DUPLICATE_TAG"),
        ("tags", {"tags": ["bad!"]}, "TAG_CHARSET"),
        ("tags", {"tags": ["history"] * 0}, "TAG_COUNT_OUT_OF_BOUNDS"),
        ("tags", {"tags": ["click here"]}, "BANNED_PHRASE"),
        ("chapters", {"chapters": [{"start_ms": 5000, "title": "Late"}]}, "FIRST_CHAPTER_NOT_AT_ZERO"),
        ("chapters", {"chapters": [{"start_ms": 0, "title": " "}]}, "CHAPTER_TITLE_EMPTY"),
        (
            "chapters",
            {"chapters": [{"start_ms": 0, "title": "A"}, {"start_ms": 500000, "title": "B"}]},
            "CHAPTER_TOO_SHORT",
        ),
        (
            "chapters",
            {"chapters": [{"start_ms": 0, "title": "A"}, {"start_ms": 0, "title": "B"}]},
            "CHAPTERS_NOT_ASCENDING",
        ),
        ("title", {"text": "history " * 20}, "TITLE_TOO_LONG"),
    ],
)
def test_every_alternative_is_checked_like_the_primary_value(field: str, value: dict[str, Any], code: str) -> None:
    result = run(_with_variant(field, value))
    assert code in {f.code for f in result.failures}
    assert any(f.locator.startswith(("variants[g-", "variant_groups[g-")) for f in result.failures if f.code == code)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tags", {"tags": ["river history", "valley"]}),
        ("chapters", {"chapters": [{"start_ms": 0, "title": "Source"}, {"start_ms": 60000, "title": "Delta"}]}),
        ("description", {"text": "The river carved the valley, a history of ten thousand years."}),
    ],
)
def test_clean_alternatives_pass(field: str, value: dict[str, Any]) -> None:
    assert run(_with_variant(field, value)).failures == ()


def test_duplicate_assets_and_a_presentation_only_tamper_are_refused() -> None:
    body = clean_body()
    body["assets"].append(copy.deepcopy(body["assets"][0]))
    assert "DUPLICATE_ASSET" in {f.code for f in run(body).failures}
    constraints = all_rules_constraints()
    candidate = sealed(clean_body(), constraints)
    forged = PackagingCandidate.model_validate(
        candidate.model_dump(mode="python")
        | {"assets": [candidate.assets[0].model_dump(mode="python") | {"source_ref": "elsewhere.mp4"}]}
    )
    codes = {
        (f.check_id, f.code)
        for f in check_package(forged, q.PlatformConstraintSnapshot.model_validate(constraints), facts(forged)).failures
    }
    assert codes == {("closure.presentation", "CLOSURE_MISMATCH")}


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("title", {"text": "history " * 20}, "TITLE_TOO_LONG"),
        ("tags", {"tags": ["bad!"]}, "TAG_CHARSET"),
        ("chapters", {"chapters": [{"start_ms": 5000, "title": "Late"}]}, "FIRST_CHAPTER_NOT_AT_ZERO"),
    ],
)
def test_alternatives_are_checked_even_without_a_variants_rule(field: str, value: dict[str, Any], code: str) -> None:
    constraints = all_rules_constraints()
    constraints["rules"] = [r for r in constraints["rules"] if r["check_id"] != "variants.bounds"]
    result = run(_with_variant(field, value), constraints)
    assert code in {f.code for f in result.failures}
