"""Measure bounded Governance archive scans against test-only signed trees."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lib.content_digest import canonical_json_bytes
from r2.governance.operator_archive_reader import OperatorArchiveInvalid, OperatorArchiveReader
from server.services.governance_operator_archive import (
    OperatorArchiveReconcileUnavailable,
    verify_operator_archive_preflight,
)
from tests.unit.r2.governance.test_operator_archive_reader import _digest, _encoded, _put, _tree


def make_chain(parent: Path, count: int) -> Path:
    root, paths = _tree(parent)
    signer = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    previous_checkpoint = json.loads(paths["checkpoint"].read_bytes())
    previous_high_water_raw = paths["high_water"].read_bytes()
    high_water_raw = previous_high_water_raw
    checkpoint_raw = paths["checkpoint"].read_bytes()
    for sequence in range(2, count + 1):
        body = previous_checkpoint["body"] | {
            "checkpoint_sequence": sequence,
            "previous_checkpoint_digest": _digest(canonical_json_bytes(previous_checkpoint["body"], allow_nan=False)),
            "issued_at": f"2026-10-12T{sequence // 3600:02d}:{sequence // 60 % 60:02d}:{sequence % 60:02d}Z",
        }
        body_raw = canonical_json_bytes(body, allow_nan=False)
        checkpoint_raw = canonical_json_bytes(
            {"body": body, "signature": _encoded(signer.sign(body_raw))}, allow_nan=False
        )
        high_water = json.loads(previous_high_water_raw) | {
            "checkpoint_sequence": sequence,
            "checkpoint_body_digest": _digest(body_raw),
            "checkpoint_file_digest": _digest(checkpoint_raw),
            "previous_checkpoint_body_digest": body["previous_checkpoint_digest"],
            "previous_high_water_digest": _digest(previous_high_water_raw),
            "checkpoint_issued_at": body["issued_at"],
            "recorded_at": body["issued_at"],
        }
        high_water_raw = canonical_json_bytes(high_water, allow_nan=False)
        _put(root / "archive" / "high-water" / f"{sequence:020d}.json", high_water_raw, 0o600)
        _put(root / "archive" / "checkpoints" / f"sha256-{_digest(checkpoint_raw)[7:]}.json", checkpoint_raw, 0o600)
        previous_checkpoint = {"body": body}
        previous_high_water_raw = high_water_raw
    if count > 1:
        _put(paths["public_high_water"], high_water_raw, 0o644)
        _put(paths["public_checkpoint"], checkpoint_raw, 0o644)
    return root


async def main() -> None:
    engine = create_async_engine(os.environ["M8C_BENCHMARK_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        for count in (1, 100, 1000, 4000, 4993, 4994):
            with tempfile.TemporaryDirectory(prefix="m8c-archive-benchmark-") as directory:
                root = make_chain(Path(directory), count)
                if count == 4994:
                    try:
                        OperatorArchiveReader(root, expected_uid=os.getuid()).read()
                    except OperatorArchiveInvalid:
                        pass
                    else:
                        raise AssertionError("archive entry cap did not deny")
                    try:
                        await verify_operator_archive_preflight(root, session_factory=factory, expected_uid=os.getuid())
                    except OperatorArchiveReconcileUnavailable:
                        pass
                    else:
                        raise AssertionError("preflight entry cap did not deny")
                    print("4994 checkpoints: entry-cap denial", flush=True)
                    continue
                start = time.perf_counter()
                reader = OperatorArchiveReader(root, expected_uid=os.getuid()).read()
                read_s = time.perf_counter() - start
                start = time.perf_counter()
                preflight = await verify_operator_archive_preflight(
                    root, session_factory=factory, expected_uid=os.getuid()
                )
                preflight_s = time.perf_counter() - start
                assert reader == preflight
                print(f"{count} checkpoints: read={read_s:.3f}s preflight={preflight_s:.3f}s", flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
