# M10 A4: bounded deterministic technical observations

Status: implementation design; builder questions resolved below, main source
qualification still required. This is not an A4 runtime acceptance artifact.
Design choices below are the implementing agent's calls under the user's
instruction to continue autonomously; they are not sponsor or Human acceptance.
No production activation, migration execution or deployment is authorized here.

## Purpose and inherited boundary

Implement the existing M10-A Task A4: inspect exact approved media with fixed
local recipes, preserve typed measurements and M7 execution custody, and return
`TechnicalObservation` through the existing `QualityProbePort.observe` interface.
Metrics cannot issue Human disposition or operational readiness. A5 owns complete
run closure, foreign authority/currentness, accessibility and factual admission;
A6 owns Human disposition. This work neither resumes M9 nor begins M10-B.

Base: `2ce1478bef93a77c888f3fc8fe2a5eefd8a46d4c`, inheriting sealed A3-P
`9d06ca2a824ea8bac061f95153d3610d02e6f9c8`. Protected source/test bytes remain
those of `b69b290413d1fcbcc6f8e8c6c86887f2a4a17135` except explicitly owned
additive seams below. A3's recorded 18,449 backend passes and 77 required
PostgreSQL passes are predecessor evidence, not A4 verification.

## Alternatives and selected reuse

1. Extend `format_render.run_process`: its unbounded `communicate()` and direct
   child cancellation cannot establish the required tree/output envelope.
2. User systemd filesystem namespaces: an owned actual fixture failed with
   `226/NAMESPACE` on this host. Enabling global namespace settings is outside
   scope; silently falling back would invalidate the boundary.
3. Select user systemd cgroups plus Landlock ABI >=6 and explicit seccomp denial.
   Actual resource, filesystem, signal, network, FFprobe/decode and VMAF fixtures
   succeeded. This adds a small quality-specific supervisor, not another queue.

Reuse M7 attempts/fences/transitions and A3 publication reconstruction; retain
A1/A2 contracts, canonicalization and error identities. Existing FFmpeg validation
recipes supply same-fixture comparison cases, not a trusted A4 verdict. Exact
ArcReel-host bytes and donor limitations are in the linked [reuse research](../../research/2026-10-27-r2-m10-a4-reuse.md).
No existing runner inspected supplies all required bounds. The inspected set is
bounded; this is not an exhaustive claim about every dynamic execution surface.

## Host qualification and exact tools

Raw disposable probes are retained under
`.superpowers/sdd/2026-10-27-r2-m10-a4/`; the committed characterization artifact
records their hashes, normalized outcomes and limitations. They do not constitute
M7 receipts, cohort calibration or product implementation tests.

- Installed FFmpeg/FFprobe 8.0.1 support blackdetect, freezedetect, silencedetect,
  ebur128 and caption-related inspection. Stock FFmpeg lacks libvmaf.
- Select the official standalone Netflix VMAF 3.2.1 Linux x86_64 GCC artifact,
  source `f85a853692a8c730d0270cd733c8bb30b5b93b7c`.
  Archive SHA256 `c0bb6d354f7009530fab5749e1309bd90f9c45a5a10e90250e6e558c48cfdd02`;
  ELF SHA256 `55e2eeff3ecefe8585467afc215d25ab27dcba109bc03f65e71a77ea4e634cdd`.
  Explicit model `model/vmaf_v0.6.1.json` at that source, SHA256
  `5950d61fa1f861bd45d8149d80539ed9f3376cfc2495b8f0fa8e9f57cb131ee3`.
  Qualification uses a private developer cache, not production installation.
- VMAF runs `--threads 1 --cpumask 4294967295 --frame_cnt 5`, explicit
  `--model path=...`, 8-bit planar 4:2:0. The all-bits mask disables SIMD in this
  pinned source; zero does not. Two identical five-frame fixtures produced
  99.485749 mean; horizontal-flip fixture produced 3.567179. Compare normalized
  frame/pooled scores, excluding runtime FPS. Identical media is not assumed100.
