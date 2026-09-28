"""The V1 operator CLI's digests and argument contract."""

from __future__ import annotations

import hashlib
import re

import pytest

from scripts.r2 import v1_operator


def test_digests_bind_the_bundle_file_and_its_script() -> None:
    result = v1_operator.digests()

    assert result["source_digest"] == "sha256:" + hashlib.sha256(v1_operator.BUNDLE.read_bytes()).hexdigest()
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", result["script_digest"])


def test_the_final_approval_requires_an_explicit_audio_decision(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        v1_operator.main(["approve-final", "--project", "p"])

    assert "--audio" in capsys.readouterr().err
