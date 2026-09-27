# R2 M7 H6 V1-02: grid reference states at the capture boundary

Date: 2026-09-27. Source HEAD before this note: `88a433e0`.
Status: bounded source research; no capture-admission rule is approved.

## Observed transitions

`GridGeneration.create()` starts `pending` with a null composite path and a
frame chain whose paths are null (`lib/grid/models.py:219-254,67-113`). Normal
worker completion writes the composite path and `completed` together while
clearing `split_at` (`server/services/generation_tasks.py:3137-3150,3347-3376`).
Explicit split assigns paths only to selected frames and sets `split_at`
(`server/services/grid_split.py:461-475`); a missing or superseded scene can
leave another frame without a path. Thus `completed` does not mean every frame
has a path (`lib/grid/models.py:129-139`).

Regeneration sets an existing record back to `pending` without clearing its
composite or frame paths (`server/routers/grids.py:328-335`); worker failure
sets `failed` after reloading the durable record, so old path fields may remain
(`server/services/generation_tasks.py:3419-3428`). Manual replacement sets a
new composite path and clears `split_at` but leaves old frame paths
(`lib/grid/models.py:203-217`). Legacy `splitting` reads as `completed` with
no split time; legacy `completed` lacking `split_at` reads as already split
(`lib/grid/models.py:169-200`). Those read-time projections must not overwrite
the raw record during capture.

| Raw state/field | Supported inference for the classifier | Open approval question |
| --- | --- | --- |
| `pending`/`generating`, composite path absent | A newly created grid may have no composite yet. | The V1-01 task/attempt state must prove whether active work is fenced or disposed before capture. |
| `pending`/`generating`/`failed`, composite path present | The path may point to a retained earlier composite. | Decide whether a missing earlier composite is a required-file error or an inspected stale-reference disposition; status alone cannot discard the path. |
| `completed` or raw legacy `splitting`, composite path present | Normal completion and the legacy intermediate state claim a composite. | Define the exact required-byte and version/Manifest cross-check; a missing file cannot be accepted by treating `splitting` as pending. |
| `split_at` non-null, individual frame path absent | Split can skip a scene that is no longer in the script. | Do not demand every frame path solely because `split_at` is present; reconcile selected frame assignments and script authority. |
| `split_at` null, individual frame path present | The path can be left from an earlier split after composite replacement. | Define whether to retain/check that declared reference as historical or prove it superseded; do not silently ignore it. |

The existing pure `inspect_grid_references()` returns raw status, `split_at`
presence and each declared path, including absent versus null; it does not
open files, evaluate currency or grant H6 capture authority
(`r2/host_hardening/grid_reference_probe.py:1-5,97-166`). This table is a
source-backed counterexample set for the required release-pinned classifier,
not a complete state machine. The final rule needs a fenced corpus covering
regeneration, failure, manual replacement, legacy records, missing composite
and skipped frames, plus the matching Task/attempt and Manifest states.
