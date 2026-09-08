"""Pure Canon content schema transitions.

A v1 version stays verifiable under v1; it is never rewritten in place. The first
v2 delta over a v1 base performs a deterministic upgrade that only adds empty
epistemic/temporal maps and takes no wall-clock input.
"""

from __future__ import annotations

from r2.contracts import CANON_SCHEMA_V1, CANON_SCHEMA_V2, CanonContent

from .errors import NarrativeSchemaVersionError

_KNOWN_SCHEMAS: frozenset[str] = frozenset({CANON_SCHEMA_V1, CANON_SCHEMA_V2})

# ``None`` means genesis (no prior version). The base schema is always supplied by the
# caller; it is never inferred from whether the v2 maps happen to be empty.
_LEGAL_TRANSITIONS: frozenset[tuple[str | None, str]] = frozenset(
    {
        (None, CANON_SCHEMA_V1),
        (None, CANON_SCHEMA_V2),
        (CANON_SCHEMA_V1, CANON_SCHEMA_V1),
        (CANON_SCHEMA_V1, CANON_SCHEMA_V2),
        (CANON_SCHEMA_V2, CANON_SCHEMA_V2),
    }
)


def require_schema_transition(*, from_schema: str | None, to_schema: str) -> None:
    """Raise ``NarrativeSchemaVersionError`` unless ``from_schema -> to_schema`` is legal."""
    if from_schema is not None and from_schema not in _KNOWN_SCHEMAS:
        raise NarrativeSchemaVersionError(f"unknown base Canon schema selector {from_schema!r}")
    if to_schema not in _KNOWN_SCHEMAS:
        raise NarrativeSchemaVersionError(f"unknown target Canon schema selector {to_schema!r}")
    if (from_schema, to_schema) not in _LEGAL_TRANSITIONS:
        raise NarrativeSchemaVersionError(f"illegal Canon schema transition {from_schema!r} -> {to_schema!r}")


def upgrade_canon_content(content: CanonContent, *, from_schema: str | None, to_schema: str) -> CanonContent:
    """Return ``content`` shaped for ``to_schema`` after proving the transition is legal.

    The upgrade never rewrites Entity/Fact/Event bytes. ``CanonContent`` already carries
    empty v2 maps by default, so a legal transition needs no structural change; the value
    of this seam is the explicit, wall-clock-free legality gate.
    """
    require_schema_transition(from_schema=from_schema, to_schema=to_schema)
    return content
