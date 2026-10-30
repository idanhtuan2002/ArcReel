"""Verify model-store filesystem behavior with the Ollama service identity."""

import json
import os
import pwd
import shutil
import uuid
from pathlib import Path

assert os.geteuid() == pwd.getpwnam("ollama").pw_uid
models = Path("/var/lib/ollama-models")
assert (models / "manifests/registry.ollama.ai/library/qwen3.5-vimax/9b").is_file()
try:
    list(Path("/mnt/arcreel").iterdir())
except PermissionError:
    private_parent_denied = True
else:
    raise AssertionError("The Ollama account unexpectedly has private D ancestor access")

probe = models / f".arcreel-permission-probe-{uuid.uuid4().hex}"
probe.mkdir(mode=0o700)
try:
    first = probe / "first"
    fd = os.open(first, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(b"ollama-model-storage-write-probe\n")
        stream.flush()
        os.fsync(stream.fileno())
    assert first.read_bytes() == b"ollama-model-storage-write-probe\n"
    second = probe / "second"
    os.replace(first, second)
    assert second.read_bytes() == b"ollama-model-storage-write-probe\n"
    print(json.dumps({"uid": os.geteuid(), "read_write_replace": True, "private_parent_denied": private_parent_denied}))
finally:
    shutil.rmtree(probe)
