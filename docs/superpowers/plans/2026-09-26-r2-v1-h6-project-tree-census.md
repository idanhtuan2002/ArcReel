# R2 V1 H6 Project Tree Census Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a bounded, read-only physical tree census for the later H6 project inventory classifier.

**Architecture:** One pure filesystem module opens the approved absolute root and every descendant through no-follow directory descriptors. It returns sorted relative directory and regular-file records with exact size and digest. It neither assigns project liveness nor creates a backup manifest, and is not wired to the current disposable backup path.

**Tech Stack:** Python 3.13 POSIX directory descriptors, SHA-256, pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-r2-v1-m7d-recovery-closure-design.md` §4 project-file census proposal. This is a provisional primitive; the full schema and production admission still require V1-01/V1-02 approval.

## Global Constraints

- Preserve regular hidden, profile, history, opaque and lock-named files; preserve empty directories.
- Reject symlink, junction or other non-regular/non-directory entries and source change observed during a file read.
- Reject an invalid/aliased root, count/size/depth limit overflow and unavailable no-follow descriptor support with a sanitized error code; never expose source paths in errors.
- Do not mutate a source, write an archive, call a provider or grant restore authority.

## Review Focus

1. A regular `.lock` or `.claude` file is retained, while a symlink with the same name rejects.
2. A root or intermediate directory symlink rejects before reading contents.
3. A FIFO/device rejects without opening it, and no scanner operation creates a file.
4. File and total-byte bounds reject without silently truncating the result.
5. A changed file observed during hashing rejects; an external write fence remains necessary for a whole-tree recovery point.

---

### Task 1: Bounded physical census

**Files:**
- Create: `r2/host_hardening/project_tree_census.py`
- Create: `tests/unit/r2/host_hardening/test_project_tree_census.py`

**Interfaces:**
- `CensusLimits(max_files: int, max_entries: int, max_file_bytes: int, max_total_bytes: int, max_depth: int)` requires positive bounds; entries count directories and files, including the root.
- `scan_project_tree(root: Path, *, limits: CensusLimits) -> TreeCensus` returns sorted `DirectoryRecord(relative_path)` and `FileRecord(relative_path, byte_size, content_digest)` tuples; root directory uses `relative_path=""`.
- `CensusError.code` is one of `ROOT_INVALID`, `ENTRY_UNSUPPORTED`, `ENTRY_CHANGED`, `LIMIT_EXCEEDED`, `PLATFORM_UNSUPPORTED`; exception text contains only the code.

- [ ] **Step 1: Write failing tests** for a tree with hidden/lock files and empty directory, symlink root/child, FIFO, missing root, file/entry/total/depth limits. Inspect the before/after metadata guard for source changes during read; a deterministic writer-race test belongs with the later fence/capture integration.
- [ ] **Step 2: Run RED.** `DATABASE_URL=sqlite+aiosqlite:///:memory: .venv/bin/python -m pytest tests/unit/r2/host_hardening/test_project_tree_census.py -q`; expected import/behavior failure, never zero collected tests.
- [ ] **Step 3: Implement the interface** using `os.open(..., dir_fd=..., O_NOFOLLOW)` for every path component, `os.scandir(fd)`, no-follow `stat`/`fstat`, bounded streaming SHA-256 and before/after file identity checks. Source errors map to sanitized codes without an exception context.
- [ ] **Step 4: Run GREEN and relevant gates.** Run this file and neighboring backup unit tests, `scripts/audit_tests.py --check`, Ruff, basedpyright, lint-imports, deptry and `git diff --check`. Run the affected backend gate before claiming completion.
- [ ] **Step 5: Review the diff and commit only the plan, module and test.** Record the exact HEAD and limits; report that V1-01/V1-02 and custody approval still gate production wiring.

## Exit

The scanner is a reusable primitive only. H6 capture, whole-DB reference closure, custody, restore and `RECOVERY_VERIFIED` are outside this packet.
