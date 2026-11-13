"""Build a continuity-judge corpus with local FLUX.2 klein: per story a character sheet, a location plate and
frames drawn from those references (the production storyboard path). Usage: build_corpus.py <corpus_dir>."""

import json
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:8188"
WF = json.loads(Path("/var/tmp/ar9b/flux2-klein-reference.json").read_text(encoding="utf-8"))["workflow"]

STORIES = [
    (
        "s1",
        "Linh",
        "a Vietnamese woman in her late twenties with a short black bob haircut, wearing a mustard-yellow raincoat over a white t-shirt and dark jeans, carrying a red umbrella",
        "a rainy old Hanoi street at dusk with yellow shop signs and wet cobblestones",
        [
            "stands under the red umbrella looking up at the rain, medium shot",
            "walks along the street holding the red umbrella, full shot from the side",
            "close-up of her face under the umbrella, worried expression",
            "stops at a shop window and looks inside, medium shot from behind her shoulder",
            "turns toward the camera smiling, holding the umbrella, medium close-up",
        ],
    ),
    (
        "s2",
        "Ông Tư",
        "an elderly Vietnamese fisherman around seventy with a white stubble beard, deeply tanned wrinkled skin, a conical straw hat and a faded indigo shirt with rolled sleeves",
        "a small wooden fishing boat on a calm bay at sunrise with limestone karsts behind",
        [
            "sits at the stern pulling a fishing net, medium shot",
            "close-up of his weathered face under the straw hat, squinting at the sun",
            "stands in the boat casting the net, full shot",
            "smiles while holding a silver fish, medium close-up",
            "rows the boat with a long oar, wide shot",
        ],
    ),
    (
        "s3",
        "Minh",
        "a Vietnamese boy about ten years old with spiky black hair, wearing a white school shirt with a red neckerchief, navy shorts and a blue backpack",
        "a sunny schoolyard with a big flame tree and a yellow school building",
        [
            "runs across the schoolyard with his backpack bouncing, full shot",
            "sits under the flame tree reading a comic book, medium shot",
            "close-up of his face laughing",
            "waves goodbye at the school gate, medium shot",
            "kicks a plastic ball, full shot from a low angle",
        ],
    ),
    (
        "s4",
        "Bà Hạnh",
        "a Vietnamese grandmother in her eighties with silver hair in a bun, round gold-rimmed glasses, wearing a plum-purple áo bà ba and a jade bracelet",
        "a traditional kitchen with a wood stove, clay pots and morning light through a lattice window",
        [
            "stirs a clay pot on the wood stove, medium shot",
            "close-up of her face smiling behind the round glasses",
            "sits on a low stool peeling garlic, full shot",
            "pours tea into small cups, medium close-up of her hands and face",
            "looks out the lattice window, medium shot in profile",
        ],
    ),
    (
        "s5",
        "Khoa",
        "a Vietnamese man in his thirties with a shaved head and a thin mustache, wearing a black leather jacket over a grey hoodie, silver chain necklace",
        "a neon-lit night market alley with food stalls and steam",
        [
            "walks through the alley with hands in his jacket pockets, full shot",
            "close-up of his face lit by pink neon, serious expression",
            "eats noodles at a plastic table, medium shot",
            "talks on his phone leaning on a wall, medium shot",
            "looks back over his shoulder, medium close-up",
        ],
    ),
    (
        "s6",
        "Mai",
        "a young Vietnamese woman in her early twenties with very long straight black hair to her waist, wearing a white áo dài and a conical hat held in her hand",
        "a lotus pond with a small wooden bridge in soft morning mist",
        [
            "stands on the wooden bridge looking at the lotus pond, full shot",
            "close-up of her face with long hair moving in the wind",
            "kneels at the edge of the pond touching a lotus flower, medium shot",
            "walks across the bridge holding the conical hat, wide shot",
            "smiles shyly, medium close-up",
        ],
    ),
    (
        "s7",
        "Đại úy Sơn",
        "a Vietnamese police captain in his fifties, stocky, grey crew cut, square jaw, wearing an olive-green police uniform with a peaked cap",
        "a busy city police station office with desks, files and fluorescent lights",
        [
            "sits at his desk reading a file, medium shot",
            "close-up of his stern face under the peaked cap",
            "stands at a window with hands behind his back, medium shot from behind",
            "points at a map pinned on the wall, medium shot",
            "walks down the corridor, full shot",
        ],
    ),
    (
        "s8",
        "Hoa",
        "a Vietnamese woman in her forties with curly shoulder-length auburn-dyed hair, wearing a bright green chef apron over a striped shirt",
        "a busy small restaurant kitchen with steel counters and hanging pans",
        [
            "chops vegetables on a steel counter, medium shot",
            "close-up of her face tasting soup from a ladle",
            "carries a large pot across the kitchen, full shot",
            "laughs with her hands on her hips, medium shot",
            "plates a dish carefully, medium close-up",
        ],
    ),
]

