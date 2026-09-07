from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from r2.contracts import Provenance, ProvenanceActor


def test_provenance_requires_timezone_aware_created_at():
    item = Provenance(
        created_by=ProvenanceActor.AGENT,
        source_refs=["source:b", "source:a", "source:b"],
        created_at=datetime(2026, 9, 6, 10, 0, tzinfo=UTC),
        tool_or_adapter="r2-test",
        parent_revision_refs=["rev:2", "rev:1", "rev:2"],
    )
    assert item.source_refs == ["source:a", "source:b"]
    assert item.parent_revision_refs == ["rev:1", "rev:2"]

    with pytest.raises(ValidationError):
        Provenance(
            created_by=ProvenanceActor.SYSTEM,
            source_refs=[],
            created_at=datetime(2026, 9, 6, 10, 0),
        )
