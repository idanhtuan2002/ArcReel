"""Run one DramaClaw film: `python -m assembly.connector --story story.txt --title "…" --spine narrated`.

Resume a stopped run with `--state <state file>` (the pipeline status is the source of truth; the state file keeps
the project id, casting and downloaded finals).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from assembly.connector import setup
from assembly.connector.dramaclaw_tools import DramaClawTools
from assembly.connector.film import CheckpointReached, FilmRun, RunState, RunStopped

DATA = Path.home() / "assembly-data/runs"

# Project settings (ASSEMBLY_PLAN D17 vertical, D27 local Wan, D7 Seedream for sketches/renders).
SETTINGS = {
    "aspect_ratio": "9:16",
    "visual_style": "realistic",
    "narration_style": "third_person",
    "ethnicity": "Vietnamese",
    "rhythm": "medium",
    "video_backend": "newapi_Wan22-5B-local",
    "video_resolution": "720x1280",
    "add_subtitles": True,
    "sketch_image_selection": "newapi_gpt_image2",
    "render_image_selection": "newapi_gpt_image2",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--story", type=Path)
    parser.add_argument("--title")
    parser.add_argument("--spine", choices=["narrated", "drama"], default="narrated")
    parser.add_argument("--region", choices=["north", "central", "south"], default="north")
    parser.add_argument("--state", type=Path)
    parser.add_argument("--mode", choices=["auto", "step"], default="auto")
    parser.add_argument("--approve", action="append", default=[], help="checkpoint key to approve, e.g. CP1")
    args = parser.parse_args()

    if args.state:
        state_path = args.state
        state = RunState.load(state_path)
        state.approved.extend(a for a in args.approve if a not in state.approved)
        state.save(state_path)
        tools = DramaClawTools(state.project_id)
    else:
        if not args.story or not args.title:
            parser.error("--story and --title are required for a new run")
        project_id = setup.create_project(args.title)
        state_path = DATA / f"{project_id}.json"
        state = RunState(project_id=project_id, title=args.title, spine=args.spine, mode=args.mode)
        state.save(state_path)
        tools = DramaClawTools(project_id)
        print(f"project {project_id}; state {state_path}", flush=True)
        setup.prepare_project(tools, args.story, spine=args.spine, settings=SETTINGS)

    run = FilmRun(
        tools,
        state,
        state_path,
        out_dir=DATA / "films",
        cast_voices=lambda r: setup.cast_voices(r, story_region=args.region),
        fill_face_prompts=setup.fill_face_prompts,
        log=lambda line: print(line, flush=True),
    )
    try:
        run.run()
    except CheckpointReached as point:
        print(f"CHECKPOINT: {point}", flush=True)
        return 3
    except RunStopped as stop:
        print(f"STOPPED: {stop}", flush=True)
        return 2
    print(f"DONE: {state.finals}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
