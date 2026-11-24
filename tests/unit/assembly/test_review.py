from __future__ import annotations

from typing import Any

from assembly import review


def test_a_transient_model_error_is_retried_then_reported() -> None:
    answers = iter(
        [
            {"ok": False, "error": "status_code: 503, high demand"},
            {"ok": True, "data": {"passed": False, "report_text": "phong cách không đều"}},
        ]
    )
    pauses: list[float] = []

    def request(method: str, path: str, **_kw: Any) -> dict[str, Any]:
        assert (method, path) == ("POST", "/projects/P/episodes/1/verify/episode-overview")
        return next(answers)

    result = review.run_check(request, "P", 1, "verify/episode-overview", {}, sleep=pauses.append)
    assert result["ok"] is True
    assert result["passed"] is False
    assert result["report"] == "phong cách không đều"
    assert pauses == [review.PAUSES[0]]


def test_a_lasting_error_is_kept_as_the_result() -> None:
    def request(method: str, path: str, **_kw: Any) -> dict[str, Any]:
        return {"ok": False, "error": "Exceeded maximum output retries (2)"}

    result = review.run_check(request, "P", 1, "verify/continuity", {}, sleep=lambda _s: None)
    assert result["ok"] is False
    assert "output retries" in result["error"]


def test_every_check_is_reported_with_its_label() -> None:
    def request(method: str, path: str, **_kw: Any) -> dict[str, Any]:
        return {"ok": True, "data": {"overall_passed": True}}

    result = review.review_episode(request, "P", 2)
    assert set(result) == {"overview", "consistency", "continuity"}
    assert result["consistency"]["label"] == "Nhân vật nhất quán trên khung hình"
