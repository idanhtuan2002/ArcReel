# Vietnamese control page (ASSEMBLY_PLAN M2b)

`uv run uvicorn assembly.web.app:app --host 127.0.0.1 --port 8790` — runs as the user unit `assembly-console`
(http://127.0.0.1:8790).

- **Runs**: connector state files `~/assembly-data/runs/<project>.json`, their logs (first `project <id>` line) and
  the user units `assembly-run-<key>` started from the page. Filters Tất cả / Đang chạy / Chờ duyệt / Hoàn tất /
  Thất bại (the old app's run-panel words). Status comes from the unit and the last `CHECKPOINT`/`STOPPED`/`DONE` line
  after the last `--- ` resume marker.
- **Run page**: film player (only files recorded in `finals`), DramaClaw `pipeline/status` as a 15-step timeline with
  a link per step into DramaClaw's own screen (view / redo there), step log, voices, last log lines, errors and
  checkpoint panels; buttons Duyệt CPn và chạy tiếp / Chạy tiếp / Tạm dừng (stops the unit; DramaClaw tasks finish).
- **Start form**: story text or a video (file path or link) → `python -m assembly.connector` with title, spine
  (narrated; drama after M2), voice region, mode auto/step. Ideas from huohuo come with M3.
- **Video ngắn**: OpenMontage projects linked to Backlot (http://127.0.0.1:4750).
- **Catalog**: `catalog.py`, every function with status, where it runs and a link.
- Redo inside a step is done in DramaClaw's screens (plan: no re-implementation of donor screens).
