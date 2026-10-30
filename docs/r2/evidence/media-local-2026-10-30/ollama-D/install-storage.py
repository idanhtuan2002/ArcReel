#!/usr/bin/python3
"""Configure only the Ollama model store on the existing D volume."""

import json
import os
import pwd
import subprocess
import time
import urllib.request
from pathlib import Path


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with pkexec or sudo to configure the system Ollama service.")
    evidence = Path(__file__).resolve().parent
    copied = json.loads((evidence / "copy-verification.json").read_text())
    assert len(copied) == 9
    destination = Path("/mnt/arcreel/D/ArcReel/ollama/models")
    volume_uuid = subprocess.check_output(
        ["findmnt", "-rn", "-M", "/mnt/arcreel/D", "-t", "ntfs3", "-o", "UUID"], text=True
    ).strip()
    assert volume_uuid == "F676A3B876A3784F"
    for entry in copied:
        file = destination / entry["relative_path"]
        assert not file.is_symlink()
        assert file.stat().st_size == entry["size"]
    drop_in = Path("/etc/systemd/system/ollama.service.d/arcreel-model-storage.conf")
    assert not drop_in.exists(), "Refusing to replace an existing storage override"
    baseline = subprocess.check_output(["systemctl", "cat", "ollama.service"], text=True)
    (evidence / "service-before.txt").write_text(baseline)
    account = pwd.getpwnam("ollama")
    subprocess.run(["setfacl", "-R", "-m", "u:ollama:rwX", str(destination)], check=True)
    for root, _, _ in os.walk(destination):
        subprocess.run(["setfacl", "-d", "-m", "u:ollama:rwx", root], check=True)
    target = Path("/var/lib/ollama-models")
    assert not target.is_symlink()
    target.mkdir(mode=0o750, exist_ok=True)
    assert not any(target.iterdir()), "Refusing to cover existing model-store data"
    os.chown(target, account.pw_uid, account.pw_gid)
    fixture = subprocess.run(
        [
            "systemd-run",
            "--quiet",
            "--wait",
            "--pipe",
            "--collect",
            "--unit=arcreel-ollama-D-permission-probe",
            "--property=User=ollama",
            "--property=Group=ollama",
            f"--property=BindPaths={destination}:{target}",
            "/usr/bin/python3",
            "-c",
            (evidence / "permission-probe.py").read_text(),
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    (evidence / "permission-probe-result.txt").write_text(fixture.stdout + fixture.stderr)
    print("OLLAMA IDENTITY FILESYSTEM PROBE PASSED", fixture.stdout.strip(), flush=True)
    loaded = json.load(urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=5))
    assert not loaded["models"], "A model is loaded; do not interrupt it"
    expected = {m["name"]: m["digest"] for m in json.loads((evidence / "models-before.json").read_text())["models"]}
    unit = (evidence / "arcreel-model-storage.conf").read_bytes()
    subprocess.run(["systemctl", "stop", "ollama.service"], check=True)
    try:
        drop_in.parent.mkdir(exist_ok=True)
        with drop_in.open("xb") as stream:
            stream.write(unit)
            stream.flush()
            os.fsync(stream.fileno())
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(
            ["systemd-analyze", "--generators=yes", "verify", "/etc/systemd/system/ollama.service"], check=True
        )
        subprocess.run(["systemctl", "start", "ollama.service"], check=True)
        for _ in range(40):
            try:
                models = json.load(urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2))
                break
            except (OSError, ValueError):
                time.sleep(1)
        else:
            raise RuntimeError("Ollama did not become ready")
        assert {m["name"]: m["digest"] for m in models["models"]} == expected
        pid = subprocess.check_output(
            ["systemctl", "show", "ollama.service", "-p", "MainPID", "--value"], text=True
        ).strip()
        sample = copied[0]["relative_path"]
        inside = Path(f"/proc/{pid}/root/var/lib/ollama-models") / sample
        assert os.path.samefile(inside, destination / sample), "Service is not using the D-backed model inode"
        result = {
            "model_digests_unchanged": True,
            "service_pid": int(pid),
            "service_model_inode_is_D_inode": True,
            "service_uid": account.pw_uid,
        }
        (evidence / "service-switch-verification.json").write_text(json.dumps(result, indent=2) + "\n")
        print("OLLAMA D STORAGE SWITCH VERIFIED", json.dumps(result), flush=True)
    except Exception:
        if drop_in.exists() and drop_in.read_bytes() == unit:
            drop_in.unlink()
        subprocess.run(["systemctl", "daemon-reload"], check=False)
        subprocess.run(["systemctl", "restart", "ollama.service"], check=False)
        print("ROLLED BACK TO ORIGINAL OLLAMA STORAGE", flush=True)
        raise
    finally:
        for file in evidence.iterdir():
            if file.is_file() and file.stat().st_uid == 0:
                os.chown(file, 1000, 1000)


if __name__ == "__main__":
    main()
