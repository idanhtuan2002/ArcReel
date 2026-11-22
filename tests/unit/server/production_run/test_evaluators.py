from __future__ import annotations

import dataclasses
import json
import math
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from r2.contracts.automation import ModelRoute
from server.production_run.evaluators import (
    CONTEXT_TOKENS,
    FINDING_CHARS,
    FRAME_COUNT,
    PROBABILITIES,
    QUESTIONS,
    VERDICT_FINDINGS,
    VERDICT_TOKENS,
    WATCH,
    FinalEvidence,
    OllamaReviewer,
    cue_at,
    first_token_probability,
    frame_answer_findings,
    frame_times,
    illustration_findings,
    prompt_digest,
    review_method,
    review_prompts,
    segment_keys,
    upright_letter,
    yes_no,
)
from server.production_run.quality_adapter import final_segments

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

ROUTE = ModelRoute(
    role="reviewer_a",
    provider_id="custom-1",
    model_id="gemma3:4b",
    model_identity="ollama/gemma3:4b",
    config_digest="sha256:" + "1" * 64,
    local=True,
    paid=False,
    currency="USD",
    max_cost_per_call=None,
)
ANSWER = {
    "language": "vi",
    "scores": {"story": 4, "visual": 5, "audio": 4, "continuity": 4, "pacing": 4},
    "findings": [{"code": "soft_focus", "severity": "MINOR", "repair_stage": None, "detail": "cảnh 2 hơi mờ"}],
}


def _evidence(tmp_path: Path) -> FinalEvidence:
    final = tmp_path / "final.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=576x1024:r=24:d=4", str(final)],
        check=True,
    )
    subtitles = tmp_path / "final.srt"
    subtitles.write_text("1\n00:00:00,000 --> 00:00:02,000\nXin chào\n", encoding="utf-8")
    return FinalEvidence(
        unit_key="episode:1",
        final_path=final,
        subtitle_path=subtitles,
        narration_text="Xin chào",
        subject_digest="sha256:" + "2" * 64,
    )


async def _base_url(_provider_id: str) -> str:
    return "http://reviewer.test:11434"


