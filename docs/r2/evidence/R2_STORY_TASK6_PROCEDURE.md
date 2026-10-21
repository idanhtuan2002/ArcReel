# R2 V2 Task6 — acceptance procedure (prepared 2026-10-19)

Human decisions (2026-10-19): run Task6 in a disposable development environment (option 1) and run every case of
the plan (no merging of cases).

## Environment (outside the repository)

`~/arcreel-v2-story-accept/` — never staging, never the V1 trial.

| Item | Value |
|---|---|
| Database | `arcreel_story_accept` on the disposable container `arcreel-story-test-pg` (127.0.0.1:55480) |
| Data root | `~/arcreel-v2-story-accept/data`, one narration project per case (`accept-*`) |
| Server | `start.sh` / `stop.sh [--kill]`, port 1261, login `sponsor` (password in `CREDENTIALS.txt`, mode 0600) |
| Providers | `custom-1` "Ollama local" (`localhost:11434`), `custom-2` "Ollama qua proxy" (`127.0.0.1:11500`, `proxy.sh start|stop`), each with `qwen3.5-vimax:9b` and `gemma3:12b` on `ollama-chat` |
| Authority | the production `GrantNarrativeShowrunnerAuthority` and `CurrentShowrunnerGrantReader`; one signed `HUMAN_SHOWRUNNER` grant per project for `sponsor`, signed by a disposable key (`keys/grant.key`) and imported by the production importer (`setup_accept.py`); `launch_accept.py` gives the unmodified server that reader |
| Evidence tool | `collect.py PROJECT [--snapshot N] [--against N]` → `evidence/*.json` |

Recorded deviation: the production custody path (offline signing keys, checkpoints, startup attestor) is not part
of this environment; Task7's staging smoke covers it on the activated staging deployment.

Smoke (2026-10-19, before T): login works; the reader accepts `sponsor` on `accept-clean` and denies another
principal; drafting a brief works. No run was started.

## Preconditions

1. The donor differential has finished and every fix it leads to is committed. That commit is **T**
   (`tested_code_head`); any later code change voids Task6 evidence.
2. `frontend` is built at T (`pnpm build`), so the server serves T's page.
3. The writer is `qwen3.5-vimax:9b` and the review model `gemma3:12b` on `custom-1`, except the endpoint case.

## Cases

The text lane runs one story at a time; runs queue in the order their Gate A is given.

| Project | Idea (genre) | Human actions | Agent actions | Pass condition |
|---|---|---|---|---|
| `accept-restart` | Ông Sáu sửa đồng hồ ở Chợ Lớn nhận một chiếc đồng hồ quả quýt khắc tên người vợ đã mất ba mươi năm trước. (bí ẩn nhẹ – gia đình) | Gate A | snapshot heads when chapter 2 is drafting; `stop.sh --kill`; `start.sh` | resumes; chapter-1 heads unchanged; ends at touchpoint 2 or a typed block |
| `accept-kill` | Một ông lão đánh cá ở Cửa Lò kể cho cháu nghe về đêm bão năm 1989, nhưng mỗi lần kể lại một khác. (gia đình – ký ức) | Gate A | `stop.sh --kill` while a call is in flight; `start.sh` | the in-flight attempt ends with an outcome; no call counted twice; run continues |
| `accept-endpoint` | Cô thợ may ở phố cổ Hội An nhận may lại chiếc áo dài cưới cho một bà cụ không nhớ tên mình. (tình cảm) — writer and review on `custom-2` | Gate A | `proxy.sh stop` mid-run; later `proxy.sh start` | typed state (no crash, no hang); Retry by the Human is optional |
| `accept-discard` | any short idea | Gate A, then Discard while it runs | — | `DISCARDED`; no Narrative/governance record for the run (`project_rows` only the grant) |
| `accept-clean` | Hạnh, cô giáo cắm bản ở Hà Giang, được xét chuyển về xuôi đúng lúc điểm trường sắp bị sáp nhập; cô phải chọn giữa suất chuyển và lời hứa với lũ trẻ. (tâm lý – đời thường) | Gate A, Approve | collect; Export | `COMMITTED`; exactly two Human actions; export has three chapters, zero CJK; no stored head from a truncated or over-context call; every attempt has an outcome |
| `accept-var-1` | Hai anh em sinh đôi tranh nhau tiệm phở của cha ở Nam Định sau khi cha đột quỵ; công thức nước dùng chỉ cha biết. (gia đình – hài nhẹ) | Gate A, then Approve or not | collect | completion pass: ≥ 2 of 3 variations reach touchpoint 2 with no hard finding and are committed by the Human |
| `accept-var-2` | Một nữ shipper ở Sài Gòn đêm mưa giao nhầm gói hàng, bên trong là lá thư một người mẹ gửi đứa con bỏ nhà đi. (tình cảm – đô thị) | as above | as above | as above |
| `accept-var-3` | Một kỹ sư cầu đường trở lại xã miền núi nơi anh từng làm cây cầu bị sập năm xưa, và gặp người góa phụ của người thợ đã mất. (chính kịch – chuộc lỗi) | as above | as above | as above |
| `accept-revision` | Bà Tư bán xôi ở chợ huyện bị con trai ép lên thành phố ở, nhưng bà còn một món nợ ân tình chưa trả. (gia đình) | Gate A; at touchpoint 2 request a revision of chapter 2 with a note; then Approve or Discard | snapshot heads before the revision; collect against it | regenerated nodes = exactly the Change D stale set of a chapter-2 request, as the Task4 propagation tests define it; chapter 1 unchanged |
| `accept-cjk` | Viết về ông đồ cho chữ ngày Tết ở Văn Miếu; trích nguyên văn các chữ Hán 福 祿 壽 và câu đối chữ Hán trong truyện. (đời thường – Tết) | Gate A | collect | zero CJK in every stored head and the export (detector + grammar), or a typed block |
| `accept-long` | an idea of about 3,900 characters (dense backstory, many names) | Gate A | collect | ends at touchpoint 2 or a typed block; no over-context call |

