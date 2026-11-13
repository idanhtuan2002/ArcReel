"""Corpus 2: the ok cases of corpus 1 plus, per ok case, a real identity drift: the same beat in the same place drawn
from ANOTHER story's character sheet (a look-alike where one exists), judged against this story's own references.
Usage: build_drift.py <corpus1> <corpus2>."""
import json, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import build_corpus as bc

DONOR = {"s1": "s6", "s6": "s1", "s2": "s7", "s7": "s2", "s4": "s8", "s8": "s4", "s5": "s7", "s3": "s5"}

def main(c1: Path, c2: Path) -> None:
    stories = {sid: (name, look, place, beats) for sid, name, look, place, beats in bc.STORIES}
    if not c2.exists():
        shutil.copytree(c1, c2, ignore=shutil.ignore_patterns("cases.json"))
    ok = [c for c in json.loads((c1 / "cases.json").read_text())["cases"] if c["expected"] == "ok"]
    cases = list(ok)
    for case in ok:
        sid, bi = case["story"], int(case["case_id"].split("-")[1])
        donor = DONOR[sid]
        _n, dlook, _p, _b = stories[donor]
        name, look, place, beats = stories[sid]
        out = c2 / sid / f"drift{bi}.png"
        if not out.exists():
            bc.run(
                f"{bc.STYLE}. The person from the first reference image ({dlook}) {beats[bi]}, in the place from the second reference image: {place}.",
                5000 + 10 * int(sid[1:]) + bi, out, 576, 1024,
                [c2 / donor / "character.png", c2 / sid / "location.png"],
            )
        cases.append({**case, "case_id": f"{case['case_id']}:wrong-person", "expected": "drift", "frame": f"{sid}/drift{bi}.png", "donor": donor})
        print(sid, bi, flush=True)
    (c2 / "cases.json").write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
