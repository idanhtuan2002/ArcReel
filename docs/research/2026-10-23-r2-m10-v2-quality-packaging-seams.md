# M10 V2 quality and packaging: verified seams and donor limits

Research HEAD: `28b93411dc908a4616093ee4b8c9276cfeb75e19`, directly descended
from release `r2-v2.0.5`, commit `4bd70525dc2a4e5a0e05c57381a90a35301ec169`.
This records observations and proposed implications, not design acceptance.

## Host facts

1. `r2/contracts/advanced_creative.py:69` has two promotion target kinds:
   `ARTIFACT_SLOT` and `PRODUCTION_BINDING`. The candidate union at `:474`
   admits Canvas, Spatial and Format payloads. M10 is not an enum-only change:
   `lib/db/models/advanced_creative.py:74` constrains revision kinds in SQL,
   and `:99` constrains command operation names.
2. `r2/advanced_creative/exploration.py:254` creates a digest-bound, expiring
   preview after command-key and candidate-head locking. The repository's
   `lock_command_key()` (`lib/db/repositories/advanced_creative.py:152`)
   uses a transaction advisory lock on PostgreSQL; other dialects are no-ops.
   SQLite tests cannot establish PostgreSQL serialization.
3. `ExplorationPromotion.promote()` at
   `r2/advanced_creative/promotion.py:60` replays an exact recorded command,
   then locks command, candidate and preview, recomputes the candidate digest,
   verifies evidence and locks/rechecks the slot. The successful path at `:167`
   invokes the slot's `promote()`. `HostSlotAuthority.promote()` in
   `server/services/advanced_creative.py:88` invokes M7
   `MasterAuthorityUnit.promote_registered()`. This path changes production
   master authority. It is unsuitable for selecting an M10 package unchanged.
4. `MasterAuthorityRepository.advance_head()` in
   `lib/db/repositories/host_hardening.py:1008` uses an expected-version UPDATE.
   `get_current_version()` creates absent heads inside a savepoint (`:925`).
   These are implementation references; their existence does not prove a new
   packaging-head race is handled.
5. Gate C stages and promotes through M7 on the database session
   (`server/routers/gates.py:402`), then projects/exports under the head guard
   (`:449`). Gate D uses `_locked_to_heads()` (`:289`) and revalidates master
   projections before appending PublishApproval (`:672`). Packaging must
   compose the same canonical master writers' lock discipline rather than
   introducing an independent application mutex.
6. `GateAuthorization` (`r2/contracts/gates.py:20`) records the authenticated
   principal and HUMAN_OPERATOR role. `_authorization()` in gates (`:163`)
   constructs this on the server. Human quality decisions should follow this
   custody pattern, never trust an issuer or role supplied by a probe/request.
7. `format_render.verified_snapshot()` (`server/services/format_render.py:103`)
   hashes a private copy and measures that copy. `run_process()` (`:134`) kills
   and waits for its subprocess on cancellation. `format_validation.media_facts()`
   (`:40`) and `decode_errors()` (`:61`) measure metadata and decoding separately.
   The current process helper buffers `communicate()` output; it does not
   establish a capped-output or resource-isolated generic probe runner.
8. `python -m alembic heads` on this checkout returned exactly
   `918c4a0e0001 (head)`. No migration was run. Future M10 migration work must
   branch from the approved released V2 lineage and recheck this boundary;
   unfinished M9 schema changes are not prerequisites available on this branch.

## Fresh bounded qualification

Command, with the existing environment and `PYTHONPATH=.`:

```text
python -m pytest tests/unit/r2/contracts/test_advanced_creative.py tests/unit/r2/advanced_creative/test_digests.py tests/unit/r2/advanced_creative/test_exploration.py tests/unit/r2/advanced_creative/test_exploration_promotion.py -q -n 0 --junitxml=.superpowers/sdd/2026-10-23-r2-m10-v2/m8-seam-baseline.xml
```

Result: **65 passed, 1 warning, 1.73s**, exit 0; no failures or skips. The
warning is the existing expression-index reflection warning. These are contracts
and in-memory domain fixtures, not a new PostgreSQL race proof. Earlier 28
export/candidate tests are separately recorded in the start evidence and were
not rerun or combined into a newly executed 93-test suite.

## Kalinga: actual selected surface

Repository: `desaultkhan/Kalinga-Shorts-Factory`.
Pin: `e4b5a2173ca03d365aad565a89fcc43159b44f9b`.
Read from the existing M9-A bare donor cache without modifying it.