Safety pass: every run ends at touchpoint 2 or a typed blocked/terminal state, without invariant breach, crash
or hang. Completion pass: as in the table. Completion rate, blocking causes and latency per stage are
observations only. Evidence: `R2_STORY_ACCEPTANCE_RUN.json` (clean run) and `R2_STORY_RESILIENCE_RUNS.json`
(everything else), each with `tested_code_head` = T, committed as evidence-only commits on top of T.

## Order

1. Agent: finish the differential and its fixes; record T; build the frontend; `proxy.sh start`; `start.sh`.
2. Human: log in at `http://127.0.0.1:1261`, open each project's **Viết truyện** page, prepare the brief from the
   table and approve it, in this order: restart, kill, endpoint, discard, clean, var-1, var-2, var-3, revision,
   cjk, long. Discard `accept-discard` once it shows "Đang viết".
3. Agent: inject the faults when their run reaches the right point; collect evidence per run.
4. Human: at each touchpoint 2, read and decide (Approve / revise / discard). The agent never approves.

## Tested code head and gates (2026-10-20)

- **T = `0b7f869f`** (`tested_code_head`). Later commits touch only `docs/r2/evidence/`.
- Donor parity: `R2_STORY_DONOR_PARITY.json` — PASS, every surface PARITY or IMPROVED at T or at an unchanged
  earlier code head (see its `recorded_deviations`).
- Gates on T: `ruff check .`, `ruff format --check .` (1,966 files), `basedpyright --warnings` (0/0/0),
  `lint-imports` (23 kept), `deptry` (no issues); related pytest — story authoring unit and integration,
  `tests/integration/r2/narrative_plan`, `tests/integration/r2/narrative_lifecycle`, `tests/unit/lib/custom_provider`,
  `tests/unit/lib/text_backends`, gates router and export tests, i18n consistency — 2,028 passed on PostgreSQL;
  `audit_tests --check` 0 violations; `pnpm check` (typecheck, lint, knip, 2,610 tests) passed.
- Frontend built at T; acceptance server started from T with the proxy on 11500. Briefs for the Human:
  `~/arcreel-v2-story-accept/BRIEFS.md`.

## Lost first attempt and rebuilt environment (2026-10-20)

- The Human gave Gate A on `accept-restart` at about 12:22 and run `story-4085c8f44a8bd42a52ddc7bf` started. The
  server log ends abruptly at 13:28 (zero-filled tail); the host came back at 18:49. The database container runs on
  tmpfs, so the run state, grants and providers were lost. No fault had been injected and no evidence was collected,
  so that attempt counts for nothing.
- Part of that run's calls went to `127.0.0.1:11500` (the proxy provider), although the case should run entirely on
  `custom-1`. The rerun must select **Ollama local** for both writer and review model.
- The run's blobs and the log up to 13:28 are kept outside the repository in `~/arcreel-v2-story-accept/lost-run-2026-10-20/`.
- Rebuilt at HEAD `ab89da20` (T `0b7f869f` + evidence-only commits; frontend build from T unchanged): container
  restarted, `setup_accept.py` re-created both providers and the 11 grants; proxy and server started; login works and
  every `accept-*` project lists zero runs.
- Then, before any new run, the disposable container was re-created on a named volume (`arcreel-story-accept-pgdata`,
  restart policy `unless-stopped`) so a host restart no longer loses acceptance state; `setup_accept.py` re-ran and the
  checks above passed again.

## Restart case: script defect and the real kill (2026-10-21)

- `stop.sh` signalled only the `uv` wrapper and its direct children; the server's Python process (started 2026-10-20
  19:22:49) survived every stop. Consequences: the container re-creation happened under that same process (it
  reconnected to the new database; no run existed yet), the second `start.sh` failed to bind without saying so, and
  the first `stop.sh --kill` at 00:52:52 killed nothing.
- Fixed outside the repository: `stop.sh` also kills by the launcher path and fails if the server survives;
  `start.sh` refuses to start while a server process exists and fully detaches the server.
- Real fault: heads snapshot `before-kill`, then SIGKILL at 2026-10-21 00:53:58 +07 while `scene_draft[2,1]#1`
  GENERATE was in flight; fresh server up at about 00:56. Every later run uses a server process started after the fix.

## Discard case reading (2026-10-21)

The pass condition "`project_rows` only the grant" is read as: the run leaves no Narrative or governance record. A
discarded run still has its `api_calls` rows (observability of the calls it made) and the Human's own Gate A row in
`gate_greenlight_decisions`, which precedes the run; neither is created by the run's authority path.

## Human decision: reduced Task6 (2026-10-21)

After the donor-recheck fixes (`81e165fd`), the Human chose a reduced Task6 over rerunning all eleven cases: only
`accept-clean` runs on the new T (brief → Gate A → `COMMITTED` → export, exactly two Human actions, zero CJK, no stored
head from a truncated or over-context call, every attempt with an outcome). Recorded deviation from "run every case":

- Restart, kill, endpoint and discard keep their real-run passes on the previous T (`0b7f869f`, sections above) and
  are covered at the new T by the PostgreSQL driver tests (crash and resume without regenerating converged nodes, a
  transient and a persistent model outage, discard and late-result fencing in the runtime/service tests).
- The variation, revision, CJK and long-brief cases are not run; their invariants rest on the automated tests
  (grammar CJK ban, Change D propagation, over-context refusal). Completion rate across ideas stays unmeasured.