- Every production measurement binds executable bytes, version/build output,
  recipe/parser version, canonical config, model, input bytes and measured span.
  A version string alone is insufficient. Tools are never installed or fetched
  by `observe`. Missing/unqualified tools fail closed.

Primary sources: [Landlock kernel API](https://docs.kernel.org/userspace-api/landlock.html),
[systemd 259 resources](https://www.freedesktop.org/software/systemd/man/259/systemd.resource-control.html),
[systemd group cleanup](https://www.freedesktop.org/software/systemd/man/259/systemd.kill.html),
[VMAF release](https://github.com/Netflix/vmaf/releases/tag/v3.2.1),
[pinned CLI](https://github.com/Netflix/vmaf/blob/f85a853692a8c730d0270cd733c8bb30b5b93b7c/libvmaf/tools/cli_parse.c),
[pinned CPU-mask semantics](https://github.com/Netflix/vmaf/blob/f85a853692a8c730d0270cd733c8bb30b5b93b7c/libvmaf/src/libvmaf.c).
The implementation gate must repeat the resource and recipe fixtures; these
research results alone cannot enable a capability entry.

## Interfaces, trust and input acquisition

Keep `ProbeRequest` and `ProbeReceipt = TechnicalObservation` unchanged. New pure
module `r2/quality/probes.py` defines frozen, extra-forbid `ProbeConfig`,
`ProbeMeasurement` and `ProbeExecutionResult`, all schema-versioned. Configuration
contains structured numeric/rational limits and allowlisted recipe enums only;
never shell, executable, arbitrary filter text, URL or caller filesystem paths.
A host-owned immutable `ProbeCatalog` maps each config/applicability/threshold/
reference policy identity+digest to its full verified body. Unknown identities,
changed bodies and version constraints fail closed before execution.
The catalog is a code-embedded frozen tuple, schema `m10.probe-catalog.v1`,
released with source under `r2/quality/probes.py`; no mutable JSON/DB registry or
runtime catalog update. `ProbeCatalog` construction recomputes every body's
digest, validates unique identity+revision, fixed enums, ranges and tool pins.
Its immutable catalog digest is recorded in the invocation. New bodies/tools
require source review and the same-fixture qualification gate. `observe` cannot
use caller-supplied policy bodies to populate missing catalog entries.

`QualityProbeService.for_request(request, sessions, *, interactive_token,
project_root, catalog, runtime)` creates a request-bound private service. Its
`observe(request)` first revalidates the real `get_current_interactive_user`
JWT and matches `(user.id,user.sub)` with `(user_id,actor_id)`. Reject auth-off,
API keys, expired JWT and changed request bindings. Recheck before returning a
replay and before committing finalization. This initial host adapter supports
interactive invocation only; it has no new public router, background identity,
Human grant issuance or default app registration. The catalog/runtime arguments
are host configuration, never accepted from an HTTP payload.

Envelope: canonical request <=1,048,576 bytes; all identity fields <=255 UTF-8
bytes; finite numeric values; digest caches recomputed from complete bodies.
Before first execution resolve the exact stored profile via
`QualityProfileRepository.get_revision` and require full canonical equality.
That reader reconstructs publication custody. Read the actual scoped approved
root via `MasterAuthorityRepository.get_current` and require equality of root
version/candidate/object reference/content digest/approval record. A1 validates
embedded metadata closure, not independent foreign authority. A4 explicitly does
not certify dependency/content-basis currentness; A5 must resolve those owners
before accepting operational readiness.

Host root/ref/caption locators use anchored directory descriptors, reject `..`,
foreign paths, symlinks in every component, nonregular files and escaped roots.
The stored master `object_ref` is an absolute host path in the existing seam:
lexically strip only the exact trusted project-root prefix, then open each
remaining component relative to its anchored descriptor. Reject absolute public
paths; do not `resolve()` symlinks into acceptance. Open with no-follow, check identity, copy with byte ceilings to a private
0700 directory, hash actual copied bytes and compare the expected digest.
Do not reuse the manifest's unbounded JSON read as authority. Caption/reference
locations come from the trusted catalog's scoped bindings; public DTOs provide
no path. Target/ref combined <=134,217,728 bytes and each <=67,108,864; caption
<=262,144 bytes within that total. Exact immutable copied bytes survive later
source replacement. Root/profile equality is checked in prepare and finalize;
change before finalize yields typed stale error, leaving historical M7 evidence.

Receipt-first replay authenticates and verifies the entire stored request/result/
M7/observation chain before live master, media, catalog or tool checks. Same
full key with different canonical request conflicts, even if its hash collides.

## Execution envelope and isolation

One random owned systemd **service**, not a scope or shell. `--service-type=exec`,
`--expand-environment=no`, fixed executable/argv, bounded stdout and stderr read
concurrently, no inherited database or token environment. Close unrelated FDs;
Landlock cannot revoke previously inherited descriptors. The worker starts
single-threaded, sets no-new-privileges, installs its complete policy, confirms
it, then execs only fixed recipes. Never let a caller supply Python code.

| Resource | Maximum / enforcement |
|---|---|
| Tool wall budget | `min(rule.max_runtime_ms,120000)` ms, shared across recipe subprocesses |
| Group memory / swap | MemoryMax 536,870,912 bytes; MemorySwapMax0 |
| Group tasks | TasksMax32, includes threads/descendants |
| CPU rate | CPUQuota100%; recorded rate ceiling, not a total CPU-time guarantee |
| Cleanup | RuntimeMaxSec plus independent host deadline; KillMode control-group; TimeoutStopSec1; then kill/wait/check no live members |
| Streams/result | combined stdout+stderr <=`min(rule.max_output_bytes,1048576)` bytes; stored canonical result<=1,048,576 bytes |
| Scratch | exactly three precreated regular writable inodes, each LimitFSIZE67,108,864; <=201,326,592 total payload bytes |
| Other | LimitCORE0; clean env LC_ALL=C,TZ=UTC, single tool threads; no network; no raw log persistence |

Cgroup effective files must match the admitted envelope before tool exec.
MemoryMax is kernel cgroup accounting with documented possible transient overshoot,
not a claim of exact RSS. Record effective caps, peak accounting, exit/OOM/timeout
outcome and group cleanup. Deadline expiry rejects late results; cleanup has a
separate bounded grace and is not misrepresented as hard real-time precision.
Unsupported/delegation failure means no tool execution and required evidence
missing; never silently drop a controller.

Landlock ABI>=6 handles all FS rights supported by the selected policy, allows
read-only exact copied inputs/model/tool and required shared system libraries,
and scopes signals/abstract Unix sockets. Only the three scratch inodes permit
write/truncate; no create/delete/rename rights. No project directory or home-wide
allow rule. Seccomp rejects `@network-io`, `@debug`, `ptrace`,
`process_vm_readv`, `process_vm_writev`, `kcmp`, `io_uring_setup`,
`io_uring_enter`, `io_uring_register`, with EPERM. Explicit process-memory calls
are required: the installed `@debug` group alone did not block the readv fixture.
Untrusted media never runs before policy confirmation. Resource/isolation
fixtures must include a forked child, malicious local reference, output flood,
read/write escape, socket and out-of-domain signal/memory attempts.

## Recipes and measurement meaning

All paths are supervisor-owned handles; FFmpeg uses `-nostdin`, explicit file/pipe
protocol whitelist, no stdin media/remote nested fetches, single threads and fixed
filter templates constructed from validated numeric values. Allow only target
container/stream formats qualified by fixtures; unsupported inputs are explicit.
Do not pass through metadata tags, private filenames or raw captions/logs.

- `CONTAINER_STREAM`: fixed FFprobe JSON whitelist of video/audio codec,
  dimensions, pixel format, rational frame/time bases, duration and channel/rate
  facts. Reject duplicate/missing required streams and malformed/nonfinite facts.
- `DECODE`: full selected-stream FFmpeg decode to null with error-level reporting;
  a zero exit is only decode evidence. Missing streams follow explicit policy.
- `INTERVALS`: black/freeze/silence filters with digest-bound policy numeric
  thresholds/durations. Record sorted exact start/end rational intervals;
  unclosed EOF intervals close only at independently measured duration and carry
  the EOF marker. No interval finding issues a disposition.
- `LOUDNESS`: fixed ebur128 summary; finite integrated LUFS/true peak or explicit
  `SILENT`/`UNMEASURABLE`, never IEEE Infinity/NaN or fabricated zero. No audio is
  governed by the profile applicability body, not an implicit passing score.
- `CAPTIONS`: strict UTF-8 SRT or WebVTT parser (catalog enum), <=10,000 cues,
  bounded text, exact ordered start/end times, no negative/reversed/out-of-duration
  cues; report overlap, coverage and count. Persist no caption content. Timing
  evidence does not certify language, accuracy or accessibility conformance.
- `REFERENCE_VMAF`: named reference required; catalog eligibility binds scope,
  content provenance, timing, geometry and exact model/config. Reject absent,
  changed, foreign, incomparable or insufficient-frame reference as
  `M10_REFERENCE_INVALID`. Both sources must match geometry/rational FPS,
  zero-offset timing, 8-bit 4:2:0, >=5 frames; width*height<=2,073,600 and
  FPS in [1,60]. Decode exactly first5frames of each into the two precreated
  raw files; no resize, temporal alignment or hidden resampling. The third
  scratch inode is VMAF JSON. Report scope `FIRST_5_FRAMES`, frame scores and
  mean, not whole-video perceptual quality. Reject either decoded raw size
  differing from width*height*3/2*5. This limited recipe is explicit in the
  profile; a full-video requirement is unsupported, never silently truncated.

Concrete private schemas (all extra-forbid/frozen, strict scalar types):

- `MediaTime`: integer numerator and positive denominator, reduced by gcd;
  signed values allowed only where explicitly stated. `Interval`: start/end
  `MediaTime` with 0<=start<=end<=measured duration, kind BLACK/FREEZE/SILENCE,
  `ended_at_eof: bool`. Sort by (start,end,kind); <=10,000 intervals.
- `StreamFacts`: index:int>=0, kind VIDEO/AUDIO, codec:str allowlisted,
  width/height/pixel_format for video; sample_rate/channels for audio;
  frame_rate/time_base:MediaTime, duration:MediaTime or explicit UNKNOWN.
  Exact optional-field consistency is validated by kind. <=16 streams.
- `ContainerFacts`: format enum, duration:MediaTime, tuple[StreamFacts,...].
- `DecodeFacts`: tuple[int,...] decoded stream indices and `complete: bool`;
  `complete=False` cannot yield PASS.
- `IntervalFacts`: measured_duration and tuple[Interval,...].
- `LoudnessFacts`: state FINITE/SILENT/UNMEASURABLE, integrated_lufs and
  true_peak_dbfs as decimal strings only for FINITE; absent otherwise.
- `CaptionFacts`: format SRT/WEBVTT, cue_count:int, tuple of start/end time
  pairs, union_coverage:MediaTime, overlap_count:int. No caption strings.
- `VmafFacts`: span FIRST_5_FRAMES, width,height, frame_rate, model_digest,
  exactly five `(index:int,score:decimal-string)` entries, mean:decimal-string;
  scores/mean finite in [0,100], indices exactly0..4.
- `ProbeMeasurement`: schema_id=`m10.probe-measurement.v1`, recipe enum,
  input_digests:ordered tuple, tool_identity_digest, config_digest,
  parser_version, discriminated facts union above, technical status and
  ordered findings (rule_id,severity,public locator,evidence digest).
- `ResourceEvidence`: schema_id=`m10.probe-resources.v1`, effective memory,
  swap, task and CPU caps; wall_elapsed_ms; peak_memory_bytes or explicit
  unavailable; peak_tasks or explicit unavailable; stdout_bytes,stderr_bytes,
  scratch_sizes:three-tuple; exit_code, manager_result enum, oom_killed,
  deadline_exceeded, output_exceeded, group_cleanup_verified booleans;
  kernel/control/tool identities. Missing mandatory effective caps or cleanup
  confirmation cannot produce successful `ProbeExecutionResult`.
- `ProbeExecutionResult`: schema_id=`m10.probe-execution-result.v1`,
  request_digest, execution_id, measurement:ProbeMeasurement,
  resources:ResourceEvidence, started_at/finished_at aware UTC. Digest includes
  every field; stable measurement digest includes only ProbeMeasurement.

No generic arbitrary `dict` measurement payload is accepted. Numeric detector
parameters use decimal strings parsed under a fixed precision24 context;
canonical decimal output has no exponent, trailing zeros or negative zero.
Measurement schemas identify kind, input/tool/config/parser identities, span,
normalized facts, findings and resource outcomes. Deterministic measurement
identity excludes wall clock, unit/PID, FPS throughput and memory-peak variation;
those remain separately bound resource evidence in the execution result.
Private digest envelopes use reused `digest_canonical` and explicit A4 domains;
do not extend or mutate the frozen A1 `DIGEST_DOMAINS` registry.

Tool absence / invalid reference / policy inapplicability are distinct. Missing
required tool or policy => `M10_REQUIRED_EVIDENCE_MISSING`; invalid named reference
=> `M10_REFERENCE_INVALID`; resource/output ceiling =>
`M10_OPERATIONAL_ENVELOPE_EXCEEDED`; malformed/nonzero tool => `M10_PROBE_FAILED`.
Policy-authorized INAPPLICABLE requires a measured applicability fact and exact
policy digest. PASS/FAIL are technical threshold outcomes, never dispositions.
A crashed/timed-out probe cannot produce a successful observation.

## Persistence, M7 and recovery

Add three append-only scoped tables in `lib/db/models/quality_probes.py` and a
single repository `lib/db/repositories/quality_probes.py`:

1. `m10_quality_probe_invocations`: PK `(user_id,project_name,actor_id,execution_ref)`;
   full request JSON+digest, unique scoped M7 execution ID, reserved observation
   UUIDv7, exact route/config/catalog/tool identities and prepare timestamp.
2. `m10_quality_probe_results`: scoped execution PK/FK to invocation; normalized
   measurement + resource body/digests, input fingerprints and immutable result
   timestamp. No token/media/raw logs/caption text or private paths.
3. `m10_quality_probe_observations`: scoped observation PK plus unique invocation
   FK; full `TechnicalObservation`, digest and finalized timestamp.

All rows have scoped restrictive user/invocation FKs, <=1MiB JSON envelope
checks, and PostgreSQL/SQLite update/delete refusal triggers. PostgreSQL is the
only runtime authority. SQLite migration parity is not concurrency proof.
Migration `07fd34535384` follows `65f53650f3a8`; no predecessor migration edit.
The former singleton-head assertion gets exactly one compatibility adjustment:
use `heads = script.get_heads(); assert len(heads) == 1`,
`assert REVISION in {item.revision for item in script.walk_revisions(base="base", head=heads[0])}`,
then retain `assert script.get_revision(REVISION).down_revision == PREDECESSOR`.
Only that historical test gets this edit; no shared assertion or old migration
changes. Prove this with a disposable no-op successor before the real one.

Prepare transaction: acquire full-command advisory guard, compare complete
identity on rows, replay or resolve profile/root, create durable task/API-call
and M7 PLANNED attempt plus invocation atomically. Hash collisions only serialize;
they do not merge identities. Derive M7 keys from scoped canonical data, not
unbounded concatenation or caller-provided route. Follow existing M7 lock order.

Separate route family `local-ffmpeg/quality-probe/host-quality-v1`, registry ref
`local-ffmpeg-quality-probe@host-quality-v1`: idempotency NONE,
not-found NON_AUTHORITATIVE; no poll/cancel/lookup/webhook claims. A collected
systemd unit is not authoritative proof the execution never happened.
Qualification status cannot become OFFLINE_VERIFIED until actual route/runtime/
recovery fixtures pass; do not register an enabled default app submit path.

Reuse `build_attempt_submitter`/`ExecutionAttemptServiceImpl`: commits PLANNED,
fence and SUBMITTING before adapter callback. Run tools with no DB transaction.
On successful normalized result, callback closes over the same `AsyncSession` supplied to
`build_attempt_submitter(session, user_id=..., project_name=...)`; it calls
`QualityProbeRepository(session).stage_result(invocation, result)` (flush,
no commit), then returns `ProviderSubmitReceipt(observation=ACCEPTED,
value=result)`. This is the existing `SubmitFn` hook, not a new M7 interface.
It returns ACCEPTED with the complete result digest. M7 commits both
result and acceptance atomically; an exception after possible tool start must
be ambiguous, never ordinary failed-before-acceptance. If staging fails,
rollback the callback's uncommitted session before raising `AmbiguousSubmitError`;
M7 can then commit the unknown transition. Failure of M7's acceptance commit
itself leaves reconciliation necessary and must never trigger automatic retry. Do not change M7 state
machine or use a second commit callback for result storage.

Finalize in a fresh transaction under full command guard: reauthenticate,
recompute request/result/caches, verify scoped M7 route/request/acceptance
witness and effective resource evidence, revalidate profile/root for first
finalization, transition ACCEPTED to SUCCEEDED and append observation plus
existing M7 project event atomically. The observation's receipt/evidence fields
bind this exact chain. Do not reuse A3's PUBLISH-only commands/outbox semantics.

Crash cuts: before prepare commit leaves nothing; PLANNED may submit once;
SUBMITTING without committed result remains unknown and never auto-runs again;
ACCEPTED+result can finalize after restart; SUCCEEDED+observation replays exactly.
Concurrent exact calls converge or raise `RequiredEvidenceMissingError`
while pending, with one tool start. Preflight failure before prepare commit
raises `RequiredEvidenceMissingError` and writes no invocation/attempt; failed
startup after SUBMITTING follows the M7 ambiguous branch, stores no success
result/observation, and never becomes an INAPPLICABLE observation. Deterministic
known tool failure is a persisted failed M7 attempt with sanitized reason and no
TechnicalObservation. Inherited M7 recovery can move an unresolved unknown to
operator review; A4 only reads that state and returns required-evidence-missing.
There is no A4 operator-resolution API. An authenticated interactive caller may
start a newly authorized full request with a new execution_ref; it is a distinct
attempt, not a replay or clearance of the old outcome. Changed request conflicts. M7 fence lease300s exceeds120s tool budget;
verify cleanup+bounded DB operations cannot overrun it. JWT expiry after tools
prevents finalization; historical result remains. No transaction spans subprocess
I/O, and no recovery path fabricates tool lookup authority.

## Owned paths and qualification gates

New source: `r2/quality/probes.py`; `server/services/quality_probes.py`,
`quality_probe_inputs.py`, `quality_probe_runtime.py`, `quality_probe_worker.py`;
`lib/db/models/quality_probes.py`; `lib/db/repositories/quality_probes.py`;
`alembic/versions/07fd34535384_quality_probe_evidence.py`;
`scripts/r2/verify_m10_a4_scope.py`.
Existing additive seams: model exports, one route family, one capability entry,
and the exact migration-test ancestry compatibility edit above. Test paths mirror
these modules under unit/integration; helper fixtures stay under
`tests/fixtures/r2/`. Evidence documents live under `docs/r2/evidence/`.
No protected A1/A2 contract/error/digest changes, A3 publication logic changes,
production config, frontend, old migration, M9 or unrelated cleanup.

Before source work, freeze exact owned paths, protected hashes and guard tests.
Run test-first pure normalization, hostile-input isolation, actual FFmpeg/VMAF,
PostgreSQL replay/crash/concurrency, migration cycle and predecessor regressions.
The scope guard must use actual Git HEAD/status/index with independently verified
baseline data; no fabricated HEAD. Finish required affected-domain gates from
CONTRIBUTING, test audit and one complete source adjudication. Record pending
checks honestly. A4 acceptance does not close A5/A6/A7 or enable production.
