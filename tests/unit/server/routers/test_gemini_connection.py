"""Gemini connectivity discovers configured text models through the real SDK transport."""

from __future__ import annotations

from server.routers.providers import _check_gemini_aistudio
from tests.http_capture import capture_http, only_request

MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def _translate(key: str) -> str:
    return key


def _models(*names: str) -> dict[str, object]:
    return {"models": [{"name": name} for name in names]}


class TestGeminiConnection:
    def test_text_and_media_models_are_discovered_without_embedding_or_audio_models(self) -> None:
        names = [
            "gemini-3.8-flash",
            "gemini-3.6-flash",
            "gemini-2.5-flash",
            "gemini-3.5-flash-lite",
            "gemma-4-31b-it",
            "gemma-4-26b-a4b-it",
            "veo-3.1-generate-preview",
            "imagen-4.0-generate-001",
        ]
        with capture_http(assert_all_called=True) as http:
            route = http.get(MODELS_URL).respond(
                json=_models(
                    *("models/" + name for name in names),
                    "models/gemini-embedding-2",
                    "models/gemini-3.8-flash-tts",
                )
            )
            result = _check_gemini_aistudio({"api_key": "gemini-test-key"}, _translate)
        assert result.success is True
        assert result.available_models == sorted(names)
        assert only_request(route).headers["x-goog-api-key"] == "gemini-test-key"

    def test_names_are_normalized_deduplicated_and_sorted(self) -> None:
        with capture_http(assert_all_called=True) as http:
            http.get(MODELS_URL).respond(
                json=_models(
                    "models/gemma-4-31b-it",
                    "publishers/google/models/gemma-4-31b-it",
                    "models/gemini-3.6-flash",
                )
            )
            result = _check_gemini_aistudio({"api_key": "gemini-test-key"}, _translate)
        assert result.available_models == ["gemini-3.6-flash", "gemma-4-31b-it"]

    def test_empty_relevant_catalog_is_still_successful_connectivity(self) -> None:
        with capture_http(assert_all_called=True) as http:
            http.get(MODELS_URL).respond(json=_models("models/gemini-embedding-2"))
            result = _check_gemini_aistudio({"api_key": "gemini-test-key"}, _translate)
        assert result.success is True
        assert result.available_models == []
