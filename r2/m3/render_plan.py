"""Real-render contracts for M3's closure of F1 (spec section 4,
docs/superpowers/specs/2026-09-21-r2-m3-real-media-closure-design.md).

``RenderedCutAsset`` is deliberately shaped like the existing
``LocalProducedAsset``/``GoldenACompositeAsset`` (same field names/types
where they overlap) so ``GoldenAComposer.compose`` -- which only ever reads
``.path`` off whatever produced a shot's file -- needs no change at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

from r2.contracts.enums import ProductionMethod


@dataclass(frozen=True)
class RenderCut:
    cut_id: str
    in_seconds: float
    out_seconds: float
    kind: Literal["video_passthrough", "text_card", "stat_card"]
    source_path: Path | None = None
    text: str | None = None
    subtitle: str | None = None
    background_color: str | None = None


@dataclass(frozen=True)
class RenderPlan:
    plan_id: str
    cuts: tuple[RenderCut, ...]
    width: int = 1920
    height: int = 1080
    fps: int = 30


@dataclass(frozen=True)
class RenderedCutAsset:
    target_ref: str
    method: ProductionMethod
    path: Path
    sha256: str
    duration_seconds: float
    execution_fingerprint: str
    tool: Literal["remotion"]
    tool_version: str
    wall_time_seconds: float
    external_provider_cost: Decimal
    source_master_refs: tuple[str, ...]


__all__ = ["RenderCut", "RenderPlan", "RenderedCutAsset"]
