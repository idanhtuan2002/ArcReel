"""Shared fixtures for the M6 adaptation integration suite.

``adaptation_evidence_service``, ``fake_authority``, ``authority_service`` and
``evaluation_service`` were duplicated across three or more of
``test_adaptation_evidence_service.py``, ``test_map_approval.py``,
``test_waivers.py``, ``test_evaluation.py``, and ``test_screenplay_admission.py`` —
the same entity each time, not a name collision — so they live here once instead.
``FakeAuthority`` itself is not a fixture; it lives in ``_fakes.py`` and this module
only imports it to build fixtures from.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.adaptation_uow import adaptation_uow_factory
from r2.adaptation.authority import AdaptationAuthorityService
from r2.adaptation.evaluation import ProfileEvaluationService
from r2.adaptation.evidence import AdaptationEvidenceService
from tests.integration.r2.adaptation._fakes import FakeAuthority

type Factory = async_sessionmaker[AsyncSession]


@pytest.fixture
def adaptation_evidence_service(session_factory: Factory) -> AdaptationEvidenceService:
    return AdaptationEvidenceService(adaptation_uow_factory(session_factory))


@pytest.fixture
def evaluation_service(session_factory: Factory) -> ProfileEvaluationService:
    return ProfileEvaluationService(adaptation_uow_factory(session_factory))


@pytest.fixture
def fake_authority() -> FakeAuthority:
    return FakeAuthority()


@pytest.fixture
def authority_service(session_factory: Factory, fake_authority: FakeAuthority) -> AdaptationAuthorityService:
    return AdaptationAuthorityService(adaptation_uow_factory(session_factory), fake_authority)


@pytest.fixture
def denying_authority_service(session_factory: Factory) -> AdaptationAuthorityService:
    """A Human Showrunner authority that denies every request, for the "denial grants
    nothing" tests shared by ``decide_map`` and ``decide_waiver``."""
    return AdaptationAuthorityService(adaptation_uow_factory(session_factory), FakeAuthority(deny=True))
