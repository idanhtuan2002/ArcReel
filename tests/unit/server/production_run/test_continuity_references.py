"""Which sheet the continuity judge sees for a character named in a shot, including a derivative state."""

from __future__ import annotations

from pathlib import Path

from server.production_run.continuity_pass import shot_for


def test_a_derivative_state_is_judged_against_its_own_sheet_and_combined_description(tmp_path: Path):
    (tmp_path / "characters" / "derivatives" / "Lan").mkdir(parents=True)
    (tmp_path / "characters" / "Lan.png").write_bytes(b"base")
    (tmp_path / "characters" / "derivatives" / "Lan" / "cuoi.png").write_bytes(b"wedding")
    project = {
        "characters": {
            "Lan": {
                "description": "Cô gái 19 tuổi.",
                "character_sheet": "characters/Lan.png",
                "derivatives": {
                    "áo cưới": {
                        "description": "mặc áo dài cưới trắng",
                        "character_sheet": "characters/derivatives/Lan/cuoi.png",
                    }
                },
            }
        }
    }
    script = {
        "content_mode": "narration",
        "segments": [
            {"segment_id": "E1S01", "characters_in_segment": ["Lan/áo cưới"], "image_prompt": {"scene": "lễ cưới"}},
            {"segment_id": "E1S02", "characters_in_segment": ["Lan"], "image_prompt": {"scene": "về làng"}},
        ],
    }

    wedding = shot_for(project, tmp_path, script, "E1S01")
    plain = shot_for(project, tmp_path, script, "E1S02")

    assert wedding is not None
    assert plain is not None
    assert [(label, data) for label, data in wedding.references] == [
        ("character: Lan/áo cưới - Cô gái 19 tuổi. mặc áo dài cưới trắng", b"wedding")
    ]
    assert [data for _label, data in plain.references] == [b"base"]
