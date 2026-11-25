"""Vietnamese control page (ASSEMBLY_PLAN M2b): catalog, runs, start form, step timeline, errors, film player.

Run with `uv run uvicorn assembly.web.app:app --host 127.0.0.1 --port 8790`. Donor screens are linked, not rebuilt.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from assembly.web import runs
from assembly.web.catalog import BACKLOT, CATALOG, DRAMACLAW, STATUS

app = FastAPI(title="Bàn điều khiển")
OPENMONTAGE_PROJECTS = Path.home() / "assembly-data/openmontage/projects"
_PID = re.compile(r"^[0-9A-Z]{26}$")
LABEL = {"running": "Đang chạy", "waiting": "Chờ duyệt", "failed": "Thất bại", "done": "Hoàn tất", "stopped": "Đã dừng"}
FILTERS = [
    ("all", "Tất cả"),
    ("active", "Đang chạy"),
    ("waiting", "Chờ duyệt"),
    ("done", "Hoàn tất"),
    ("failed", "Thất bại"),
]
CSS = """body{font:15px/1.5 system-ui,sans-serif;margin:0;background:#111;color:#e8e6e1}
main{max-width:1100px;margin:auto;padding:20px}a{color:#8cc8ff}h1{font-size:22px}h2{font-size:18px;margin-top:28px}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #333;padding:6px 8px;text-align:left;vertical-align:top}
.tag{padding:1px 8px;border-radius:10px;font-size:13px;white-space:nowrap}.running{background:#1d4f8f}
.waiting{background:#8a6514}.failed{background:#8f1d1d}.done{background:#1f6b3a}.stopped{background:#444}
.ready{background:#1f6b3a}.partial{background:#6b5a1f}.soon{background:#444}.none{background:#333}
.err{background:#3a1515;border:1px solid #8f1d1d;padding:10px;border-radius:6px;white-space:pre-wrap}
button{background:#2a6df4;color:#fff;border:0;border-radius:6px;padding:6px 14px;cursor:pointer}
button.alt{background:#555}input,textarea,select{background:#1c1c1c;color:#eee;border:1px solid #444;border-radius:4px;
padding:5px;width:100%;box-sizing:border-box}nav a{margin-right:14px}pre{white-space:pre-wrap;font-size:13px}
.tabs a{margin-right:10px}.tabs a.on{font-weight:bold;text-decoration:none;color:#fff}form.inline{display:inline}"""
e = html.escape
STEP_VI = {
    "build_characters": "Dựng nhân vật",
    "build_episodes": "Chia tập",
    "portraits": "Chân dung",
    "identity_plan": "Kế hoạch tạo hình",
    "identity_images": "Ảnh tạo hình",
    "script_writer": "Kịch bản",
    "content_rewriter": "Viết lại lời kể",
    "sketch_generation": "Phác thảo",
    "coloring": "Tô màu",
    "global_optimize_video": "Tối ưu video",
    "selected_regen": "Khung hình đầu",
    "voice_setup": "Chuẩn bị giọng",
    "tts": "Lồng tiếng",
    "single_video": "Video từng beat",
    "compose_episode": "Dựng phim",
}


def page(title: str, body: str, refresh: bool = False) -> HTMLResponse:
    meta = '<meta http-equiv="refresh" content="15">' if refresh else ""
    nav = (
        f'<nav><a href="/">Bàn điều khiển</a><a href="/#catalog">Chức năng</a>'
        f'<a href="{DRAMACLAW}">DramaClaw</a><a href="{BACKLOT}">Backlot</a></nav>'
    )
    return HTMLResponse(
        f'<!doctype html><html lang="vi"><head><meta charset="utf-8">{meta}<title>{e(title)}</title>'
        f"<style>{CSS}</style></head><body><main>{nav}{body}</main></body></html>"
    )


def _tag(status: str) -> str:
    return f'<span class="tag {status}">{LABEL.get(status, status)}</span>'


def _matches(run: runs.Run, flt: str) -> bool:
    return flt == "all" or (flt == "active" and run.status == "running") or run.status == flt


def _start_form() -> str:
    return """<h2 id="start">Bắt đầu phim mới</h2><form method="post" action="/start">
<p>Tên phim<input name="title" required></p>
<p>Nguồn ý tưởng: dán truyện có sẵn <b>hoặc</b> đưa video để làm lại (đường dẫn file hoặc link).
Ý tưởng của bạn và ý tưởng app tự nghĩ sẽ có ở M3 (viết truyện bằng huohuo).</p>
<p>Truyện<textarea name="story" rows="6" placeholder="Dán nội dung truyện tiếng Việt"></textarea></p>
<p>Video gốc<input name="video" placeholder="/home/…/video.mp4 hoặc https://…"></p>
<p>Kiểu phim <select name="spine"><option value="narrated">Kể chuyện (lời kể)</option>
<option value="drama" disabled>Kịch có thoại (sắp có)</option></select>
Giọng vùng <select name="region"><option value="north">Bắc</option><option value="central">Trung</option>
<option value="south">Nam</option></select>
Chế độ <select name="mode"><option value="auto">Tự động (dừng ở CP1 duyệt chân dung)</option>
<option value="step">Từng bước (chờ duyệt ở CP1–CP5)</option></select></p>
<button>Bắt đầu</button></form>"""


def _openmontage() -> str:
    rows = ""
    if OPENMONTAGE_PROJECTS.exists():
        for project in sorted(OPENMONTAGE_PROJECTS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if project.is_dir():
                renders = (
                    [r.name for r in (project / "renders").glob("*.mp4")] if (project / "renders").exists() else []
                )
                rows += (
                    f'<tr><td><a href="{BACKLOT}/p/{e(project.name)}">{e(project.name)}</a></td>'
                    f"<td>{e(', '.join(renders) or 'chưa có bản dựng')}</td></tr>"
                )
    return f"<h2>Video ngắn (OpenMontage)</h2><table><tr><th>Dự án</th><th>Bản dựng</th></tr>{rows}</table>"


def _catalog() -> str:
    body, group = '<h2 id="catalog">Danh mục chức năng</h2><table>', ""
    for grp, name, status, where, link, note in CATALOG:
        if grp != group:
            body += f"<tr><th colspan=4>{e(grp)}</th></tr>"
            group = grp
        label = f'<a href="{e(link)}">{e(name)}</a>' if link else e(name)
        body += (
            f'<tr><td>{label}</td><td><span class="tag {status}">{STATUS[status]}</span></td>'
            f"<td>{e(where)}</td><td>{e(note)}</td></tr>"
        )
    return body + "</table>"


@app.get("/", response_class=HTMLResponse)
def home(f: str = "all") -> HTMLResponse:
    all_runs = runs.load_runs()
    tabs = "".join(
        f'<a class="{"on" if k == f else ""}" href="/?f={k}">{label} ({sum(_matches(r, k) for r in all_runs)})</a>'
        for k, label in FILTERS
    )
    rows = "".join(
        f'<tr><td><a href="/run/{r.project_id}">{e(r.title or r.project_id)}</a></td><td>{_tag(r.status)}</td>'
        f"<td>{'Tự động' if r.mode == 'auto' else 'Từng bước'}</td><td>{e(('Có phim: tập ' + ', '.join(r.finals)) if r.status == 'done' else r.message[:120])}</td></tr>"
        for r in all_runs
        if _matches(r, f)
    )
    pending = "".join(
        f"<tr><td>{e(p['title'])}</td><td>{'Đang tạo dự án' if p['active'] == 'True' else 'Đã dừng'}"
        f"</td><td colspan=2><pre>{e(p['tail'])}</pre></td></tr>"
        for p in runs.pending_starts()
    )
    body = (
        f'<h1>Bàn điều khiển</h1><h2>Các lần chạy phim</h2><p class="tabs">{tabs}</p>'
        f"<table><tr><th>Phim</th><th>Trạng thái</th><th>Chế độ</th><th>Ghi chú</th></tr>{pending}{rows}</table>"
        f"{_openmontage()}{_start_form()}{_catalog()}"
    )
    return page("Bàn điều khiển", body, refresh=any(r.status == "running" for r in all_runs) or bool(pending))


@app.get("/run/{project_id}", response_class=HTMLResponse)
def run_page(project_id: str) -> HTMLResponse:
    run = _find(project_id)
    dc = f"{DRAMACLAW}/projects/{project_id}"
    steps = "".join(
        f"<tr><td>{'✅' if s['done'] else '⬜'}</td><td>{e(s['label'])}</td>"
        f'<td><a href="{dc}/{"episodes/1/" + s["page"] if s["scope"] == "episode" else s["page"]}">'
        f"Xem / làm lại trong DramaClaw</a></td></tr>"
        for s in runs.timeline(project_id)
    )
    notes = "".join(
        f"<tr><td>{e(str(s.get('at', '')))}</td><td>{e(STEP_VI.get(str(s.get('step')), str(s.get('step'))))} · {'dự án' if not s.get('episode') else 'tập ' + str(s.get('episode'))}</td>"
        f"<td>{e(str(s.get('note', '')))}</td></tr>"
        for s in reversed(run.state.get("steps", [])[-30:])
    )
    actions = ""
    if run.status == "running":
        actions = f'<form class="inline" method="post" action="/run/{project_id}/pause"><button class="alt">Tạm dừng</button></form>'
    else:
        if run.checkpoint:
            actions += (
                f'<form class="inline" method="post" action="/run/{project_id}/resume">'
                f'<input type="hidden" name="approve" value="{run.checkpoint}"><button>Duyệt {run.checkpoint} và chạy tiếp</button></form> '
            )
        if run.status != "done":
            actions += f'<form class="inline" method="post" action="/run/{project_id}/resume"><button class="alt">Chạy tiếp</button></form>'
    error = f'<h2>Lỗi</h2><div class="err">{e(run.message)}</div>' if run.status == "failed" else ""
    waiting = (
        f'<h2>Chờ duyệt</h2><div class="err" style="background:#3a2e10;border-color:#8a6514">{e(run.message)}</div>'
        if run.status == "waiting"
        else ""
    )
    films = "".join(
        f'<h3>Tập {e(ep)}</h3><video controls width="360" src="/film/{project_id}/{e(ep)}"></video>'
        for ep in run.finals
    )
    voices = ", ".join(
        f"{'Người kể' if k == '__narrator__' else e(k)}: {e(v)}" for k, v in run.state.get("voices_cast", {}).items()
    )
    tail = ""
    if run.log:
        tail = "\n".join(run.log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:])
    body = (
        f"<h1>{e(run.title)} {_tag(run.status)}</h1><p>Dự án <code>{project_id}</code> · "
        f'<a href="{dc}/episodes">Mở trong DramaClaw</a> · '
        f'<a href="{dc}/freezone">Canvas</a> · <a href="{dc}/tasks">Tác vụ</a></p>'
        f"<p>{actions}</p>{waiting}{error}<h2>Phim</h2>{films or '<p>Chưa có phim.</p>'}"
        f"{_reviews(run)}"
        f"<h2>Các bước (tập 1)</h2><table>{steps}</table><p>Giọng: {voices or '—'}</p>"
        f"<h2>Nhật ký bước</h2><table>{notes}</table><h2>Log gần nhất</h2><pre>{e(tail)}</pre>"
    )
    return page(run.title, body, refresh=run.status == "running")


def _reviews(run: runs.Run) -> str:
    out = ""
    for episode, checks in (run.state.get("reviews") or {}).items():
        out += f"<h3>Đánh giá tập {e(episode)} (chỉ báo cáo)</h3><table>"
        for item in checks.values():
            verdict = ("Đạt" if item.get("passed") else "Có vấn đề") if item.get("ok") else "Chưa chạy được"
            detail = item.get("report") or item.get("error") or ""
            out += (
                f"<tr><td>{e(str(item.get('label')))}</td><td>{e(verdict)}</td>"
                f"<td><pre>{e(str(detail)[:2500])}</pre></td></tr>"
            )
        out += "</table>"
    for episode, done in (run.state.get("finished") or {}).items():
        loud = (done.get("loudness") or {}).get("output_lufs")
        music = "có nhạc nền" if done.get("music") else "không nhạc nền"
        out += f"<p>Tập {e(episode)} đã hoàn thiện: phụ đề, {music}, âm lượng {e(str(loud))} LUFS.</p>"
    return f"<h2>Hoàn thiện và đánh giá</h2>{out}" if out else ""


def _find(project_id: str) -> runs.Run:
    if not _PID.match(project_id):
        raise HTTPException(404)
    for run in runs.load_runs():
        if run.project_id == project_id:
            return run
    raise HTTPException(404)


@app.get("/film/{project_id}/{episode}")
def film(project_id: str, episode: str) -> FileResponse:
    run = _find(project_id)
    path = (run.state.get("finished") or {}).get(episode, {}).get("final") or run.finals.get(episode)
    if not path or not Path(path).is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="video/mp4")


@app.post("/start")
def start(
    title: str = Form(...),
    story: str = Form(""),
    video: str = Form(""),
    spine: str = Form("narrated"),
    region: str = Form("north"),
    mode: str = Form("auto"),
) -> RedirectResponse:
    if not story.strip() and not video.strip():
        raise HTTPException(400, "Cần dán truyện hoặc đưa video gốc.")
    if spine not in {"narrated"} or region not in {"north", "central", "south"} or mode not in {"auto", "step"}:
        raise HTTPException(400, "Lựa chọn không hợp lệ.")
    runs.start_new(title=title.strip(), story_text=story, video=video.strip(), spine=spine, region=region, mode=mode)
    return RedirectResponse("/", status_code=303)


@app.post("/run/{project_id}/resume")
def resume(project_id: str, approve: str = Form("")) -> RedirectResponse:
    run = _find(project_id)
    if run.status == "running":
        raise HTTPException(409, "Lần chạy đang chạy.")
    runs.resume(project_id, [approve] if re.fullmatch(r"CP[1-5]", approve) else [])
    return RedirectResponse(f"/run/{project_id}", status_code=303)


@app.post("/run/{project_id}/pause")
def pause(project_id: str) -> RedirectResponse:
    _find(project_id)
    runs.pause(project_id)
    return RedirectResponse(f"/run/{project_id}", status_code=303)