STYLE = "cinematic still, natural light, realistic, sharp focus, no text"


def upload(path: Path) -> str:
    boundary = uuid.uuid4().hex
    data = path.read_bytes()
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{uuid.uuid4().hex}.png"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode()
        + data
        + f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n--{boundary}--\r\n'.encode()
    )
    req = urllib.request.Request(
        BASE + "/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    return json.load(urllib.request.urlopen(req))["name"]


def run(prompt: str, seed: int, out: Path, w: int, h: int, refs: list[Path]) -> None:
    wf = json.loads(json.dumps(WF))
    wf["74"]["inputs"]["text"] = prompt
    wf["73"]["inputs"]["noise_seed"] = seed
    for node in ("62", "66"):
        wf[node]["inputs"]["width"], wf[node]["inputs"]["height"] = w, h
    if refs:
        names = [upload(p) for p in refs]
        for slot, node in enumerate(("100", "110", "120")):
            wf[node]["inputs"]["image"] = names[min(slot, len(names) - 1)]
        wf["63"]["inputs"]["positive"] = (
            ["103", 0] if len(names) == 1 else (["113", 0] if len(names) == 2 else ["123", 0])
        )
    else:
        for n in ("100", "101", "102", "103", "110", "111", "112", "113", "120", "121", "122", "123"):
            wf.pop(n)
        wf["63"]["inputs"]["positive"] = ["74", 0]
    wf["9"]["inputs"]["filename_prefix"] = "cj/" + uuid.uuid4().hex
    body = json.dumps({"prompt": wf, "client_id": "cj"}).encode()
    pid = json.load(
        urllib.request.urlopen(urllib.request.Request(BASE + "/prompt", body, {"Content-Type": "application/json"}))
    )["prompt_id"]
    while True:
        hist = json.load(urllib.request.urlopen(f"{BASE}/history/{pid}"))
        if pid in hist:
            entry = hist[pid]
            if entry.get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(entry["status"])[:800])
            img = entry["outputs"]["9"]["images"][0]
            q = urllib.parse.urlencode(
                {"filename": img["filename"], "subfolder": img["subfolder"], "type": img["type"]}
            )
            out.write_bytes(urllib.request.urlopen(f"{BASE}/view?{q}").read())
            return
        time.sleep(0.5)


def main(corpus: Path) -> None:
    corpus.mkdir(parents=True, exist_ok=True)
    cases = []
    for si, (sid, name, look, place, beats) in enumerate(STORIES):
        d = corpus / sid
        d.mkdir(exist_ok=True)
        char, loc = d / "character.png", d / "location.png"
        if not char.exists():
            run(
                f"Full-body character reference sheet of {look}, standing, front view, plain light grey studio background, {STYLE}",
                1000 + si,
                char,
                768,
                1024,
                [],
            )
        if not loc.exists():
            run(f"Establishing shot of {place}, empty, no people, {STYLE}", 2000 + si, loc, 576, 1024, [])
        previous = None
        for bi, beat in enumerate(beats):
            frame = d / f"frame{bi}.png"
            if not frame.exists():
                run(
                    f"{STYLE}. The person from the first reference image ({look}) {beat}, in the place from the second reference image: {place}.",
                    3000 + 10 * si + bi,
                    frame,
                    576,
                    1024,
                    [char, loc],
                )
            cases.append(
                {
                    "case_id": f"{sid}-{bi}",
                    "story": sid,
                    "expected": "ok",
                    "frame": f"{sid}/frame{bi}.png",
                    "shot": {
                        "label": f"{sid} shot {bi + 1}",
                        "description": f"{name} {beat}",
                        "characters": [name],
                        "location": place,
                        "props": [],
                        "framing": beat.rsplit(", ", 1)[-1],
                        "previous_description": f"{name} {beats[bi - 1]}" if bi else "",
                    },
                    "references": [
                        {"label": f"character: {name} — {look}", "path": f"{sid}/character.png"},
                        {"label": f"location: {place}", "path": f"{sid}/location.png"},
                    ],
                    "previous": previous,
                }
            )
            previous = f"{sid}/frame{bi}.png"
            print(sid, bi, flush=True)
    (corpus / "cases.json").write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
