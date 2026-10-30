#!/usr/bin/python3
"""Mount the existing D volume at a stable path without changing partitions."""

import datetime
import fcntl
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run through pkexec or sudo; system mount configuration requires root.")
    volume_uuid = "F676A3B876A3784F"
    parent = Path("/mnt/arcreel")
    target = parent / "D"
    fstab = Path("/etc/fstab")
    line = (
        f"UUID={volume_uuid} {target} ntfs3 "
        "rw,nosuid,nodev,uid=1000,gid=1000,acl,iocharset=utf8,prealloc,"
        "nofail,x-systemd.automount,x-systemd.device-timeout=10s 0 0"
    )
    lock_fd = os.open(
        "/run/lock/arcreel-storage-mount.lock",
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(lock_fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if fstab.is_symlink() or parent.is_symlink() or target.is_symlink():
            raise SystemExit("Refusing a symlink at a system configuration path.")
        if not Path(f"/dev/disk/by-uuid/{volume_uuid}").exists():
            raise SystemExit("Expected D volume is absent.")
        old = fstab.read_bytes()
        lines = [x.strip() for x in old.decode().splitlines() if x.strip() and not x.lstrip().startswith("#")]
        matches = [x for x in lines if volume_uuid in x or (len(x.split()) > 1 and x.split()[1] == str(target))]
        if matches and matches != [line]:
            raise SystemExit("Existing D mount configuration differs; inspect it before proceeding.")
        parent.mkdir(mode=0o700, exist_ok=True)
        os.chown(parent, 1000, 1000)
        os.chmod(parent, 0o700)
        target.mkdir(mode=0o755, exist_ok=True)
        mounted = subprocess.run(["findmnt", "-rn", "-M", str(target)], capture_output=True).returncode == 0
        if not mounted and any(target.iterdir()):
            raise SystemExit("Refusing to cover a nonempty directory with a mount.")
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = Path(f"/etc/fstab.arcreel-before-{stamp}")
        with backup.open("xb") as stream:
            stream.write(old)
        shutil.copystat(fstab, backup)
        changed = not matches
        try:
            if changed:
                new = (
                    old.rstrip(b"\n")
                    + b"\n\n# ArcReel model and media storage on the existing D volume\n"
                    + line.encode()
                    + b"\n"
                )
                fd, temporary = tempfile.mkstemp(prefix=".fstab-arcreel-", dir="/etc")
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(new)
                        os.fchmod(stream.fileno(), fstab.stat().st_mode & 0o777)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, fstab)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            subprocess.run(["findmnt", "--verify", "--tab-file", str(fstab)], check=True)
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "start", "mnt-arcreel-D.mount"], check=True)
            found = subprocess.check_output(["findmnt", "-rn", "-M", str(target), "-o", "UUID"], text=True).strip()
            if found != volume_uuid:
                raise RuntimeError(f"Mounted UUID differs: {found}")
            print(f"STABLE_MOUNT_OK {target} UUID={found}")
            print(f"FSTAB_BACKUP {backup}")
        except Exception:
            if changed:
                fstab.write_bytes(old)
                subprocess.run(["systemctl", "daemon-reload"], check=False)
            raise


if __name__ == "__main__":
    main()
