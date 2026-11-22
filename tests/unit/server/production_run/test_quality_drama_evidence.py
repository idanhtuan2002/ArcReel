"""A drama final is reviewed against its spoken lines: bare lines for the subtitle check, lines with their speakers for
the review prompt; a narration keeps its segments."""

from __future__ import annotations

import json
from pathlib import Path

from server.production_run.quality_adapter import QualityAdapter

DRAMA = {
    "scenes": [
        {
            "image_prompt": {"composition": {"shot_type": "Medium Shot"}},
            "utterances": [
                {"kind": "dialogue", "speaker": "Hải", "text": "Bố sáu mươi tám rồi."},
                {"kind": "dialogue", "speaker": "Ông Ba", "text": "Con nói phải rồi."},
            ],
        },
        {
            "image_prompt": {"composition": {"shot_type": "Close-up"}},
            "utterances": [{"kind": "voiceover", "speaker": None, "text": "Bến sông vắng lặng."}],
        },
    ]
}


class _Projects:
    def __init__(self, root: Path, script: dict) -> None:
        self.root = root
        (root / "scripts").mkdir(parents=True)
        (root / "scripts" / "episode_2.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")

    def load_project(self, name: str) -> dict:
        return {"episodes": [{"episode": 2, "script_file": "scripts/episode_2.json"}], "characters": {}}

    def get_project_path(self, name: str) -> Path:
        return self.root


def _adapter(tmp_path: Path, script: dict) -> QualityAdapter:
    adapter = QualityAdapter.__new__(QualityAdapter)
    adapter._projects = _Projects(tmp_path, script)
    return adapter


def test_a_drama_is_reviewed_on_its_spoken_lines(tmp_path: Path):
    adapter = _adapter(tmp_path, DRAMA)

    assert adapter._narration("p", 2) == "Bố sáu mươi tám rồi.\nCon nói phải rồi.\nBến sông vắng lặng."
    assert adapter._dialogue("p", 2) == ("Hải: Bố sáu mươi tám rồi.\nÔng Ba: Con nói phải rồi.\nBến sông vắng lặng.")
    assert adapter._shot_types("p", 2) == ("Medium Shot", "Close-up")


def test_a_narration_keeps_its_segments_and_has_no_dialogue(tmp_path: Path):
    adapter = _adapter(tmp_path, {"segments": [{"novel_text": "Ông Ba không trả lời."}]})

    assert adapter._narration("p", 2) == "Ông Ba không trả lời."
    assert adapter._dialogue("p", 2) is None
