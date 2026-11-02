"""script_revision：剧本内容版本不随媒体生成回写的状态变化。"""

from __future__ import annotations

import json

from server.production_run.owner_support import script_revision


def _script(**segment_overrides) -> dict:
    segment = {"segment_id": "E1S01", "novel_text": "Nam nhặt chai.", "generated_assets": {"status": "pending"}}
    return {
        "title": "t",
        "segments": [{**segment, **segment_overrides}],
        "metadata": {"updated_at": "2026-11-02T00:00:00Z", "script_plan_revision": "r1"},
    }


def test_media_state_written_back_keeps_the_revision(tmp_path):
    path = tmp_path / "episode_1.json"
    path.write_text(json.dumps(_script()), encoding="utf-8")
    before = script_revision(path)

    after_media = _script(generated_assets={"status": "storyboard_ready", "storyboard_image": "storyboards/a.png"})
    after_media["metadata"]["updated_at"] = "2026-11-02T01:00:00Z"
    path.write_text(json.dumps(after_media), encoding="utf-8")

    assert script_revision(path) == before


def test_a_content_change_changes_the_revision(tmp_path):
    path = tmp_path / "episode_1.json"
    path.write_text(json.dumps(_script()), encoding="utf-8")
    before = script_revision(path)

    path.write_text(json.dumps(_script(novel_text="Nam đánh rơi chai.")), encoding="utf-8")

    assert script_revision(path) != before


def test_a_missing_script_has_no_revision(tmp_path):
    assert script_revision(tmp_path / "missing.json") is None