def _reviewer(
    answer: dict,
    *,
    broken: str = "no",
    flipped: str = "no",
    upright: str = "A",
    illustrates: str = "yes",
    sent: list[dict] | None = None,
):
    """A scripted Ollama: each one-picture question gets its scripted reply, the scoring request ``answer``."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if sent is not None:
            sent.append(body)
        if "format" in body:
            content = json.dumps(answer)
        elif "Which one is upright" in body["messages"][0]["content"]:
            content = upright
        elif "broken" in body["messages"][0]["content"]:
            content = broken
        elif "upside down" in body["messages"][0]["content"]:
            content = flipped
        else:
            content = illustrates
        return httpx.Response(200, json={"message": {"content": content}})

    return OllamaReviewer(base_url_for=_base_url, transport=httpx.MockTransport(handler))


async def test_a_drama_review_reads_each_line_with_its_speaker_and_checks_subtitles_on_the_bare_lines(
    tmp_path: Path,
) -> None:
    sent: list[dict] = []
    evidence = dataclasses.replace(_evidence(tmp_path), form="drama", dialogue="Hải: Xin chào")

    review = await _reviewer(ANSWER, sent=sent).assess(route=ROUTE, evidence=evidence)

    assert review.outcome == "COMPLETED"
    scoring = sent[-1]["messages"][0]["content"]
    assert "LỜI THOẠI:\nHải: Xin chào" in scoring
    # The subtitle check compares the bare lines: a speaker name is never a subtitle mismatch.
    assert not [f for f in review.findings if f.code.startswith("CHECK_SUBTITLE")]


async def test_review_request_refuses_silent_truncation_and_sends_every_frame(tmp_path: Path) -> None:
    sent: list[dict] = []

    review = await _reviewer(ANSWER, sent=sent).assess(route=ROUTE, evidence=_evidence(tmp_path))

    assert review.outcome == "COMPLETED"
    assert review.language == "vi"
    assert [f.code for f in review.findings] == ["SOFT_FOCUS"]
    assert len(sent) == 4 * FRAME_COUNT + 1
    assert all(len(b["messages"][0]["images"]) == 1 and b["truncate"] is False for b in sent[:-1])
    assert sum("«Xin chào»" in b["messages"][0]["content"] for b in sent[:-1]) == FRAME_COUNT
    body = sent[-1]
    assert f"{FRAME_COUNT} khung hình" in body["messages"][0]["content"]
    assert "Khung 1 (0.2s): «Xin chào»" in body["messages"][0]["content"]
    assert (body["truncate"], body["shift"], body["stream"]) == (False, False, False)
    assert body["options"]["num_ctx"] == CONTEXT_TOKENS
    assert body["model"] == "gemma3:4b"
    assert len(body["messages"][0]["images"]) == FRAME_COUNT


async def test_context_overflow_fails_the_review(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "input length exceeds context length"})

    review = await OllamaReviewer(base_url_for=_base_url, transport=httpx.MockTransport(handler)).assess(
        route=ROUTE, evidence=_evidence(tmp_path)
    )

    assert review.outcome == "FAILED"


def test_each_frame_is_paired_with_the_subtitle_shown_or_nearest_at_its_moment() -> None:
    srt = "1\n00:00:00,000 --> 00:00:02,000\nMở đầu\n\n2\n00:00:02,000 --> 00:00:04,500\nKết thúc\n"

    assert frame_times(8.0, 4) == [1.0, 3.0, 5.0, 7.0]
    assert [cue_at(srt, t) for t in (1.0, 3.0, 5.0)] == ["Mở đầu", "Kết thúc", "Kết thúc"]
    assert cue_at("", 1.0) == ""


@pytest.mark.parametrize(
    ("broken", "flipped", "upright", "illustrates", "codes"),
    [
        ("yes", "no", "A", "yes", ["FRAME_BROKEN"]),
        ("no", "yes", "A", "yes", ["FRAME_UPSIDE_DOWN"]),
        ("no", "no", "B", "yes", ["FRAME_UPSIDE_DOWN"]),
        ("no", "no", "A", "No.", ["FRAME_NOT_ILLUSTRATING_NARRATION"]),
        ("maybe", "maybe", "maybe", "unclear", []),
    ],
)
async def test_one_picture_answers_reject_broken_upside_down_or_non_illustrating_films(
    tmp_path: Path, broken: str, flipped: str, upright: str, illustrates: str, codes: list[str]
) -> None:
    review = await _reviewer(ANSWER, broken=broken, flipped=flipped, upright=upright, illustrates=illustrates).assess(
        route=ROUTE, evidence=_evidence(tmp_path)
    )

    assert [f.code for f in review.findings if f.severity == "CRITICAL"] == codes


def test_frame_answer_thresholds() -> None:
    assert frame_answer_findings([True, None, False], [False, True, True], [True], unit_key="e") == []
    found = frame_answer_findings([True, True], [False, False, False], [True, True], unit_key="e")
    assert [(f.code, f.severity) for f in found] == [
        ("FRAME_BROKEN", "CRITICAL"),
        ("FRAME_UPSIDE_DOWN", "CRITICAL"),
        ("FRAME_NOT_ILLUSTRATING_NARRATION", "CRITICAL"),
    ]
    assert [yes_no(t) for t in ("Yes.", " no", "**No**", "vâng")] == [True, False, False, None]
    assert [upright_letter(t) for t in ("A", " B.", "**b**", "C")] == [False, True, True, None]


PROBABLE = ROUTE.model_copy(update={"model_id": "qwen2.5vl:7b", "model_identity": "ollama/qwen2.5vl:7b"})


def _probable(*, b: float = 0.05, broken: float = 0.01, illustrates: float = 0.8, sent: list[dict] | None = None):
    """A scripted Ollama returning first-token log-probabilities for each one-picture question."""

    def tops(first: str, p_first: float, second: str) -> dict:
        return {
            "message": {"content": first},
            "logprobs": [
                {
                    "token": first,
                    "logprob": math.log(p_first),
                    "top_logprobs": [
                        {"token": first, "logprob": math.log(p_first)},
                        {"token": second, "logprob": math.log(1 - p_first)},
                    ],
                }
            ],
        }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if sent is not None:
            sent.append(body)
        text = body["messages"][0]["content"]
        if "format" in body:
            return httpx.Response(200, json={"message": {"content": json.dumps(ANSWER)}})
        if "Which one is upright" in text:
            return httpx.Response(200, json=tops("B", b, "A"))
        if "broken" in text:
            return httpx.Response(200, json=tops("yes", broken, "no"))
        return httpx.Response(200, json=tops("yes", illustrates, "no"))

    return OllamaReviewer(base_url_for=_base_url, transport=httpx.MockTransport(handler))


async def test_a_probability_reviewer_reads_first_token_logprobs_per_frame(tmp_path: Path) -> None:
    sent: list[dict] = []

    review = await _probable(sent=sent).assess(route=PROBABLE, evidence=_evidence(tmp_path))

    assert review_method(PROBABLE) == PROBABILITIES
    assert review.prompt_digest == prompt_digest(PROBABILITIES) != prompt_digest(QUESTIONS)
    assert review.accepts()
    assert len(sent) == 3 * FRAME_COUNT + 1
    assert all(b["logprobs"] is True and b["options"]["num_predict"] == 1 for b in sent[:-1])
    assert sent[-1]["options"]["num_predict"] == VERDICT_TOKENS
    findings = sent[-1]["format"]["properties"]["findings"]
    assert findings["maxItems"] == VERDICT_FINDINGS
    assert findings["items"]["properties"]["detail"]["maxLength"] == FINDING_CHARS


@pytest.mark.parametrize(
    ("answers", "code"),
    [
        ({"b": 0.9}, "FRAME_UPSIDE_DOWN"),
        ({"broken": 0.9}, "FRAME_BROKEN"),
        ({"illustrates": 0.05}, "FRAMES_NOT_ILLUSTRATING_NARRATION"),
    ],
)
async def test_a_probability_reviewer_rejects_by_calibrated_thresholds(
    tmp_path: Path, answers: dict, code: str
) -> None:
    review = await _probable(**answers).assess(route=PROBABLE, evidence=_evidence(tmp_path))

    assert [f.code for f in review.findings if f.severity == "CRITICAL"] == [code]


def test_first_token_probability_normalises_between_the_two_answers() -> None:
    tops = [{"top_logprobs": [{"token": " Yes", "logprob": math.log(0.6)}, {"token": "no", "logprob": math.log(0.2)}]}]

    assert first_token_probability(tops, yes="yes", no="no") == pytest.approx(0.75)
    assert first_token_probability([{"top_logprobs": [{"token": "maybe", "logprob": 0.0}]}], yes="yes", no="no") is None
    assert first_token_probability(None, yes="yes", no="no") is None
    assert illustration_findings([0.1, 0.1, None], unit_key="e")[0].code == "FRAMES_NOT_ILLUSTRATING_NARRATION"
    assert illustration_findings([0.2, 0.1], unit_key="e") == []


def test_the_questions_method_needs_most_frames_upside_down():
    from server.production_run.evaluators import (
        MIN_FLIPPED_FRAMES_QUESTIONS,
        PROBABILITIES,
        QUESTIONS,
        _min_flipped,
        frame_answer_findings,
    )

    reflections = [False, False, True, False, True, True, False, False]
    flipped_final = [False, True, True, True, True, True, True, True]
    illustrated = [True] * 8

    def codes(flipped: list[bool | None], method: str) -> list[str]:
        found = frame_answer_findings(flipped, illustrated, unit_key="episode:1", min_flipped=_min_flipped(method))
        return [f.code for f in found]

    assert MIN_FLIPPED_FRAMES_QUESTIONS == 5
    assert codes(reflections, QUESTIONS) == []
    assert codes(flipped_final, QUESTIONS) == ["FRAME_UPSIDE_DOWN"]
    assert codes(reflections, PROBABILITIES) == ["FRAME_UPSIDE_DOWN"]


def test_frame_rules_keep_their_episode_threshold_and_name_each_offending_segment():
    keys = ["episode:1:segment:E1S01"] * 3 + ["episode:1:segment:E1S02"] * 3 + ["episode:1:segment:E1S03"] * 2
    illustrates = [True, True, True, False, True, True, False, True]

    findings = frame_answer_findings([False] * 8, illustrates, [False] * 8, unit_key="episode:1", frame_keys=keys)

    assert [(f.code, f.unit_key) for f in findings] == [
        ("FRAME_NOT_ILLUSTRATING_NARRATION", "episode:1:segment:E1S02"),
        ("FRAME_NOT_ILLUSTRATING_NARRATION", "episode:1:segment:E1S03"),
    ]
    assert {f.detail for f in findings} == {"2 frames do not illustrate their narration line"}
    one_bad = [True] * 7 + [False]
    assert frame_answer_findings([False] * 8, one_bad, [False] * 8, unit_key="episode:1", frame_keys=keys) == []


def test_frame_rules_name_the_episode_when_frames_cannot_be_placed():
    findings = frame_answer_findings([False] * 8, [False] * 8, [False] * 8, unit_key="episode:1")

    assert [f.unit_key for f in findings] == ["episode:1"]


def test_each_sampled_frame_falls_in_the_segment_playing_at_its_time(tmp_path):
    evidence = FinalEvidence(
        unit_key="episode:1",
        final_path=tmp_path / "f.mp4",
        subtitle_path=tmp_path / "f.srt",
        narration_text="",
        subject_digest="sha256:" + "0" * 64,
        segments=(("E1S01", 9.0), ("E1S02", 17.0)),
    )

    assert segment_keys(evidence, [0.5, 8.9, 9.0, 16.0, 30.0]) == [
        "episode:1:segment:E1S01",
        "episode:1:segment:E1S01",
        "episode:1:segment:E1S02",
        "episode:1:segment:E1S02",
        "episode:1",
    ]


def test_a_finals_segments_come_from_its_render_manifest_in_play_order(tmp_path):
    final = tmp_path / "episode_1.mp4"
    (tmp_path / "episode_1.manifest.json").write_text(
        json.dumps(
            {
                "units": [
                    {"unit_id": "E1S01", "video": {"duration_us": 9_041_667}},
                    {"unit_id": "E1S02", "video": {"duration_us": 8_041_667}},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert final_segments(final, 1) == (("E1S01", 9.041667), ("E1S02", 17.083334))
    assert final_segments(tmp_path / "missing" / "episode_1.mp4", 1) == ()


def test_a_vietnamese_review_keeps_its_digests_and_an_english_review_has_its_own():
    # Digests of the Vietnamese prompts that the recorded reviewer qualifications are bound to.
    assert prompt_digest(QUESTIONS) == "sha256:a5725a1a4409793150536c0d63058871f87b39c392c8d2f83653da954a1abcdd"
    assert prompt_digest(PROBABILITIES) == "sha256:27f3c064a6cbce298a3fe1cae3e91bd6bde0a5e095d3494f0e40ac3ca9758fe4"
    assert prompt_digest(WATCH) == "sha256:5535b808a20f1a42e6eda898bec340b7be2baa44ed0c9c056a596efa626c5a38"
    for method in (QUESTIONS, PROBABILITIES, WATCH):
        assert prompt_digest(method, "en") != prompt_digest(method, "vi")
    frames, watch = review_prompts("en")
    assert "English" in frames
    assert "English" in watch
    assert "tiếng Việt" not in frames + watch
    with pytest.raises(ValueError, match="no review prompt"):
        review_prompts("fr")


def test_a_drama_review_asks_about_characters_lines_and_voices_with_its_own_digest():
    from server.production_run.evaluators import match_question, review_prompts

    frames, watch = review_prompts("vi", "drama")
    for prompt in (frames, watch):
        assert "lời thoại" in prompt
        assert "giọng" in prompt
        assert "kể chuyện" not in prompt
        assert "chấm 3 trở xuống thì phải có ít nhất một finding" in prompt
    assert "Spoken line" in match_question("drama")
    assert "Narration line" in match_question("narration")
    for method in (QUESTIONS, PROBABILITIES, WATCH):
        assert prompt_digest(method, "vi", "drama") != prompt_digest(method, "vi")
    assert prompt_digest(QUESTIONS, "vi", "narration") == prompt_digest(QUESTIONS)
    with pytest.raises(ValueError, match="no drama review prompt"):
        review_prompts("en", "drama")


def test_the_review_form_follows_the_launch_profile():
    from r2.automation.profiles import review_form

    assert review_form("fiction_drama_vi_v2") == "drama"
    assert review_form("fiction_narration_vi_v1") == "narration"


def test_a_drama_reviewer_is_qualified_on_its_own_corpus():
    from server.production_run.qualification_jobs import corpus_env

    assert corpus_env("vi") == "ARCREEL_REVIEWER_CORPUS"
    assert corpus_env("en") == "ARCREEL_REVIEWER_CORPUS_EN"
    assert corpus_env("vi", "drama") == "ARCREEL_REVIEWER_CORPUS_DRAMA"
    assert corpus_env("en", "drama") == "ARCREEL_REVIEWER_CORPUS_EN_DRAMA"
