"""A2 admits declarations and Protocol stubs, without importing runtime code."""

from __future__ import annotations

import pytest

from scripts.r2.verify_m10_a2_scope import source_problems


@pytest.mark.parametrize(
    "source",
    [
        "import socket",
        "from lib.db import models",
        "import subprocess",
        "from r2.host_hardening import master_authority",
        "from .runs import start",
        "from r2.contracts.quality import *",
        "print('effect')",
        "x = factory()",
        "async def f(): ...",
        "class P:\n    async def f(self): ...",
        "from typing import Protocol\nclass P(Protocol):\n    async def f(self): return 1",
        "from typing import Protocol\nclass P(Protocol):\n    async def f(self):\n        await call()",
        "def f(): return open('output', 'w')",
        "def f(): return eval('1')",
        "def f(): return __import__('socket')",
        "def f(): return getattr(object, 'x')",
        "@factory()\ndef f(): pass",
        "class C:\n    factory()",
        "if True:\n    x = 1",
        "from types import FunctionType as property",
        "def f(): yield 1",
        "def f(x=factory()): pass",
        "class Value[T: factory()]: pass",
    ],
)
def test_a2_rejects_runtime_surfaces_and_nonabstract_async(source: str) -> None:
    assert source_problems("r2/quality/ports.py", source.encode()) == ("M10_NETWORK_SIDE_EFFECT_FORBIDDEN",)


def test_a2_allows_exact_protocol_and_model_declarations() -> None:
    source = b"""from __future__ import annotations
from typing import Protocol, Self
from pydantic import model_validator
from r2.contracts.quality import M10ContractModel
class Request(M10ContractModel):
    ref: str
    @model_validator(mode="after")
    def validate(self) -> Self:
        return self
class Reader(Protocol):
    async def read(self, request: Request) -> Request: ...
"""
    assert source_problems("r2/quality/ports.py", source) == ()


def test_a2_unknown_path_and_malformed_source_refuse() -> None:
    assert source_problems("r2/quality/runs.py", b"") == ("POST_M8_BASE_SEAM_CHANGED",)
    assert source_problems("r2/quality/parity.py", b"not valid :") == ("POST_M8_BASE_SEAM_CHANGED",)
