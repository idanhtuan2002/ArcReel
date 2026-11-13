"""Qualify the storyboard continuity judge (ADR-0134) on a labelled case corpus.

``cases.json`` in the corpus directory lists ``{"case_id", "expected": "ok"|"drift", "frame", "shot": {"label",
"description", "characters", "location", "props", "framing", "previous_description"}, "references": [{"label",
"path"}], "previous": path|null}`` with paths relative to the corpus. ``--derive-swaps`` first adds, for every ok
case with a character reference, a drift case whose first character reference is swapped for a character reference
of a case from another story (``story`` field): the frame no longer shows the referenced person, an identity drift by
construction. Each case is judged once through the production prompt; the evidence JSON names the model identity,
the prompt digest, the corpus digest, every verdict and the report of ``qualify_continuity``. Exit 0 only when the
judge qualifies.

``--answers`` keeps every usable verdict as one JSON line as soon as it is given (keyed by model identity, prompt
digest and the case's own digest), so a run stopped by a daily request quota resumes where it stopped without asking
again. ``--stop-after`` stops a run after that many cases in a row got no usable answer (a quota is exhausted); the
run then writes no evidence and exits 2.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from lib.db import async_session_factory
from r2.contracts.automation import ModelRoute
from server.production_run.continuity_judge import (
    ContinuityJudge,
    Shot,
    parse_verdict,
    prompt_digest,
    qualify_continuity,
)
from server.production_run.vision_chat import model_access


def derive_swaps(cases: list[dict]) -> list[dict]:
    """``cases`` plus one identity-swap drift case per ok case that has a character reference and another story."""
    derived = list(cases)
    for case in cases:
        if case["expected"] != "ok":
            continue
        refs = case.get("references") or []
        own = next((i for i, ref in enumerate(refs) if ref["label"].startswith("character")), None)
        donor = next(
            (
                ref
                for other in cases
                if other.get("story") != case.get("story")
                for ref in other.get("references") or []
                if ref["label"].startswith("character")
            ),
            None,
        )
        if own is None or donor is None:
            continue
        swapped = [dict(ref) for ref in refs]
        swapped[own] = {"label": refs[own]["label"], "path": donor["path"]}
        derived.append({**case, "case_id": f"{case['case_id']}:swap", "expected": "drift", "references": swapped})
    return derived


def _shot(corpus: Path, case: dict) -> Shot:
    shot = case["shot"]
    previous = case.get("previous")
    return Shot(
        label=str(shot["label"]),
        description=str(shot["description"]),
        characters=tuple(shot.get("characters") or ()),
        location=str(shot.get("location") or ""),
        props=tuple(shot.get("props") or ()),
        framing=str(shot.get("framing") or ""),
        references=tuple((ref["label"], (corpus / ref["path"]).read_bytes()) for ref in case.get("references") or []),
        previous_description=str(shot.get("previous_description") or ""),
        previous_frame=(corpus / previous).read_bytes() if previous else None,
    )


def corpus_digest(corpus: Path, cases: list[dict]) -> str:
    digest = hashlib.sha256(json.dumps(cases, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    paths = sorted(
        {case["frame"] for case in cases}
        | {ref["path"] for case in cases for ref in case.get("references") or []}
        | {case["previous"] for case in cases if case.get("previous")}
    )
    for path in paths:
        digest.update(path.encode("utf-8") + hashlib.sha256((corpus / path).read_bytes()).digest())
    return "sha256:" + digest.hexdigest()


def case_digest(corpus: Path, case: dict) -> str:
    """The case and the bytes of every picture it names."""
    digest = hashlib.sha256(json.dumps(case, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    paths = [case["frame"], *(ref["path"] for ref in case.get("references") or []), case.get("previous") or ""]
    for path in paths:
        if path:
            digest.update(hashlib.sha256((corpus / path).read_bytes()).digest())
    return "sha256:" + digest.hexdigest()


def _kept(path: Path | None, identity: str) -> dict[str, dict]:
    if path is None or not path.is_file():
        return {}
    kept = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("model_identity") == identity and entry.get("prompt_digest") == prompt_digest():
            kept[entry["case_digest"]] = entry["verdict"]
    return kept


async def _main(args: argparse.Namespace) -> int:
    cases = json.loads((args.corpus / "cases.json").read_text(encoding="utf-8"))["cases"]
    if args.derive_swaps:
        cases = derive_swaps(cases)
    route = ModelRoute.model_validate(
        {
            "role": "reviewer_a",
            "provider_id": args.provider,
            "model_id": args.model,
            "model_identity": args.model_identity,
            "config_digest": "sha256:" + "0" * 64,
            "local": False,
            "paid": True,
            "currency": "USD",
            "max_cost_per_call": None,
        }
    )
    judge = ContinuityJudge(access_for=model_access(async_session_factory))
    kept = _kept(args.answers, args.model_identity)
    results, answers, missed = [], [], 0
    for case in cases:
        key = case_digest(args.corpus, case)
        if key in kept:
            verdict = parse_verdict(json.dumps(kept[key]))
        else:
            verdict = await judge.judge(route, _shot(args.corpus, case), (args.corpus / case["frame"]).read_bytes())
            if verdict is not None and args.answers is not None:
                line = {
                    "model_identity": args.model_identity,
                    "prompt_digest": prompt_digest(),
                    "case_digest": key,
                    "case_id": case["case_id"],
                    "verdict": verdict.as_json(),
                }
                with args.answers.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        missed = missed + 1 if verdict is None else 0
        if args.stop_after and missed >= args.stop_after:
            print(json.dumps({"stopped": case["case_id"], "unanswered_in_a_row": missed}))
            return 2
        results.append((case["expected"], verdict))
        answers.append(
            {"case_id": case["case_id"], "expected": case["expected"], "verdict": verdict and verdict.as_json()}
        )
    report = qualify_continuity(results)
    evidence = {
        "schema": "r2.continuity-judge-qualification.v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "model_identity": args.model_identity,
        "prompt_digest": prompt_digest(),
        "corpus_digest": corpus_digest(args.corpus, cases),
        "answers": answers,
        **report,
    }
    args.out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["qualified"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path, help="directory holding cases.json and its images")
    parser.add_argument("--provider", required=True, help="a configured provider id (gemini-aistudio, custom-<n>)")
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-identity", required=True, help="the judging route's exact model identity")
    parser.add_argument("--derive-swaps", action="store_true", help="add identity-swap drift cases")
    parser.add_argument("--out", required=True, type=Path, help="evidence JSON to write")
    parser.add_argument("--answers", type=Path, help="JSON lines of verdicts already given, read and appended")
    parser.add_argument("--stop-after", type=int, default=0, help="stop after this many unanswered cases in a row")
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
