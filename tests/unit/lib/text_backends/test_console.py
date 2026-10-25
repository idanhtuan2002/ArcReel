"""The backend console selects explicitly and does not call models while listing."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lib.text_backends.base import TextGenerationResult, TextTaskType
from lib.text_backends.console import main


def test_listing_registered_models_does_not_construct_a_client(monkeypatch, capsys):
    create = AsyncMock()
    monkeypatch.setattr("lib.text_backends.console.TextGenerator.create", create)
    assert main(["--list"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert any(r["provider_id"] == "gemini-aistudio" for r in rows)
    assert any(r["provider_id"] == "grok" for r in rows)
    assert any(r["provider_id"] == "openai" for r in rows)
    create.assert_not_awaited()


def test_generate_uses_selected_backend_and_output_limit(monkeypatch, capsys):
    generate = AsyncMock(
        return_value=TextGenerationResult(
            text="backend output", provider="gemini", model="chosen", input_tokens=10, output_tokens=5
        )
    )
    create = AsyncMock(return_value=SimpleNamespace(generate=generate, model="chosen"))
    monkeypatch.setattr("lib.text_backends.console.TextGenerator.create", create)
    assert (
        main(["--provider", "gemini-aistudio", "--model", "chosen", "--prompt", "hello", "--max-output-tokens", "64"])
        == 0
    )
    create.assert_awaited_once_with(TextTaskType.SCRIPT, provider_id="gemini-aistudio", model_id="chosen")
    request = generate.await_args.args[0]
    assert request.prompt == "hello"
    assert request.max_output_tokens == 64
    result = json.loads(capsys.readouterr().out)
    assert result["text"] == "backend output"
    assert result["provider_id"] == "gemini-aistudio"
    assert result["model_id"] == "chosen"


def test_check_constructs_selected_backend_without_generation(monkeypatch, capsys):
    generate = AsyncMock()
    create = AsyncMock(return_value=SimpleNamespace(generate=generate, model="chosen"))
    monkeypatch.setattr("lib.text_backends.console.TextGenerator.create", create)
    assert main(["--provider", "grok", "--model", "chosen", "--check"]) == 0
    generate.assert_not_awaited()
    result = json.loads(capsys.readouterr().out)
    assert result["constructed"] is True
    assert result["live_provider_verified"] is False


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--provider", "grok", "--prompt", "x"],
        ["--provider", "grok", "--model", "m", "--prompt", "x", "--max-output-tokens", "0"],
    ],
)
def test_incomplete_or_invalid_input_never_generates(args, monkeypatch):
    create = AsyncMock()
    monkeypatch.setattr("lib.text_backends.console.TextGenerator.create", create)
    with pytest.raises(SystemExit):
        main(args)
    create.assert_not_awaited()


def test_provider_failure_does_not_print_raw_secrets(monkeypatch, capsys):
    create = AsyncMock(side_effect=RuntimeError("secret-canary-do-not-print"))
    monkeypatch.setattr("lib.text_backends.console.TextGenerator.create", create)
    assert main(["--provider", "grok", "--model", "m", "--check"]) == 1
    captured = capsys.readouterr()
    assert "secret-canary" not in captured.out + captured.err
    assert json.loads(captured.err)["error"] == "MODEL_CALL_FAILED"
