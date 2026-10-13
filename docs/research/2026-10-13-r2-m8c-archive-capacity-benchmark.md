# M8-C operator archive entry-cap benchmark

Status: disposable local benchmark against the read-only archive and offline PostgreSQL preflight at code HEAD `c503a6dc`. No production host or backup device was used.

## Reproducible setup

The runner is `tests/benchmarks/r2/governance_archive_capacity.py`. It reuses the signed genesis fixture in `tests/unit/r2/governance/test_operator_archive_reader.py`, appends valid test-key checkpoint/high-water successors, and measures `OperatorArchiveReader.read()` plus `verify_operator_archive_preflight()` against a disposable PostgreSQL 16 database migrated to Alembic head. Test trees were created under `/tmp` on `tmpfs`; the project ran under `uv` Python 3.13.14. The scanner's database had no grant scopes, matching each signed checkpoint. Each archive tree is removed after its row is measured.

After provisioning and migrating a disposable PostgreSQL database, run:

```bash
M8C_BENCHMARK_DATABASE_URL='postgresql+asyncpg://USER:PASSWORD@127.0.0.1:PORT/DB' \
  PYTHONPATH=. uv run python tests/benchmarks/r2/governance_archive_capacity.py
```

The final script run exited 0 and returned:

| Checkpoints | Reader | Full offline preflight | Result |
| ---: | ---: | ---: | --- |
| 1 | 0.003 s | 0.094 s | accepted |
| 100 | 0.036 s | 0.155 s | accepted |
| 1,000 | 0.343 s | 1.425 s | accepted |
| 4,000 | 1.451 s | 5.741 s | accepted |
| 4,993 | 1.769 s | 6.931 s | accepted at 10,000 enumerated entries |
| 4,994 | — | — | reader and preflight denied over the entry cap |

`r2/governance/operator_archive_reader.py` sets `MAX_ARCHIVE_ENTRIES = 10_000` and `MAX_ARCHIVE_BYTES = 64 MiB`. The generated tree has two retained files per checkpoint plus 14 fixed entries, so 4,993 checkpoints exercise the entry cap exactly. The observed preflight includes its repeated exact archive reads, read-only schema check and empty-ledger scanner. The 64 MiB byte cap, nonempty large grant ledgers, physical disks, host backup/restore and concurrent production load were not benchmarked. These local timings are sizing evidence, not an activation SLO or a substitute for measuring the provisioned host.
