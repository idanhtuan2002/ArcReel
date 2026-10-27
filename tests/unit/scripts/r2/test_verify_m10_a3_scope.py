"""A3-P scope accepts only its owner-specific source and explicit amendment."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.r2.verify_m10_a3_scope import acceptance_problems, migration_problems, registry_problems, source_problems

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("r2/quality/profiles.py", "from sqlalchemy import select"),
        ("r2/quality/profiles.py", "async def f(): return 1"),
        ("lib/db/repositories/quality.py", "from server.auth import get_current_interactive_user"),
        ("server/services/quality_profiles.py", "from server.auth import get_current_user"),
        (
            "server/services/quality_profile_custodian.py",
            "from server.services.governance_startup import verify_governance_public_startup",
        ),
        (
            "server/services/quality_profile_custodian.py",
            "from server.services.governance_grants import CurrentShowrunnerGrantReader",
        ),
        (
            "server/services/quality_profile_custodian.py",
            "from r2.adaptation.session_authority import SessionAuthenticatedShowrunnerAuthority",
        ),
        ("lib/db/models/quality.py", "from r2.production import authority"),
        ("lib/db/repositories/quality.py", "from r2.host_hardening.master_authority import resolve_m7_candidate_id"),
        ("server/services/quality_profiles.py", "import httpx"),
        ("server/services/quality_profiles.py", "import socket"),
        ("server/services/quality_profiles.py", "def f(): return __import__('socket')"),
        ("r2/quality/profiles.py", "def f(): return getattr(object, '__subclasses__')"),
        ("r2/quality/profiles.py", "print('effect')"),
        ("r2/quality/profiles.py", "value = factory()"),
        ("lib/db/models/quality.py", "from sqlalchemy import create_engine\nx = create_engine('postgresql://')"),
        ("server/services/quality_profiles.py", "from lib.db.models.quality import *"),
        ("r2/quality/profiles.py", "@factory()\ndef f(): pass"),
        ("r2/quality/profiles.py", "class Value[T: factory()]: pass"),
        (
            "lib/db/repositories/quality.py",
            "import sqlalchemy as sa\ndef f(): return sa.create_engine('postgresql://')",
        ),
        (
            "lib/db/repositories/quality.py",
            "from sqlalchemy import engine_from_config\ndef f(): return engine_from_config({})",
        ),
    ],
)
def test_owner_boundaries_refuse_runtime_and_authority_expansion(path: str, source: str) -> None:
    assert source_problems(path, source.encode()) == ("M10_NETWORK_SIDE_EFFECT_FORBIDDEN",)


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("r2/quality/profiles.py", "from r2.contracts.quality import QualityProfileRevision\ndef f(x): return x"),
        (
            "lib/db/models/quality.py",
            "from sqlalchemy.orm import Mapped, mapped_column\nfrom lib.db.base import Base\nclass Row(Base):\n    __tablename__ = 'example'\n    id: Mapped[str] = mapped_column(primary_key=True)",
        ),
        (
            "server/services/quality_profiles.py",
            "from lib.db.repositories.quality import QualityProfileRepository\nclass Service:\n    async def publish(self, request):\n        return await self.repository.replay(request)",
        ),
        (
            "server/services/quality_profile_custodian.py",
            "from server.auth import get_current_interactive_user\nfrom server.services.governance_startup import verify_governance_activated_startup\nasync def f(token): return await get_current_interactive_user(token)",
        ),
    ],
)
def test_owner_specific_declarations_and_runtime_methods_are_allowed(path: str, source: str) -> None:
    assert source_problems(path, source.encode()) == ()


def test_unknown_path_or_malformed_python_refuses() -> None:
    assert source_problems("server/routers/quality.py", b"") == ("POST_M8_BASE_SEAM_CHANGED",)
    assert source_problems("r2/quality/profiles.py", b"not valid :") == ("POST_M8_BASE_SEAM_CHANGED",)


def test_scope_amendment_and_open_original_gates_are_required() -> None:
    receipt = json.loads((ROOT / "docs/r2/evidence/R2_M10_A3_DESIGN_ACCEPTANCE.json").read_text())
    packet = json.loads((ROOT / "docs/r2/evidence/R2_M10_A3_PACKET_2026-10-27.json").read_text())
    assert acceptance_problems(receipt, packet) == ()
    for field, value in [
        ("scope_amendment", {}),
        ("scope_amendment_sha256", "0" * 64),
        ("original_a3_fully_accepted", True),
        ("readiness_runtime_accepted", True),
        ("runtime_activation_authorized", True),
        ("production_migration_authorized", True),
        ("provider_calls_authorized", True),
        ("status", "M10_A3_DESIGN_ACCEPTED"),
    ]:
        changed = copy.deepcopy(receipt)
        changed[field] = value
        assert acceptance_problems(changed, packet) == ("M10_DESIGN_NOT_ACCEPTED",)


def test_registry_allows_only_the_five_owned_exports() -> None:
    baseline = b'"""Models."""\nfrom lib.db.models.user import User\n__all__ = ["User"]\n'
    names = (
        "QualityProfileHeadModel",
        "QualityProfileRevisionModel",
        "ProfilePublicationAuthorizationModel",
        "QualityCommandModel",
        "QualityOutboxModel",
    )
    added = ("from lib.db.models.quality import " + ", ".join(names) + "\n").encode()
    current = baseline.replace(b'__all__ = ["User"]', ("__all__ = " + repr(["User", *names])).encode()) + added
    assert registry_problems(baseline, baseline, names) == ()
    assert registry_problems(baseline, current, names) == ()
    assert registry_problems(baseline, current + b"print('effect')\n", names) == ("POST_M8_BASE_SEAM_CHANGED",)
    assert registry_problems(baseline, current.replace(b"import User", b"import User as Other"), names) == (
        "POST_M8_BASE_SEAM_CHANGED",
    )
    assert registry_problems(baseline, current.replace(b"QualityOutboxModel", b"UnexpectedModel"), names) == (
        "POST_M8_BASE_SEAM_CHANGED",
    )


def test_migration_boundary_permits_only_the_exact_derived_addition() -> None:
    old = {"alembic/versions/old.py": b"revision='old'\ndown_revision=None\n"}
    target = "alembic/versions/new.py"
    new = {**old, target: b"revision='new'\ndown_revision='old'\n"}
    assert migration_problems(old, old, target_path=target, revision="new", predecessor="old") == ()
    assert migration_problems(old, new, target_path=target, revision="new", predecessor="old") == ()
    for changed in [
        {**old, target: b"revision='wrong'\ndown_revision='old'"},
        {**new, "alembic/versions/extra.py": b"revision='extra'\ndown_revision='new'"},
        {**new, "alembic/versions/old.py": b"revision='old'\ndown_revision='new'"},
    ]:
        assert migration_problems(old, changed, target_path=target, revision="new", predecessor="old") == (
            "M10_SCHEMA_CHANGE_REQUIRED",
        )


@pytest.mark.parametrize("variant", ["baseline", "qualified", "extra_edit", "wrong_mode"])
def test_test_compatibility_amendment_admits_only_exact_qualified_bytes(variant: str) -> None:
    from scripts.r2.verify_m10_a3_scope import compatibility_problems

    baseline = b"immutable historical test body"
    qualified = b"qualified historical test body"
    row = {
        "baseline_sha256": hashlib.sha256(baseline).hexdigest(),
        "proposed_sha256": hashlib.sha256(qualified).hexdigest(),
    }
    current = (
        baseline if variant == "baseline" else qualified + (b"\n# extra edit\n" if variant == "extra_edit" else b"")
    )
    mode = "100755" if variant == "wrong_mode" else "100644"
    assert compatibility_problems(row, current, mode=mode) == (
        () if variant in {"baseline", "qualified"} else ("POST_M8_BASE_SEAM_CHANGED",)
    )
