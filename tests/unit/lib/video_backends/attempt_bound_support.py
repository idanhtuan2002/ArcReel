from __future__ import annotations

from types import SimpleNamespace


class RecordingAttemptSubmitter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def submit(self, **kwargs):
        self.calls.append(kwargs)
        receipt = await kwargs["submit"](SimpleNamespace(execution_id="execution-1"))
        return SimpleNamespace(
            execution_id="execution-1",
            snapshot=SimpleNamespace(execution_id="execution-1"),
            value=receipt.value,
        )
