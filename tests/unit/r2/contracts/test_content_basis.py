import pytest
from pydantic import ValidationError

from r2.contracts import ContentBasis, ContentBasisType


def test_content_basis_requires_non_empty_refs_and_deduplicates_deterministically():
    basis = ContentBasis(
        basis_type=ContentBasisType.NARRATIVE,
        basis_version="canon-v7",
        refs=["scene:2", "scene:1", "scene:2"],
    )
    assert basis.refs == ["scene:1", "scene:2"]

    with pytest.raises(ValidationError):
        ContentBasis(
            basis_type=ContentBasisType.NARRATIVE,
            basis_version="canon-v7",
            refs=[],
        )


def test_content_basis_requires_non_empty_basis_version():
    with pytest.raises(ValidationError):
        ContentBasis(
            basis_type=ContentBasisType.FACTUAL,
            basis_version="",
            refs=["claim:1"],
        )
