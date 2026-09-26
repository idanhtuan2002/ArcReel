# R2 V1 H6 Grid Reference Probe Plan

**Status:** provisional, read-only implementation packet. H6 design remains a draft.

**Goal:** Extract every currently declared path field from one grid JSON record
without calling `GridManager`, changing source state, or assigning backup
admission authority.

## Source and boundary

`GridGeneration.to_dict()` writes `grids/grid_*.json`, including the script,
composite, frame, and reference-image path fields
(`lib/grid/models.py:11-64,116-165`). Its `from_dict()` accepts legacy absent
`split_at` and `status="splitting"` (`:168-200`). `GridManager.__init__` creates
the grid directory and `list_all()` skips invalid JSON
(`lib/grid_manager.py:23-29,157-165`), so neither belongs in capture.

The new function accepts bounded bytes and an expected grid ID. It validates
the current writer's known JSON keys, exact identity, path-field types, and
duplicate keys, then returns raw declared references with field paths plus
presence for nullable fields. It preserves the recorded status and split
marker. It does not resolve paths, read files, decide whether a missing file
is pending, or call a backup/restore route. Unknown keys and invalid input
receive sanitized failure codes.

## Tasks

1. Write failing tests using `GridGeneration.create().to_dict()` as the
   producer fixture. Cover current and legacy shapes, absent/null path fields,
   malformed JSON, duplicate keys, unknown keys, wrong ID, invalid nested
   reference type, and byte limit.
2. Implement `r2/host_hardening/grid_reference_probe.py` with a pure
   `inspect_grid_references()` interface. Bound input size before decoding.
3. Run selected grid/probe and neighboring H6 unit tests, test audit, Ruff,
   type/import/dependency checks, and the M7 scope verifier on a clean commit.
4. Review and commit only this plan, module, and test. Report V1-01/V1-02
   review and H6 design/custody gates as still open.

## Exit

The returned fields are evidence for a later reviewed classifier. No
`BackupInventoryEntryV1`, capture adapter, restore verdict, or production
authority is created by this packet.
