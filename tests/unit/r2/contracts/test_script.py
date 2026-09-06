import pytest
from pydantic import ValidationError
from r2.contracts import ContentBasis, ContentBasisType, ScriptArtifact, ScriptSection


def approval_value():
    ann = ScriptArtifact.model_fields["approval_status"].annotation
    try:
        values = [m.value for m in ann]
    except TypeError:
        values = []
    for value in ("APPROVED", "PROPOSED", "DRAFT", "REVIEW_REQUIRED"):
        if value in values:
            return value
    return "DRAFT"


def factual_basis():
    return ContentBasis(basis_type=ContentBasisType.FACTUAL, basis_version="golden-a-v1",
                        refs=["research:RP-1", "claim:CLAIM-001"])


def test_script_requires_factual_basis():
    basis = ContentBasis(basis_type=ContentBasisType.NARRATIVE, basis_version="canon-v1", refs=["canon:C1"])
    with pytest.raises(ValidationError):
        ScriptArtifact(id="SCRIPT-1", version=1, content_basis=basis, sections=[], participants=[],
                       timing_intent="60-90s explainer", creative_constraints=["factual"],
                       approval_status=approval_value())


def test_script_claim_ref_must_be_declared_in_basis():
    with pytest.raises(ValidationError):
        ScriptArtifact(id="SCRIPT-1", version=1, content_basis=factual_basis(),
                       sections=[ScriptSection(id="SEC-01", text="x", claim_refs=["CLAIM-999"],
                                               target_duration_seconds=20.0)],
                       participants=[], timing_intent="60-90s explainer", creative_constraints=["factual"],
                       approval_status=approval_value())


def test_script_accepts_declared_claim_ref():
    script = ScriptArtifact(id="SCRIPT-1", version=1, content_basis=factual_basis(),
                            sections=[ScriptSection(id="SEC-01", text="x", claim_refs=["CLAIM-001"],
                                                    target_duration_seconds=20.0)],
                            participants=[], timing_intent="60-90s explainer", creative_constraints=["factual"],
                            approval_status=approval_value())
    assert script.sections[0].claim_refs == ["CLAIM-001"]
