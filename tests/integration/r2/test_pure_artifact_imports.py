"""Cold pure-contract imports must not activate host environment or filesystem authority."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "module",
    [
        "r2.artifact_identity",
        "r2.contracts.artifact_metadata",
        "r2.contracts.advanced_creative",
        "r2.advanced_creative.digests",
        "r2.contracts.host_hardening",
    ],
)
def test_pure_import_has_no_host_side_effects(module: str) -> None:
    script = r"""
import sys,os,types,pathlib,builtins,socket,subprocess,json
sys.path.insert(0,sys.argv[1])
original=dict(os.environ)

def forbidden(*args,**kwargs):
    raise AssertionError("pure import attempted host authority")

fake=types.ModuleType("dotenv")
fake.load_dotenv=forbidden
fake.dotenv_values=forbidden
sys.modules["dotenv"]=fake
pathlib.Path.mkdir=forbidden
os.mkdir=forbidden
os.makedirs=forbidden
subprocess.Popen=forbidden
socket.socket.connect=forbidden
old_open=builtins.open

def guarded_open(path,mode="r",*args,**kwargs):
    if any(flag in mode for flag in "wax+") or str(path).endswith(".env"):
        forbidden()
    return old_open(path,mode,*args,**kwargs)

builtins.open=guarded_open
__import__(sys.argv[2])
assert dict(os.environ)==original
assert not any(name in {"lib","server","lib.env_init"} for name in sys.modules)
print(json.dumps({"imported":sys.argv[2],"environment_unchanged":True,"host_modules_absent":True}))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(ROOT), module], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"imported": module, "environment_unchanged": True, "host_modules_absent": True}
