"""Compiler-only read protocols and a deterministic token counter.

Every port is exact and read-only: none exposes list-latest, search-live, insert,
update, delete, flush, commit, session, or repository access. The compiler receives
no authority repository, write port, unit-of-work factory, provider, or donor memory.
"""

from __future__ import annotations

from typing import Protocol

from r2.contracts import NarrativePlan, SceneContract
from r2.contracts.narrative_context import NarrativeSourceDescriptor, RetrievalSnapshot
from r2.narrative.canon_state import ResolvedCanonView


class CanonVersionReader(Protocol):
    async def get_exact(
        self, *, branch_id: str, canon_version_id: str, project_name: str, user_id: str
    ) -> ResolvedCanonView | None: ...


class NarrativePlanReader(Protocol):
    async def get_exact_plan(
        self, *, plan_id: str, plan_version: int, project_name: str, user_id: str
    ) -> NarrativePlan | None: ...

    async def get_exact_scene(
        self,
        *,
        plan_id: str,
        plan_version: int,
        scene_contract_id: str,
        scene_contract_version: int,
        project_name: str,
        user_id: str,
    ) -> SceneContract | None: ...


class CreativePolicySegment(Protocol):
    @property
    def source_ref(self) -> str: ...

    @property
    def content(self) -> str: ...


class CreativePolicyReader(Protocol):
    async def get_exact(
        self, *, policy_ref: str, policy_version: str, project_name: str, user_id: str
    ) -> tuple[CreativePolicySegment, ...] | None: ...


class AcceptedNarrativeRecord(Protocol):
    @property
    def accepted_narrative_ref(self) -> str: ...

    @property
    def content(self) -> str: ...

    @property
    def descriptor(self) -> NarrativeSourceDescriptor: ...


class AcceptedNarrativeReader(Protocol):
    async def get_exact(
        self, *, accepted_narrative_ref: str, project_name: str, user_id: str
    ) -> AcceptedNarrativeRecord | None: ...


class RetrievalSnapshotReader(Protocol):
    async def get_exact(self, *, snapshot_ref: str, project_name: str, user_id: str) -> RetrievalSnapshot | None: ...


class TokenCounter(Protocol):
    @property
    def version(self) -> str: ...

    def count(self, content: str) -> int: ...