| Source | SHA-256 |
| --- | --- |
| `pipeline/src/kalinga.py` | `d8fed2e491c7a184f9682173fc04cc56eba5da41aafe1263c453c2c78c9c22f3` |
| `pipeline/src/creative.py` | `3efc1b24cbd5f479959041ad5597f6f2a2c65ea03536b27782869d561807dfcd` |

`produce()` at `kalinga.py:384–407` can pause after keyframes, before expensive
clips and assembly. In contrast, `run_to_done()` (`:410–488`) performs its
full validation after production and AI review. The bounded finding is
cheap keyframe review, not a verified universal cheap-first quality pipeline.

`run_to_done()` writes a report and marks queued work done even if the returned
validation result is not OK (`:531–540`). `cmd_bundle()` only checks that
`short.mp4` exists before calling `make_video.export_upload()` (`:723–736`).
These source paths cannot establish quality disposition or immutable export
readiness. AI review exceptions are caught and execution continues (`:461–468`).

Pure `_validate()` at `creative.py:744–799` requires labels, rejects missing or
duplicate beats, and returns soft word-count findings. It explicitly leaves
visual/overlay validation outside this function. A fresh probe compiled only
the exact `_words` and `_validate` AST nodes, avoiding module imports, credentials
and providers. Its four cases observed:

| Fixture | Observed result |
| --- | --- |
| Required labels, short text, no visual fields | No findings |
| Duplicate label | ValueError |
| Missing required label | ValueError |
| Five words with a three-word beat cap | Soft finding, no exception |

These are donor characterization cases. They are not M10 same-fixture parity.
The local cache is partial: SEO, evaluator, validation, make_video and referenced
test blobs were unavailable locally. Call-site names cannot prove their internal
repair/SEO semantics. No such unavailable surface is selected for code reuse.

## Proposed implications and remaining unknowns

- Reuse host candidate revisions and byte-verification primitives through an
  explicit shared-schema amendment. Give packaging its own selection authority.
- Keep package payload identity independent from quality run/disposition identity
  so a run can assess an already-defined package without a circular hash.
- Translate cheap ordering into prerequisites → technical probes → human semantic
  review; keep failed/error/missing evidence distinct from a quality PASS.
- Export eligibility must revalidate the exact master, package, profile, run and
  current human decision; neither a queue status nor file existence substitutes.
- No new provider, SEO model or remote repair adapter is selected. Kalinga's
  unverified runtime modules remain excluded rather than being called reusable.

Python's [3.13 zipfile documentation](https://docs.python.org/3.13/library/zipfile.html)
defines per-member timestamps and compression choices. Fixing those fields and
member order is a candidate mechanism; reproducible bundle bytes still require
an actual replay fixture on the selected runtime. The FFmpeg official search
result confirms JSON stream/format inspection; direct page retrieval timed out.
Installed-tool behavior and host-source fixtures are the current measurement
evidence; no unavailable documentation is treated as a verified implementation.

Graph project `r2-v2-main`, generation `2026-10-15T01:19:44Z`, was used only
for provisional discovery. Relevant coverage was checked; docs are excluded,
several host files changed, and the project indexes a different checkout.
All material host claims above were read on this exact V2 branch. The preview
call trace was fully paginated, but heuristic edges were not treated as authority.

## Additional offline experiments

Machine-readable results, source seals and JUnit binding are in
[R2_M10_V2_RESEARCH_2026-10-23.json](../r2/evidence/R2_M10_V2_RESEARCH_2026-10-23.json).

A synthetic one-second 160×90, 24-FPS MP4 had two audio streams: a silent first
track and an audible second track. Existing V2 helpers measured both streams,
returned peak −16.1 dB and zero full-decode errors, and refused a non-media file.
The initial experiment incorrectly expected `decode_errors()` to return a tuple;
source inspection showed an integer error count. The corrected harness passed;
no product fix was needed, and the failed harness log remains preserved.

A separate ZIP_STORED experiment on Python 3.13.14 produced identical archive
bytes from three fresh processes, roots and input mtimes, using fixed headers
and identical synthetic members. SHA-256:
`118ca1551504b3c0af802b7db2c4cabc7d2b1b0ed6d78ae8224be6d683cc5461`.
Changing a member changed the archive. This supports the proposed encoding on
this runtime only; it does not qualify the future M10 exporter, ZIP64 handling,
concurrency, authorization or production media. Both scripts are retained in the
ignored M10 workspace named by the checkpoint.
