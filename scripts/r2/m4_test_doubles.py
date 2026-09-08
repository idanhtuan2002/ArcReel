"""Verification-only Director and execution doubles for the D09 golden fixture.

These are NOT runtime authority and never live in ``r2/production_intelligence``.
They sit at the external boundary so real M4 policy/resolution/compiler code runs
against them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from r2.contracts import DirectorKind, ProviderRequest, SceneSpec, ShotSpec
from r2.production_intelligence.director import DirectorRouteUnavailable


class DirectorDoubleMode(StrEnum):
    SUCCEED = "SUCCEED"
    ROUTE_UNAVAILABLE = "ROUTE_UNAVAILABLE"
    MALFORMED = "MALFORMED"


@dataclass(frozen=True)
class RawDirection:
    scenes: list[SceneSpec]
    shots: list[ShotSpec]


class FixtureDirectorAdapter:
    """Returns pre-built normalized specs for one shot; can also simulate a
    route-unavailable or a malformed/partial output."""

    def __init__(
        self,
        *,
        director_kind: DirectorKind,
        scenes: list[SceneSpec],
        shots: list[ShotSpec],
        mode: DirectorDoubleMode = DirectorDoubleMode.SUCCEED,
    ) -> None:
        self.director_kind = director_kind
        self._scenes = scenes
        self._shots = shots
        self._mode = mode

    def direct(self, artifact: object) -> object:
        if self._mode is DirectorDoubleMode.ROUTE_UNAVAILABLE:
            raise DirectorRouteUnavailable(f"{self.director_kind.value} donor unavailable")
        if self._mode is DirectorDoubleMode.MALFORMED:
            orphan = self._shots[0].model_copy(update={"scene_id": "SC-DOES-NOT-EXIST"})
            return RawDirection(scenes=list(self._scenes), shots=[orphan])
        return RawDirection(scenes=list(self._scenes), shots=list(self._shots))


class ExecutionTier(StrEnum):
    LOCAL_TIER_DOUBLE = "LOCAL_TIER_DOUBLE"
    CHEAP_CLOUD_TIER_DOUBLE = "CHEAP_CLOUD_TIER_DOUBLE"
    PREMIUM_CLOUD_TIER_DOUBLE = "PREMIUM_CLOUD_TIER_DOUBLE"


class ExecutionMode(StrEnum):
    SUCCEED = "SUCCEED"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    UNAVAILABLE = "UNAVAILABLE"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    CHARGE_THEN_FAIL = "CHARGE_THEN_FAIL"
    CANCEL = "CANCEL"


_PAID_TIERS = {ExecutionTier.CHEAP_CLOUD_TIER_DOUBLE, ExecutionTier.PREMIUM_CLOUD_TIER_DOUBLE}


@dataclass(frozen=True)
class DoubleResult:
    succeeded: bool
    output_ref: str | None
    cost_record_ref: str | None
    error_code: str | None


class ControlledExecutionDouble:
    """Simulates only execution-policy characteristics — never visual quality."""

    def __init__(self, *, tier: ExecutionTier, mode: ExecutionMode = ExecutionMode.SUCCEED) -> None:
        self.tier = tier
        self.mode = mode
        self.calls = 0

    def run(self, request: ProviderRequest) -> DoubleResult:
        self.calls += 1
        cost_ref = f"COST:{request.id}:{self.tier.value}" if self.tier in _PAID_TIERS else None

        if self.mode is ExecutionMode.SUCCEED:
            return DoubleResult(True, f"asset:{request.id}", cost_ref, None)
        if self.mode is ExecutionMode.TIMEOUT:
            raise TimeoutError(f"{self.tier.value} timed out")
        if self.mode is ExecutionMode.RATE_LIMIT:
            raise ConnectionError(f"{self.tier.value} rate limited")
        if self.mode is ExecutionMode.UNAVAILABLE:
            raise ConnectionError(f"{self.tier.value} unavailable")
        if self.mode is ExecutionMode.MALFORMED_RESPONSE:
            return DoubleResult(False, None, cost_ref, "MALFORMED_RESPONSE")
        if self.mode is ExecutionMode.CHARGE_THEN_FAIL:
            # The provider charged before failing — cost stays attributable.
            return DoubleResult(False, None, cost_ref or f"COST:{request.id}:charged", "CHARGE_THEN_FAIL")
        return DoubleResult(False, None, None, "CANCELLED")
