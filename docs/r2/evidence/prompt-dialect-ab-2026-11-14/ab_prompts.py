"""A/B of storyboard prompt dialects on the local FLUX.2 klein reference workflow (read-only on prod data)."""
import json, os, sys, time, urllib.request, uuid
from pathlib import Path
sys.path.insert(0, "/home/anhtuan/content-production-os/.worktrees/r2-film-quality")
from lib.prompt_builders import render_storyboard_image_prompt, storyboard_cast

P = Path(os.path.expanduser("~/arcreel-v2-staging/data/san-xuat-tu-ong-7fb4ef4b"))
OUT = Path("/mnt/arcreel/D/ArcReel/ace-step-cache/ab")
COMFY = "http://127.0.0.1:8188"
project = json.loads((P / "project.json").read_text())
script = json.loads((P / "scripts/episode_1.json").read_text())
segs = {s["segment_id"]: s for s in script["segments"]}
d = json.loads(Path("/home/anhtuan/content-production-os/.worktrees/r2-film-quality/docs/r2/evidence/media-local-2026-10-30/flux2-klein-reference/endpoint-definition.json").read_text())["definition"]

NAM = "Nam: a thin final-year university student, short messy black hair, white T-shirt and blue jeans, hands that always tremble slightly"
EN = {
 "E1S02": {
  "json": {"scene": "a narrow, dim old sticky-rice shop in Hanoi; a steaming stove and worn wooden tables behind him",
           "subjects": [{"description": NAM, "position": "center, upper-middle of the frame", "action": "steps inside, both hands clenched against his chest in a defensive pose, trembling; a worn black leather school bag with peeling edges on the floor beside him"}],
           "style": "realistic Vietnamese TV drama still, cinematic", "lighting": "a dim warm 2800K tungsten bulb on the right casts uneven shadows across his gaunt face; faint fire glow from the stove",
           "color_palette": ["#2B2119", "#C8873E", "#E9E2D3"], "mood": "cold, nervous", "camera": {"angle": "eye level", "lens": "35mm f/2", "depth_of_field": "shallow"},
           "composition": "medium shot, vertical 9:16 frame"},
  "prose": "Medium shot, vertical frame. " + NAM + ", steps into a narrow, dim old sticky-rice shop in Hanoi, both hands clenched against his chest in a defensive pose, trembling. A worn black leather school bag with peeling edges lies on the floor beside him. Behind him a steaming stove and worn wooden tables. A dim warm 2800K tungsten bulb on the right casts uneven shadows across his gaunt face. Realistic Vietnamese TV drama still, cinematic, shot on 35mm f/2, shallow depth of field.",
 },
 "E1S03": {
  "json": {"scene": "inside the old sticky-rice shop near the door; steam rising from a big pot on the blurred kitchen stove behind; on the table a bowl of hot porridge and an old rice-cooker lid",
           "subjects": [{"description": NAM, "position": "center", "action": "sits on an old wooden chair, leaning forward to breathe in the warm steam"}],
           "style": "realistic Vietnamese TV drama still, cinematic, visible film grain", "lighting": "warm firelight from the right reflects on the wall and his face with strong contrast; rising steam catches light beams on the left (Tyndall effect)",
           "color_palette": ["#3A2614", "#E08A3C", "#F2E8D8"], "mood": "humid, warm, hungry", "camera": {"angle": "eye level", "lens": "50mm f/1.8", "depth_of_field": "shallow"},
           "composition": "close-up, vertical 9:16 frame"},
  "prose": "Close-up, vertical frame. " + NAM + ", sits on an old wooden chair near the door of an old sticky-rice shop, leaning forward to breathe in the warm steam. On the table a bowl of hot porridge and an old rice-cooker lid. Steam rises from a big pot on the blurred kitchen stove behind him and catches light beams on the left. Warm firelight from the right reflects on the wall and his face with strong contrast. Realistic Vietnamese TV drama still, visible film grain, 50mm f/1.8, shallow depth of field.",
 },
}

def post(path, payload=None, files=None):
    req = urllib.request.Request(COMFY + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())

def upload(path):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"abref_{path.name}\"\r\nContent-Type: image/png\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(COMFY + "/upload/image", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.loads(urllib.request.urlopen(req).read())["name"]

ref = upload(P / "characters/Nam.png")
def run(prompt, seed, name):
    g = json.loads(json.dumps(d["workflow"]))
    g["74"]["inputs"]["text"] = prompt
    g["73"]["inputs"]["noise_seed"] = seed
    for n in ("62", "66"):
        g[n]["inputs"]["width"], g[n]["inputs"]["height"] = 576, 1024
    g["100"]["inputs"]["image"] = ref
    for node in ("110", "111", "112", "113", "120", "121", "122", "123"):
        g.pop(node, None)
    # chain: positive conditioning goes 74 -> 103 only
    for k, v in g.items():
        for i, val in list(v["inputs"].items()):
            if isinstance(val, list) and val[0] in ("113", "123"):
                v["inputs"][i] = ["103", 0]
    g["9"]["inputs"]["filename_prefix"] = f"ab_{name}"
    pid = post("/prompt", {"prompt": g})["prompt_id"]
    while True:
        h = json.loads(urllib.request.urlopen(f"{COMFY}/history/{pid}").read())
        if pid in h and h[pid].get("outputs"):
            img = h[pid]["outputs"]["9"]["images"][0]
            data = urllib.request.urlopen(f"{COMFY}/view?filename={img['filename']}&type=output").read()
            (OUT / f"{name}.png").write_bytes(data); return
        if pid in h and h[pid].get("status", {}).get("status_str") == "error":
            raise SystemExit(json.dumps(h[pid]["status"])[:800])
        time.sleep(2)

for sid in ("E1S02", "E1S03"):
    seg = segs[sid]
    variants = {
        "A_yaml": render_storyboard_image_prompt(seg["image_prompt"], style=project.get("style", ""), style_description=project.get("style_description", ""), cast=storyboard_cast(project, seg)),
        "B_json": json.dumps(EN[sid]["json"], ensure_ascii=False),
        "C_prose": EN[sid]["prose"],
    }
    for vname, text in variants.items():
        (OUT / f"{sid}_{vname}.txt").write_text(text)
        for seed in (11, 22):
            t = time.time(); run(text, seed, f"{sid}_{vname}_s{seed}"); print(sid, vname, seed, round(time.time() - t, 1), flush=True)
