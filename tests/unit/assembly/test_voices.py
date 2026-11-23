"""Vietnamese voice casting for DramaClaw: VieNeu catalog, sample registry, casting rule (ASSEMBLY_PLAN D9, D18)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from assembly.voices import registry
from assembly.voices.casting import CastMember, cast, normalize_gender
from assembly.voices.catalog import Voice, load_voices


def _presets(tmp_path: Path) -> Path:
    data = {
        "presets": {
            "Thanh Bình": {
                "description": "Nam · Bắc · Phong cách kể chuyện",
                "gender": "male",
                "region": "Bắc",
                "style": "doc_truyen",
            },
            "Phạm Tuyên": {"description": "Nam · Bắc · Phong cách tự nhiên", "gender": "male", "style": "tu_nhien"},
            "Thái Sơn": {
                "description": "Nam · Nam · Phong cách kể chuyện",
                "gender": "male",
                "region": "Nam",
                "style": "doc_truyen",
            },
            "Ngọc Huyền": {
                "description": "Nữ · Bắc · Giọng đọc tự nhiên",
                "gender": "female",
                "region": "Bắc",
                "style": "tu_nhien",
            },
            "Mỹ Duyên": {
                "description": "Nữ · Nam · Phong cách đọc truyện",
                "gender": "female",
                "region": "Nam",
                "style": "doc_truyen",
            },
        }
    }
    path = tmp_path / "voices.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_the_catalog_reads_region_from_the_description_when_the_field_is_missing(tmp_path: Path) -> None:
    voices = {v.name: v for v in load_voices(_presets(tmp_path))}
    assert voices["Phạm Tuyên"] == Voice("Phạm Tuyên", "male", "north", "tu_nhien")
    assert voices["Thái Sơn"].region == "south"


def test_characters_get_distinct_presets_of_their_gender_from_the_story_region_first(tmp_path: Path) -> None:
    voices = load_voices(_presets(tmp_path))
    chosen = cast(
        [CastMember("ông Khang", "male"), CastMember("Vy", "女"), CastMember("Tài", "nam", region="south")],
        voices,
        story_region="north",
    )
    assert chosen["__narrator__"] == "Thanh Bình"  # story-reading style, northern
    assert chosen["ông Khang"] == "Phạm Tuyên"  # northern male not used by the narrator
    assert chosen["Vy"] == "Ngọc Huyền"
    assert chosen["Tài"] == "Thái Sơn"  # marked southern


def test_presets_are_reused_in_order_once_all_are_taken(tmp_path: Path) -> None:
    voices = load_voices(_presets(tmp_path))
    chosen = cast([CastMember(f"F{i}", "female") for i in range(3)], voices, story_region="north")
    assert [chosen["F0"], chosen["F1"]] == ["Ngọc Huyền", "Mỹ Duyên"]
    assert chosen["F2"] == "Ngọc Huyền"


def test_gender_words_from_donors_are_understood() -> None:
    assert normalize_gender("女") == "female"
    assert normalize_gender("Nữ") == "female"
    assert normalize_gender("male") == "male"
    assert normalize_gender("") == "male"


def test_the_registry_maps_a_sample_to_its_preset(tmp_path: Path) -> None:
    path = tmp_path / "reg.json"
    digest = registry.register(b"sample-bytes", "Ngọc Huyền", path)
    assert registry.load(path) == {digest: "Ngọc Huyền"}
    assert digest == registry.sample_digest(b"sample-bytes")


def test_casting_without_a_preset_of_the_gender_fails(tmp_path: Path) -> None:
    voices = [v for v in load_voices(_presets(tmp_path)) if v.gender == "male"]
    with pytest.raises(ValueError, match="female"):
        cast([CastMember("Vy", "female")], voices)
