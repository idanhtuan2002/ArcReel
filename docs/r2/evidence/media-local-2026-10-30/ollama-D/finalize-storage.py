#!/usr/bin/python3
"""Remove only verified original Ollama models after successful D inference."""

import hashlib
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with pkexec or sudo to remove the original service-owned files.")
    evidence = Path(__file__).resolve().parent
    original = Path("/usr/share/ollama/.ollama/models")
    destination = Path("/mnt/arcreel/D/ArcReel/ollama/models")
    records = json.loads((evidence / "copy-verification.json").read_text())
    chat = json.loads((evidence / "native-chat-before-cleanup.json").read_text())["response"]
    embedding = json.loads((evidence / "embedding-before-cleanup.json").read_text())["response"]
    assert chat["done"]
    assert chat["message"]["content"]
    assert len(embedding["embeddings"]) == 2
    assert all(len(vector) == 1024 for vector in embedding["embeddings"])
    expected_names = {record["relative_path"] for record in records}
    actual_names = {str(file.relative_to(original)) for file in original.rglob("*") if file.is_file()}
    assert actual_names == expected_names, "Original model store changed; inspect before deletion"
    verified = []
    for record in records:
        source = original / record["relative_path"]
        target = destination / record["relative_path"]
        for file in (source, target):
            assert not file.is_symlink()
            assert file.stat().st_size == record["size"]
            assert hashlib.file_digest(file.open("rb"), "sha256").hexdigest() == record["sha256"]
        stat = source.stat()
        baseline = record["source_stat"]
        assert (stat.st_dev, stat.st_ino, stat.st_mtime_ns) == (baseline["dev"], baseline["ino"], baseline["mtime_ns"])
        verified.append((source, stat))
        print("VERIFIED BEFORE DELETION", record["relative_path"], flush=True)
    expected = {
        model["name"]: model["digest"] for model in json.loads((evidence / "models-before.json").read_text())["models"]
    }
    current = json.load(urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5))
    assert {model["name"]: model["digest"] for model in current["models"]} == expected
    loaded = json.load(urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=5))
    assert not loaded["models"], "A model is loaded; do not interrupt it"
    volume_uuid = subprocess.check_output(
        ["findmnt", "-rn", "-M", "/mnt/arcreel/D", "-t", "ntfs3", "-o", "UUID"], text=True
    ).strip()
    assert volume_uuid == "F676A3B876A3784F"
    before = os.statvfs("/")
    free_before = before.f_bavail * before.f_frsize
    subprocess.run(["systemctl", "stop", "ollama.service"], check=True)
    removed = []
    try:
        for source, stat in verified:
            now = source.stat()
            assert (now.st_dev, now.st_ino, now.st_size, now.st_mtime_ns) == (
                stat.st_dev,
                stat.st_ino,
                stat.st_size,
                stat.st_mtime_ns,
            )
            source.unlink()
            removed.append(str(source))
        assert not any(file.is_file() for file in original.rglob("*"))
    finally:
        after = os.statvfs("/")
        result = {
            "removed": removed,
            "root_available_before_bytes": free_before,
            "root_available_after_bytes": after.f_bavail * after.f_frsize,
        }
        output = evidence / "original-removal.json"
        output.write_text(json.dumps(result, indent=2) + "\n")
        os.chown(output, 1000, 1000)
        subprocess.run(["systemctl", "start", "ollama.service"], check=True)
    for _ in range(40):
        try:
            current = json.load(urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2))
            break
        except (OSError, ValueError):
            time.sleep(1)
    else:
        raise RuntimeError("Ollama did not become ready; verified copies remain on D")
    assert {model["name"]: model["digest"] for model in current["models"]} == expected
    print("ORIGINAL MODEL FILES REMOVED", len(removed), flush=True)
    print("OLLAMA RESTART AND MODEL DIGESTS VERIFIED", flush=True)


if __name__ == "__main__":
    main()
