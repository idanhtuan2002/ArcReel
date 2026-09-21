"""Pure shot-to-cut projection (spec section 5): turns one ``AnyShotSpec`` plus
its method-specific content into one ``RenderCut``, fed to a real Remotion
render as the sole segment of that shot's own file (mirroring the existing
one-file-per-shot architecture: ``GoldenAComposer.compose`` concatenates
whatever ``GoldenALocalProducer.produce`` writes per shot, unchanged by this
module).

Every currently-defined ``ProductionMethod`` this closure does not implement
raises ``NotImplementedError`` explicitly -- the previous solid-color stub's
defect was exactly this: silently folding every method into one code path
instead of failing loud for a method with no real content source.
"""

from __future__ import annotations

from pathlib import Path

from r2.contracts import AnyShotSpec
from r2.contracts.enums import ProductionMethod

from .render_plan import RenderCut

_IMPLEMENTED_METHODS = frozenset({ProductionMethod.REUSE, ProductionMethod.DETERMINISTIC})


class UnimplementedRenderMethodError(NotImplementedError):
    """This closure has no real content source for the given method yet."""


def project_shot_to_cut(
    shot: AnyShotSpec,
    *,
    method: ProductionMethod,
    bound_source: Path | None,
    display_text: str | None,
) -> RenderCut:
    if method not in _IMPLEMENTED_METHODS:
        raise UnimplementedRenderMethodError(
            f"{method.value} has no real render content source in this closure "
            "(spec section 1: only REUSE/DETERMINISTIC/COMPOSITE are in scope)"
        )

    if method is ProductionMethod.REUSE:
        if bound_source is None:
            raise ValueError(f"{shot.id}: REUSE requires a resolved bound source")
        return RenderCut(
            cut_id=shot.id,
            in_seconds=0.0,
            out_seconds=float(shot.target_duration),
            kind="video_passthrough",
            source_path=bound_source,
        )

    # DETERMINISTIC
    if display_text is None:
        raise ValueError(f"{shot.id}: DETERMINISTIC requires real display text")
    return RenderCut(
        cut_id=shot.id,
        in_seconds=0.0,
        out_seconds=float(shot.target_duration),
        kind="text_card",
        text=display_text,
    )


__all__ = ["UnimplementedRenderMethodError", "project_shot_to_cut"]
