import ast, json, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path
fx = json.load(open(sys.argv[1], encoding="utf-8")); media = Path(sys.argv[2])
ns = {"json": json, "re": re, "Path": Path, "subprocess": subprocess}
for f in fx["functions"]:
    exec(compile(ast.parse(f["source"]), f["path"], "exec"), ns)
tpl = {"duration_range": [1, 10], "virality_min_overall": 40, "virality_min_hook": 35}
for name in ["av.mp4", "video_only.mp4", "silent.mp4", "intervals.mp4", "truncated.mp4", "mpeg4.mp4", None]:
    d = Path(tempfile.mkdtemp())
    if name: shutil.copyfile(media / name, d / "short.mp4")
    t = time.perf_counter()
    try: r = ns["tech_qc"](d, tpl)
    except Exception as e: r = f"RAISES {type(e).__name__}: {e}"
    vol = subprocess.run(["ffmpeg","-i",str(d/"short.mp4"),"-af","volumedetect","-f","null","-"],capture_output=True,text=True).stderr if name else ""
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", vol)
    print(name, r, "mean=", m.group(1) if m else None, f"{(time.perf_counter()-t)*1000:.0f}ms")
d = Path(tempfile.mkdtemp()); shutil.copyfile(media/"av.mp4", d/"short.mp4")
(d/"audio.json").write_text(json.dumps({"segments":[{"words":[]},{"words":[{"w":"x","start":0,"end":0.1}]}]}))
print("sparse words", ns["tech_qc"](d, tpl))
(d/"audio.json").write_text(json.dumps({"segments":[{"words":[]}]}))
print("no words", ns["tech_qc"](d, tpl))
print("virality missing", ns["virality_gate"](d, tpl))
def boom(_): raise RuntimeError("probe crashed")
print("safe_validate raising", ns["_safe_validate"](boom, d/"short.mp4"))
qc, seo = [], []; vir = ns["virality_gate"](d, tpl)
print("run ok with unknown virality", eval(fx["run_ok_expression"]["source"].split("=",1)[1]))
