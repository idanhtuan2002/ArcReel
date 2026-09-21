"""M3 real-media closure Task 3: real per-shot rendering (replaces the old
solid-color FFmpeg stub). ``execution_variant`` (a past parameter used only
to vary the old stub's arbitrary color seed) is gone -- real content-driven
rendering has nothing analogous to differentiate: the same shot, method, and
content always render the same real bytes (verified this session), so there
is no "variant" left to parameterize.
"""

from __future__ import annotations

from pathlib import Path

from r2.contracts.enums import ProductionMethod, ReadinessState

from .preparation import GoldenAPreparedShot
from .remotion_engine import render_cut
from .render_plan import RenderedCutAsset
from .render_projection import project_shot_to_cut


class GoldenALocalProducer:
    def produce(
        self,
        prepared: GoldenAPreparedShot,
        *,
        work_dir: Path,
        display_text: str | None = None,
    ) -> RenderedCutAsset:
        if prepared.readiness.state is not ReadinessState.READY:
            raise ValueError(f"{prepared.shot.id} is BLOCKED and cannot be produced")

        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        output = work_dir / f"{prepared.shot.id}.mp4"

        bound_source: Path | None = None
        if prepared.method.method is ProductionMethod.REUSE:
            if not prepared.bindings:
                raise ValueError("REUSE requires a resolved binding")
            bound_source = Path(prepared.bindings[0].production_ref)

        cut = project_shot_to_cut(
            prepared.shot,
            method=prepared.method.method,
            bound_source=bound_source,
            display_text=display_text,
        )
        return render_cut(cut, output_path=output)


__all__ = ["GoldenALocalProducer"]
