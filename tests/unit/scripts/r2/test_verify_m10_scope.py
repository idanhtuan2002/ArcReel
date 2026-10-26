"""The bounded quality packet rejects authority surfaces without importing candidate code."""

from __future__ import annotations

import pytest

from scripts.r2.verify_m10_scope import source_problems

MODULES = frozenset({"r2.contracts.common", "r2.advanced_creative.digests", "r2.contracts.quality"})


@pytest.mark.parametrize(
    "source",
    [
        "import socket",
        "from subprocess import run as launch",
        "from lib.db import models",
        "from r2.production import authority",
        "from r2.host_hardening.master_authority import resolve_m7_candidate_id",
        "from r2.quality.runs import start",
        "from r2.contracts.common import *",
        "from .common import *",
        "def f():\n    return __import__('socket')",
        "def f():\n    return eval('1')",
        "def f():\n    return open('output', 'w')",
        "def f():\n    return getattr(object, '__subclasses__')()",
        "def f():\n    yield 1",
        "async def f():\n    return 1",
        "print('side effect')",
        "x = unknown_factory()",
        "class Value[T: unknown_factory()]:\n    pass",
        "def f[T: unknown_factory()]():\n    return 1",
        "class C:\n    unknown_factory()",
        "@unknown_decorator()\ndef f():\n    return 1",
        "def hook(f):\n    return f\n@hook\ndef f():\n    return 1",
        "def f():\n    write = open\n    return write('output', 'w')",
        "from types import FunctionType as classmethod\nclass C:\n    @classmethod\n    def f():\n        return 1",
        "def hook(f):\n    return f\nclassmethod = hook\nclass C:\n    @classmethod\n    def f():\n        return 1",
        "if True:\n    x = 1",
        "try:\n    import socket\nexcept ImportError:\n    pass",
    ],
)
def test_contract_sources_refuse_runtime_imports_dynamic_execution_and_initialization(source: str) -> None:
    assert source_problems("r2/contracts/quality.py", source.encode(), allowed_project_modules=MODULES) == (
        "M10_SCOPE_EXPANSION_REQUIRED",
    )


def test_pure_model_declarations_and_relative_imports_are_allowed() -> None:
    source = b'''"""Pure fixture."""
from __future__ import annotations
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .common import R2ContractModel
class Value(R2ContractModel):
    model_config = ConfigDict(frozen=True)
    count: int = Field(gt=0)
    @field_validator("count")
    @classmethod
    def check(cls, value):
        return value
'''
    assert source_problems("r2/contracts/quality.py", source, allowed_project_modules=MODULES) == ()


def test_quality_package_initializer_has_no_executable_behavior() -> None:
    path = "r2/quality/__init__.py"
    assert source_problems(path, b'"""Quality contracts."""', allowed_project_modules=MODULES) == ()
    assert source_problems(
        path, b"from r2.contracts.quality import QualityPolicyV1", allowed_project_modules=MODULES
    ) == ("M10_SCOPE_EXPANSION_REQUIRED",)


def test_pure_string_operations_inside_functions_are_allowed() -> None:
    assert (
        source_problems(
            "r2/quality/digests.py",
            b"def f(value):\n    return value.replace('a', 'b')",
            allowed_project_modules=MODULES,
        )
        == ()
    )


def test_unknown_source_paths_and_invalid_python_are_refused() -> None:
    assert source_problems("r2/quality/runs.py", b"", allowed_project_modules=MODULES) == (
        "M10_SCOPE_EXPANSION_REQUIRED",
    )
    assert source_problems("r2/contracts/quality.py", b"not valid :", allowed_project_modules=MODULES) == (
        "M10_SCHEMA_FREEZE_FAILED",
    )
