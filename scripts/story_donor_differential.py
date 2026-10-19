"""Task4.6 donor differential (R2-DEC-031) on the rubric fixed in ``docs/r2/evidence/R2_STORY_DONOR_BASELINE.json``.

Every model-calling donor surface is run in two arms on the same fixture, the same model and the same gateway
(native ``/api/chat``, grammar-constrained, no-CJK pattern, same decoding preset, seeds 300-309): the R2 arm uses
the shipped R2 prompt; the donor arm uses the donor's prompt text verbatim, read from the pinned donor checkout and
checked against the baseline's sha256, plus a Vietnamese-output instruction. Only the prompt differs; output
schema, paragraph bounds, quote verification and patch application are shared (recorded harness deviation).

Surfaces: S01 outline, S02 chapter plan vs Novel Studio, S03 chapter plan vs Shenbi, S04 scene drafting, S05
continuity audit vs Novel Studio, S06 specialist audits vs Shenbi, S07 span repair vs Huohuo, S10 length
normalizing, S11 packaging. S08 and S09 are deterministic and proved by tests.

Verdicts follow the rubric's winning rule. Where a surface has no prose (planning, audits, repair), the rule's
terms are mapped as declared in ``MAPPING`` before any run: the length-window term becomes the surface's success
rate, the defects term its defect measure, and pairwise preference stays where a judge applies. A sample whose
generation fails is scored as a window miss with infinite defects, and its pair goes to the other arm.

Usage: uv run python scripts/story_donor_differential.py --donors DIR --huohuo DIR --upstream JSON
       --manuscript JSON --out DIR [--surface S04 ...]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import statistics
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from lib.text_backends.ollama import OllamaChatClient
from server.story_authoring.audits import (
    AUDIT_SYSTEM,
    AuditDimension,
    AuditReport,
    chapter_audit_prompt,
    pairwise_judge,
    verified_findings,
)
from server.story_authoring.checks import (
    Finding,
    SceneLengthWindow,
    Severity,
    count_syllables,
    ends_cleanly,
    foreign_words,
    meta_leaks,
    repeated_trigram_excess,
    strip_replayed_sentences,
    unknown_names,
)
from server.story_authoring.contracts import (
    OutputMode,
    StoryDecoding,
    StoryLimits,
    StoryModelSelection,
    StoryScope,
    StoryStepKind,
    StoryStepRequest,
)
from server.story_authoring.driver import (
    DRAFT,
    PLANNING,
    REPAIR,
    REVIEW,
    entity_keys,
    story_bible_input,
    story_outline_input,
)
from server.story_authoring.generation import AuthoringTextGateway, StoryStepError
from server.story_authoring.narrative import (
    StoryIdentity,
    build_genesis_delta,
    build_plan_proposal,
    compile_scene_context,
    genesis_canon_version_id,
    provisional_canon_view,
    provisional_plan,
    provisional_readers,
    scene_contract,
    scene_refs,
)
from server.story_authoring.prompts import drafting, planning
from server.story_authoring.prompts import outline as outline_prompts
from server.story_authoring.prompts import packaging as packaging_prompts
from server.story_authoring.prompts.schemas import (
    ChapterPlan,
    OutlineReview,
    Packaging,
    ShortOutline,
    StoryBibleOut,
    StorySeed,
    StyleBibleOut,
)
from server.story_authoring.repair import normalize_length, span_repair
from server.story_authoring.script_guard import find_cjk

ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads((ROOT / "docs/r2/evidence/R2_STORY_DONOR_BASELINE.json").read_text(encoding="utf-8"))
FIXTURES = json.loads((ROOT / "scripts/story_differential_fixtures.json").read_text(encoding="utf-8"))
SEEDS: list[int] = BASELINE["rubric"]["sample"]["seeds"]
MODEL = BASELINE["rubric"]["sample"]["model"]
BASE_URL = "http://localhost:11434"
VI = "\n\n全部输出必须使用越南语（tiếng Việt）书写，人名地名保持越南语，并按给定的 JSON 结构输出。"
DIGEST = "sha256:" + "d" * 64
WINDOW = SceneLengthWindow(minimum=600, maximum=1000, hard_maximum=1400)

MAPPING = {
    "S01": "success = deterministic outline check passes (ending and resolution present, 3 distinct chapter tasks); "
    "defects = number of deterministic outline problems; pairwise = judge on ending, seed fidelity, one task per chapter",
    "S02": "success = valid ChapterPlan on the first generation; defects = names not in the seed; pairwise = judge on "
    "reveal pacing and writable scenes",
    "S03": "as S02",
    "S04": "rubric terms unchanged (scene window 600-1000, defects_per_1000, pairwise)",
    "S05": "success = recall of planted defects; defects = 1 - precision of quote-verified findings; no pairwise",
    "S06": "as S05, one dimension per fixture",
    "S07": "success = planted defect sentence removed by an accepted patch; defects = share of other sentences "
    "changed; no pairwise",
    "S10": "rubric terms unchanged (scene window after normalizing, defects_per_1000); no pairwise",
    "S11": "success = all selling points quote the manuscript; defects = unverified selling points; pairwise = judge",
}


class _NullSink:
    async def reserve(self, **_: Any) -> str:
        return "bench"

    async def dispatched(self, _: str) -> None:
        return None

    async def completed(self, _: str, **__: Any) -> None:
        return None

    async def failed(self, _: str, **__: Any) -> None:
        return None

    async def unknown(self, _: str, **__: Any) -> None:
        return None


# --- donor text ------------------------------------------------------------------------------------


class Donors:
    def __init__(self, donors_dir: Path, huohuo_dir: Path) -> None:
        self._ns = donors_dir / "novel-studio-ai"
        self._shenbi = donors_dir / "shenbi"
        self._huohuo = huohuo_dir
        self.hashes: dict[str, str] = {}

    def _read(self, path: Path, expected: str | None = None) -> str:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if expected is not None and digest != expected:
            raise SystemExit(f"{path}: sha256 {digest} differs from the baseline pin {expected}")
        self.hashes[str(path)] = digest
        return data.decode("utf-8")

    def skill(self, name: str) -> str:
        text = self._read(self._shenbi / "skills" / name / "SKILL.md", _baseline_hash(f"skills/{name}/SKILL.md"))
        return text.split("<!-- END AUTO-GENERATED -->", 1)[-1].strip()

    def ns_template(self, function: str, values: dict[str, str]) -> str:
        source = self._read(self._ns / "src/lib/ai/prompts.ts", _baseline_hash("src/lib/ai/prompts.ts"))
        return _render(_template(source, f"export function {function}("), values, self)

    def ns_constant(self, name: str) -> str:
        source = self._read(self._ns / "src/lib/ai/prompts.ts", _baseline_hash("src/lib/ai/prompts.ts"))
        return _template(source, f"export const {name} = ")

    def ns_pacing(self) -> str:
        return _template(self._read(self._ns / "src/lib/ai/pacing.ts"), "export const LONG_SERIAL_PACING_RULES = ")

    def huohuo_patch_system(self) -> str:
        path = self._huohuo / "workbench-server/src/services/novel/novel-continuity-patch.ts"
        return _template(
            self._read(path, _baseline_hash("workbench-server/src/services/novel/novel-continuity-patch.ts")),
            "const PATCH_SYSTEM = ",
        )


def _baseline_hash(source_path: str) -> str | None:
    for surface in BASELINE["surfaces"]:
        if (
            surface.get("source_path") == source_path
            or str(surface.get("source_path", "")).split("#")[0] == source_path
        ):
            return surface.get("source_sha256")
    for surface in BASELINE["surfaces"]:
        pinned = (surface.get("source_paths") or {}).get(source_path)
        if pinned is not None:
            return pinned
    return None


def _template(source: str, anchor: str) -> str:
    """The first template literal after ``anchor``, verbatim."""
    start = source.index("`", source.index(anchor)) + 1
    end = start
    while True:
        end = source.index("`", end)
        if source[end - 1] != "\\":
            return source[start:end]
        end += 1


def _render(template: str, values: dict[str, str], donors: Donors) -> str:
    text = template.replace("${LONG_SERIAL_PACING_RULES}", donors.ns_pacing())
    for expression, value in values.items():
        text = text.replace("${" + expression + "}", value)
    text = re.sub(r"\$\{continuityContextBlock\([^}]*\)\}", "", text)
    if "${" in text:
        raise SystemExit(f"unrendered donor expression in: {text[text.index('${') : text.index('${') + 60]}")
    return text


# --- model calls -----------------------------------------------------------------------------------


class Bench:
    def __init__(self, gateway: AuthoringTextGateway, selection: StoryModelSelection) -> None:
        self.gateway = gateway
        self.selection = selection
        self.scope = StoryScope(user_id="bench", project_name="bench", actor_id="bench")
        self.calls = 0

    def decoding(self, preset: dict[str, float], seed: int) -> StoryDecoding:
        return StoryDecoding.model_validate({**preset, "seed": seed})

    async def structured[T: BaseModel](
        self, step: str, system: str, prompt: str, model: type[T], preset: dict[str, float], seed: int
    ) -> tuple[T | None, str | None]:
        self.calls += 1
        try:
            output = await self.gateway.generate(
                scope=self.scope,
                request=StoryStepRequest(
                    step_id=step,
                    kind=StoryStepKind.OUTLINE,
                    context_digest=DIGEST,
                    selection=self.selection,
                    system_prompt=system,
                    prompt=prompt,
                    output_mode=OutputMode.STRUCTURED,
                    response_model=model,
                    decoding=self.decoding(preset, seed),
                    max_output_tokens=4096,
                ),
            )
        except StoryStepError as error:
            return None, error.code.value
        return model.model_validate_json(output.text), None

    async def prose(
        self, step: str, system: str, prompt: str, preset: dict[str, float], seed: int, bounds: tuple[int, int]
    ) -> tuple[str | None, str | None]:
        self.calls += 1
        try:
            output = await self.gateway.generate(
                scope=self.scope,
                request=StoryStepRequest(
                    step_id=step,
                    kind=StoryStepKind.SCENE_DRAFT,
                    context_digest=DIGEST,
                    selection=self.selection,
                    system_prompt=system,
                    prompt=prompt,
                    output_mode=OutputMode.PROSE,
                    decoding=self.decoding(preset, seed),
                    max_output_tokens=4096,
                    min_paragraphs=bounds[0],
                    max_paragraphs=bounds[1],
                ),
            )
        except StoryStepError as error:
            return None, error.code.value
        return output.text, None

    async def judge(self, r2: str | None, donor: str | None, criteria: str, seed: int) -> float | None:
        """R2's score in one blind pair: 1 win, 0.5 tie, 0 loss; None when the judgment had no verified reason."""
        if r2 is None or donor is None:
            return None if r2 is None and donor is None else (1.0 if donor is None else 0.0)
        r2_first = seed % 2 == 0
        a, b = (r2, donor) if r2_first else (donor, r2)
        self.calls += 1
        try:
            result = await pairwise_judge(
                self.gateway,
                scope=self.scope,
                selection=self.selection,
                step_id=f"judge-{seed}",
                context_digest=DIGEST,
                decoding=self.decoding(REVIEW, seed),
                text_a=a,
                text_b=b,
                criteria=criteria,
            )
        except StoryStepError:
            return None
        if result.preferred is None:
            return None
        if result.preferred == "tie":
            return 0.5
        return 1.0 if (result.preferred == "A") == r2_first else 0.0


# --- metrics and verdict ---------------------------------------------------------------------------


def prose_metrics(text: str | None, allowed: set[str], window: SceneLengthWindow = WINDOW) -> dict[str, Any]:
    if text is None:
        return {"failed": True, "window_hit": False, "defects_per_1000": math.inf, "cjk": 0, "truncation": 0}
    syllables = count_syllables(text)
    foreign = len(foreign_words(text))
    repetition = repeated_trigram_excess(text) + len(strip_replayed_sentences(text)[1])
    meta = len(meta_leaks(text))
    names = sum(unknown_names(text, allowed).values())
    truncation = 0 if ends_cleanly(text) else 1
    return {
        "failed": False,
        "syllables": syllables,
        "window_hit": window.minimum <= syllables <= window.maximum,
        "cjk": len(find_cjk(text)),
        "foreign_words": foreign,
        "repetition": repetition,
        "meta_leak": meta,
        "unknown_names": names,
        "truncation": truncation,
        "dialogue_lines": sum(1 for line in text.splitlines() if line.lstrip().startswith(("—", "–", "“", '"'))),
        "defects_per_1000": (foreign + repetition + meta + names + 10 * truncation) * 1000 / max(1, syllables),
    }


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    defects = [s["defects_per_1000"] for s in samples]
    return {
        "n": len(samples),
        "failed": sum(1 for s in samples if s.get("failed")),
        "invariant_failures": sum(1 for s in samples if s.get("cjk") or s.get("truncation") or s.get("invalid_final")),
        "success_rate": sum(1 for s in samples if s["window_hit"]) / max(1, len(samples)),
        "median_defects": statistics.median(defects) if defects else math.inf,
    }


def verdict(r2: dict[str, Any], donor: dict[str, Any], preference: float | None) -> str:
    """The rubric's winning rule; ``preference`` is None for surfaces without a judge."""
    if r2["invariant_failures"]:
        return "REGRESSED"
    donor_lost = donor["invariant_failures"] > 0
    defects_ok = r2["median_defects"] <= donor["median_defects"] * 1.10 or (
        r2["median_defects"] == 0 and donor["median_defects"] == 0
    )
    success_ok = r2["success_rate"] >= donor["success_rate"] - 0.10
    preference_ok = preference is None or preference >= 0.40
    parity = donor_lost or (defects_ok and success_ok and preference_ok)
    if not parity:
        return "REGRESSED"
    improved = (
        (
            math.isfinite(r2["median_defects"])
            and r2["median_defects"] <= donor["median_defects"] * 0.80
            and donor["median_defects"] > 0
        )
        or r2["success_rate"] >= donor["success_rate"] + 0.20
        or (preference is not None and preference >= 0.60)
    )
    return "IMPROVED" if improved else "PARITY"


def mean_preference(scores: Sequence[float | None]) -> float | None:
    valid = [s for s in scores if s is not None]
    return sum(valid) / len(valid) if valid else None


# --- shared fixture --------------------------------------------------------------------------------


class Upstream:
    def __init__(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        self.seed = StorySeed.model_validate(data["seed"])
        self.bible = StoryBibleOut.model_validate(data["bible"])
        self.style = StyleBibleOut.model_validate(data["style"])
        self.outline = ShortOutline.model_validate(data["outline"])
        self.plan1 = ChapterPlan.model_validate(data["plan1"])
        self.names, self.locations = entity_keys(self.seed)
        self.allowed = {c.name for c in self.seed.characters} | {loc.name for loc in self.seed.locations}
        self.key_names = {**{k: n for n, k in self.names.items()}, **{k: n for n, k in self.locations.items()}}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _render_outline(outline: ShortOutline | None) -> str | None:
    return None if outline is None else _json(outline.model_dump())


# --- surfaces --------------------------------------------------------------------------------------

type Surface = Callable[["Run"], Awaitable[dict[str, Any]]]


class Run:
    def __init__(self, bench: Bench, donors: Donors, upstream: Upstream, manuscript: list[str]) -> None:
        self.bench = bench
        self.donors = donors
        self.up = upstream
        self.manuscript = manuscript


async def s01_outline(run: Run) -> dict[str, Any]:
    b, up = run.bench, run.up
    donor_system = run.donors.skill("shenbi-short-outline") + VI
    criteria = "dàn ý tốt hơn: kết thúc trọn vẹn giải quyết xung đột trung tâm; trung thành với seed (tên, tuổi, quan hệ, mốc thời gian); mỗi chương một nhiệm vụ riêng"
    r2_samples, donor_samples, prefs = [], [], []
    for seed in SEEDS:
        outline, error = await b.structured(
            f"s01-r2-{seed}",
            outline_prompts.OUTLINE_SYSTEM,
            outline_prompts.outline_prompt(up.seed),
            ShortOutline,
            PLANNING,
            seed,
        )
        first_valid = outline is not None
        if outline is not None:
            review, _ = await b.structured(
                f"s01-r2r-{seed}",
                outline_prompts.OUTLINE_SYSTEM,
                outline_prompts.outline_review_prompt(up.seed, outline),
                OutlineReview,
                REVIEW,
                seed,
            )
            problems = [*outline_prompts.deterministic_outline_problems(outline), *(review.problems if review else [])]
            if problems:
                revised, _ = await b.structured(
                    f"s01-r2v-{seed}",
                    outline_prompts.OUTLINE_SYSTEM,
                    outline_prompts.outline_revision_prompt(up.seed, outline, problems),
                    ShortOutline,
                    PLANNING,
                    seed,
                )
                outline = revised or outline
        donor, derror = await b.structured(
            f"s01-d-{seed}",
            donor_system,
            f"novel.json:\n{_json(up.seed.model_dump())}\n\n请按本技能为这部 3 章短篇生成压缩大纲（含复核与修订后的最终版本）。",
            ShortOutline,
            PLANNING,
            seed,
        )
        for arm, value, err, valid in (
            (r2_samples, outline, error, first_valid),
            (donor_samples, donor, derror, donor is not None),
        ):
            problems = outline_prompts.deterministic_outline_problems(value) if value is not None else ["failed"]
            arm.append(
                {
                    "failed": value is None,
                    "error": err,
                    "schema_valid_first": valid,
                    "window_hit": not problems,
                    "defects_per_1000": len(problems) if value is not None else math.inf,
                    "problems": problems,
                    "output": value.model_dump() if value is not None else None,
                }
            )
        prefs.append(await b.judge(_render_outline(outline), _render_outline(donor), criteria, seed))
    return _result("S01_short_story_shape", r2_samples, donor_samples, prefs)


async def _chapter_plans(run: Run, surface: str, donor_system: str, donor_prompt: str) -> dict[str, Any]:
    b, up = run.bench, run.up
    criteria = "kế hoạch chương 2 tốt hơn: giữ kín điều chưa đến lúc lộ (không hé lộ kết thúc hay bí mật sớm); mỗi cảnh có diễn biến cụ thể viết được; bám dàn ý chương 2; chỉ dùng nhân vật và địa điểm đã có"
    r2_prompt = planning.chapter_plan_prompt(
        chapter_number=2,
        outline=up.outline,
        bible=up.bible,
        character_names=list(up.names),
        location_names=list(up.locations),
        previous_plans=[up.plan1],
    )
    r2_samples, donor_samples, prefs = [], [], []
    for seed in SEEDS:
        mine, error = await b.structured(
            f"{surface}-r2-{seed}", planning.PLANNING_SYSTEM, r2_prompt, ChapterPlan, PLANNING, seed
        )
        donor, derror = await b.structured(
            f"{surface}-d-{seed}", donor_system, donor_prompt, ChapterPlan, PLANNING, seed
        )
        for arm, value, err in ((r2_samples, mine, error), (donor_samples, donor, derror)):
            unknown = (
                sorted(
                    {
                        n
                        for s in value.scenes
                        for n in (s.pov, *s.characters)
                        if planning.resolve_name(n, up.names) is None
                    }
                )
                if value is not None
                else []
            )
            arm.append(
                {
                    "failed": value is None,
                    "error": err,
                    "window_hit": value is not None,
                    "defects_per_1000": len(unknown) if value is not None else math.inf,
                    "unknown_names": unknown,
                    "output": value.model_dump() if value is not None else None,
                }
            )
        prefs.append(
            await b.judge(
                _json(mine.model_dump()) if mine else None, _json(donor.model_dump()) if donor else None, criteria, seed
            )
        )
    return _result(surface, r2_samples, donor_samples, prefs)


async def s02_plan_ns(run: Run) -> dict[str, Any]:
    up = run.up
    prompt = run.donors.ns_template(
        "chapterOutlinePrompt",
        {
            "input.chapterNumber": "2",
            "JSON.stringify(input.volumeOutline ?? {}, null, 2)": _json(up.outline.model_dump()),
            "JSON.stringify(input.arcPack, null, 2)": _json(
                {
                    "chapters": [c.model_dump() for c in up.outline.chapters],
                    "previous_chapter_plan": up.plan1.model_dump(),
                    "characters": [c.name for c in up.seed.characters],
                    "locations": [loc.name for loc in up.seed.locations],
                }
            ),
        },
    )
    system = run.donors.ns_constant("jsonSystemPrompt") + VI
    return await _chapter_plans(run, "S02_hierarchy_and_scene_beats", system, prompt)


async def s03_plan_shenbi(run: Run) -> dict[str, Any]:
    up = run.up
    system = run.donors.skill("shenbi-chapter-planning") + VI
    prompt = (
        f"请为第 2 章生成章节备忘（8 段式）。人类合作者已批准。\n\n# novel.json\n{_json(up.seed.model_dump())}\n\n"
        f"# story bible\n{_json(up.bible.model_dump())}\n\n# outline\n{_json(up.outline.model_dump())}\n\n"
        f"# 上一章备忘\n{_json(up.plan1.model_dump())}"
    )
    return await _chapter_plans(run, "S03_chapter_memo_sections", system, prompt)


async def s04_drafting(run: Run) -> dict[str, Any]:
    b, up = run.bench, run.up
    identity = StoryIdentity(user_id="bench", project_name="bench", run_id="bench")
    now = datetime(2026, 10, 19, tzinfo=UTC)
    bible_input = story_bible_input(up.seed, up.style)
    outline_input = story_outline_input(up.outline, [up.plan1] * 3, up.names, up.locations)
    delta = build_genesis_delta(identity, bible_input, created_by="bench", created_at=now)
    version = genesis_canon_version_id(delta)
    proposal = build_plan_proposal(
        identity, outline_input, canon_version_id=version, created_by="bench", created_at=now
    )
    plan = provisional_plan(proposal, approval_ref="bench", committed_by="bench", committed_at=now)
    readers = provisional_readers(
        identity, bible_input, canon_view=provisional_canon_view(delta), plan=plan, acceptances=[]
    )
    refs = [r for r in scene_refs(outline_input) if r.chapter == 1]
    target = drafting.target_syllables_for(up.plan1.scenes)
    bounds = drafting.paragraph_bounds(target)
    donor_system = run.donors.ns_constant("draftSystemPrompt") + VI
    criteria = "cảnh văn tốt hơn: tiếng Việt tự nhiên, cụ thể, có hành động và lời thoại, không lặp, không lộ chuyện chưa đến lúc, bám đúng bối cảnh"
    r2_samples, donor_samples, prefs = [], [], []
    for index, seed in enumerate(SEEDS):
        ref = refs[index % len(refs)]
        contract = scene_contract(proposal, ref)
        pack = await compile_scene_context(
            readers, identity, ref, contract=contract, canon_version_id=version, plan_version=1, recent_decision_ids=[]
        )
        scene = up.plan1.scenes[ref.scene - 1]
        r2_prompt = drafting.scene_draft_prompt(
            context=drafting.render_context(pack, up.key_names),
            scene=scene,
            plan=up.plan1,
            chapter_number=1,
            scene_number=ref.scene,
            is_last_scene_of_chapter=ref.scene == len(up.plan1.scenes),
            is_final_scene=False,
            target_syllables=target,
            revision_note=None,
        )
        donor_prompt = run.donors.ns_template(
            "chapterDraftPrompt",
            {
                "chapterTargetWords": str(target),
                "JSON.stringify(contextPack, null, 2)": _json(pack.model_dump(mode="json")),
            },
        )
        mine, error = await b.prose(f"s04-r2-{seed}", drafting.DRAFT_SYSTEM, r2_prompt, DRAFT, seed, bounds)
        donor, derror = await b.prose(f"s04-d-{seed}", donor_system, donor_prompt, DRAFT, seed, bounds)
        r2_samples.append({**prose_metrics(mine, up.allowed), "scene": ref.node_id, "error": error, "text": mine})
        donor_samples.append({**prose_metrics(donor, up.allowed), "scene": ref.node_id, "error": derror, "text": donor})
        prefs.append(await b.judge(mine, donor, criteria, seed))
    return _result("S04_drafting_prompt", r2_samples, donor_samples, prefs)


def _scenes(fixture: dict[str, Any]) -> list[tuple[str, str]]:
    return [(f"scene_draft[1,{i + 1}]", text) for i, text in enumerate(fixture["scenes"])]


def _audit_sections(dimension: AuditDimension, fixture: dict[str, Any]) -> tuple[str, str]:
    """The R2 audit prompt split into its instruction head and the shared context sections."""
    prompt = chapter_audit_prompt(
        dimension,
        chapter_number=1,
        chapter_text="\n\n".join(fixture["scenes"]),
        plan=ChapterPlan.model_validate(FIXTURES["plan"]),
        facts=FIXTURES["facts"],
        previous_summary="",
    )
    head, sections = prompt.split("[Sự thật đã khóa]", 1)
    return head, "[Sự thật đã khóa]" + sections


def _score_findings(findings: Sequence[Finding], defects: Sequence[dict[str, str]]) -> tuple[int, int, int]:
    """(true-positive findings, all findings, planted defects found)."""

    def hits(finding: Finding, sentence: str) -> bool:
        quote, target = " ".join(finding.quote.split()), " ".join(sentence.split())
        return bool(quote) and (quote in target or target in quote)

    tp = sum(1 for f in findings if any(hits(f, d["sentence"]) for d in defects))
    found = sum(1 for d in defects if any(hits(f, d["sentence"]) for f in findings))
    return tp, len(findings), found


async def _audit_arms(
    run: Run, surface: str, fixtures: list[dict[str, Any]], donor_for: Callable[[AuditDimension], tuple[str, str]]
) -> dict[str, Any]:
    b = run.bench
    r2_samples, donor_samples = [], []
    for index, seed in enumerate(SEEDS):
        fixture = fixtures[index % len(fixtures)]
        dimension = AuditDimension(fixture["dimension"])
        head, sections = _audit_sections(dimension, fixture)
        donor_system, donor_head = donor_for(dimension)
        arms = (
            (r2_samples, AUDIT_SYSTEM, head + sections),
            (donor_samples, donor_system, donor_head + VI + "\n\n" + sections),
        )
        for arm, system, prompt in arms:
            report, error = await b.structured(
                f"{surface}-{len(arm)}-{seed}", system, prompt, AuditReport, REVIEW, seed
            )
            if report is None:
                arm.append(
                    {
                        "failed": True,
                        "error": error,
                        "fixture": fixture["id"],
                        "tp": 0,
                        "findings": 0,
                        "found": 0,
                        "defects": len(fixture["defects"]),
                    }
                )
                continue
            findings, discarded = verified_findings(report.issues, dimension=dimension, scenes=_scenes(fixture))
            tp, total, found = _score_findings(findings, fixture["defects"])
            arm.append(
                {
                    "failed": False,
                    "fixture": fixture["id"],
                    "tp": tp,
                    "findings": total,
                    "found": found,
                    "defects": len(fixture["defects"]),
                    "discarded_unquoted": discarded,
                    "quotes": [f.quote for f in findings],
                }
            )
    return _pr_result(surface, r2_samples, donor_samples)


def _pr_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(s["tp"] for s in samples)
    total = sum(s["findings"] for s in samples)
    found = sum(s["found"] for s in samples)
    planted = sum(s["defects"] for s in samples)
    precision = tp / total if total else 0.0
    recall = found / planted if planted else 0.0
    return {
        "n": len(samples),
        "failed": sum(1 for s in samples if s["failed"]),
        "invariant_failures": 0,
        "success_rate": recall,
        "precision": precision,
        "median_defects": 1 - precision,
    }


def _pr_result(surface: str, r2: list[dict[str, Any]], donor: list[dict[str, Any]]) -> dict[str, Any]:
    r2_summary, donor_summary = _pr_summary(r2), _pr_summary(donor)
    # precision is a share, so the defects term compares 1 - precision with the rubric's success tolerance
    parity = (
        r2_summary["success_rate"] >= donor_summary["success_rate"] - 0.10
        and r2_summary["precision"] >= donor_summary["precision"] - 0.10
    )
    improved = parity and (
        r2_summary["success_rate"] >= donor_summary["success_rate"] + 0.20
        or r2_summary["precision"] >= donor_summary["precision"] + 0.20
    )
    return {
        "surface": surface,
        "mapping": MAPPING[surface[:3]],
        "verdict": "IMPROVED" if improved else "PARITY" if parity else "REGRESSED",
        "r2": r2_summary,
        "donor": donor_summary,
        "r2_samples": r2,
        "donor_samples": donor,
    }


async def s05_continuity_ns(run: Run) -> dict[str, Any]:
    template = run.donors.ns_template(
        "continuityPrompt",
        {
            "JSON.stringify(input.contextPack, null, 2)": "(见下方各节)",
            "input.draftText": "(见下方 [Chương 1 cần thẩm định])",
        },
    )
    head = template.split("Context Pack：", 1)[0].strip()
    system = run.donors.ns_constant("jsonSystemPrompt") + VI
    fixtures = [f for f in FIXTURES["fixtures"] if f["dimension"] == "CONTINUITY"]
    return await _audit_arms(run, "S05_continuity_review", fixtures, lambda _d: (system, head))


async def s06_audits_shenbi(run: Run) -> dict[str, Any]:
    skills = {
        AuditDimension.CONTINUITY: "shenbi-review-continuity",
        AuditDimension.MEMO_COMPLIANCE: "shenbi-review-memo-compliance",
        AuditDimension.CHARACTER: "shenbi-review-character",
        AuditDimension.ANTI_AI: "shenbi-review-anti-ai",
    }
    texts = {d: run.donors.skill(name) for d, name in skills.items()}
    return await _audit_arms(
        run,
        "S06_specialist_audits",
        FIXTURES["fixtures"],
        lambda d: (texts[d] + VI, "请按本技能审查下面的章节，只报告有原文证据的问题。"),
    )


async def s07_span_repair(run: Run) -> dict[str, Any]:
    b = run.bench
    donor_system = run.donors.huohuo_patch_system() + VI
    fixtures = [f for f in FIXTURES["fixtures"] if f["id"] in ("F1_continuity", "F3_character")]
    r2_samples, donor_samples = [], []
    for index, seed in enumerate(SEEDS):
        fixture = fixtures[index % len(fixtures)]
        text = "\n\n".join(fixture["scenes"])
        findings = [
            Finding(
                d["kind"].upper(), Severity.NARRATIVE_CRITICAL, "scene_draft[1,1]", f"lỗi {d['kind']}", d["sentence"]
            )
            for d in fixture["defects"]
        ]
        others = [
            s
            for s in re.split(r"(?<=[.!?])\s+", text)
            if s and not any(s in d["sentence"] or d["sentence"] in s for d in fixture["defects"])
        ]
        for arm, system in ((r2_samples, None), (donor_samples, donor_system)):
            b.calls += 1
            try:
                outcome = await span_repair(
                    b.gateway,
                    scope=b.scope,
                    selection=b.selection,
                    step_id=f"s07-{len(arm)}-{seed}",
                    context_digest=DIGEST,
                    decoding=b.decoding(REPAIR, seed),
                    text=text,
                    findings=findings,
                    context_block=FIXTURES["facts"],
                    **({"system_prompt": system} if system else {}),
                )
            except StoryStepError as error:
                arm.append(
                    {
                        "failed": True,
                        "error": error.code.value,
                        "fixture": fixture["id"],
                        "tp": 0,
                        "findings": 1,
                        "found": 0,
                        "defects": len(fixture["defects"]),
                    }
                )
                continue
            result = outcome.text
            removed = sum(1 for d in fixture["defects"] if outcome.accepted and d["sentence"] not in result)
            kept = sum(1 for s in others if s in result)
            arm.append(
                {
                    "failed": False,
                    "fixture": fixture["id"],
                    "accepted": outcome.accepted,
                    "reason": outcome.reason,
                    "tp": kept,
                    "findings": len(others),
                    "found": removed,
                    "defects": len(fixture["defects"]),
                    "cjk": len(find_cjk(result)),
                    "text": result,
                }
            )
    return _pr_result("S07_span_local_repair", r2_samples, donor_samples)


async def s10_length(run: Run) -> dict[str, Any]:
    b, up = run.bench, run.up
    donor_system = run.donors.skill("shenbi-length-normalizing") + VI
    scenes = run.manuscript
    long_texts = ["\n\n".join(scenes[i : i + 2]) for i in range(len(scenes) - 1)]
    long_texts = [t for t in long_texts if count_syllables(t) > WINDOW.maximum]
    short_texts = []
    for scene in scenes:
        paragraphs = scene.split("\n\n")
        cut = "\n\n".join(paragraphs[: max(2, len(paragraphs) * 2 // 5)])
        if count_syllables(cut) < WINDOW.minimum:
            short_texts.append(cut)
    cases = [*long_texts[:5], *short_texts[:5]]
    r2_samples, donor_samples = [], []
    for index, seed in enumerate(SEEDS):
        text = cases[index % len(cases)]
        for arm, system in ((r2_samples, None), (donor_samples, donor_system)):
            b.calls += 1
            try:
                outcome = await normalize_length(
                    b.gateway,
                    scope=b.scope,
                    selection=b.selection,
                    step_id=f"s10-{len(arm)}-{seed}",
                    context_digest=DIGEST,
                    decoding=b.decoding(REPAIR, seed),
                    text=text,
                    window=WINDOW,
                    **({"system_prompt": system} if system else {}),
                )
                result: str | None = outcome.text if outcome.accepted else None
                reason = outcome.reason
            except StoryStepError as error:
                result, reason = None, error.code.value
            arm.append(
                {
                    **prose_metrics(result, up.allowed | _names_in(text)),
                    "input_syllables": count_syllables(text),
                    "reason": reason,
                }
            )
    return _result("S10_length_normalizing", r2_samples, donor_samples, None)


def _names_in(text: str) -> set[str]:
    """Names already present in a repair input are allowed in its output; new ones count as defects."""
    return set(unknown_names(text, set()))


async def s11_packaging(run: Run) -> dict[str, Any]:
    b, up = run.bench, run.up
    manuscript = "\n\n".join(run.manuscript)
    donor_system = run.donors.skill("shenbi-short-packaging") + VI
    donor_prompt = (
        f"# 书名（暂定）\n{up.seed.working_title}\n\n# 简介\n{up.seed.premise}\n\n# 全部章节正文\n{manuscript}"
    )
    r2_prompt = packaging_prompts.packaging_prompt(
        manuscript=manuscript, working_title=up.seed.working_title, premise=up.seed.premise
    )
    criteria = "gói giới thiệu tốt hơn: tựa hấp dẫn và đúng truyện; giới thiệu gây tò mò nhưng không tiết lộ kết; điểm hấp dẫn có thật trong truyện"
    r2_samples, donor_samples, prefs = [], [], []
    for seed in SEEDS:
        mine, error = await b.structured(
            f"s11-r2-{seed}", packaging_prompts.PACKAGING_SYSTEM, r2_prompt, Packaging, PLANNING, seed
        )
        donor, derror = await b.structured(f"s11-d-{seed}", donor_system, donor_prompt, Packaging, PLANNING, seed)
        for arm, value, err in ((r2_samples, mine, error), (donor_samples, donor, derror)):
            unverified = packaging_prompts.unverified_selling_points(value, manuscript) if value is not None else []
            arm.append(
                {
                    "failed": value is None,
                    "error": err,
                    "window_hit": value is not None and not unverified,
                    "defects_per_1000": len(unverified) if value is not None else math.inf,
                    "unverified": unverified,
                    "cjk": len(find_cjk(value.model_dump_json())) if value is not None else 0,
                    "output": value.model_dump() if value is not None else None,
                }
            )
        prefs.append(await b.judge(_render_packaging(mine), _render_packaging(donor), criteria, seed))
    return _result("S11_packaging", r2_samples, donor_samples, prefs)


def _render_packaging(packaging: Packaging | None) -> str | None:
    if packaging is None:
        return None
    return _json(
        {
            "titles": [t.title for t in packaging.titles],
            "blurbs": packaging.blurbs,
            "selling_points": [s.point for s in packaging.selling_points],
        }
    )


def _result(
    surface: str, r2: list[dict[str, Any]], donor: list[dict[str, Any]], prefs: list[float | None] | None
) -> dict[str, Any]:
    r2_summary, donor_summary = summarize(r2), summarize(donor)
    preference = mean_preference(prefs) if prefs is not None else None
    return {
        "surface": surface,
        "mapping": MAPPING[surface[:3]],
        "verdict": verdict(r2_summary, donor_summary, preference),
        "r2": r2_summary,
        "donor": donor_summary,
        "pairwise_r2_preference": preference,
        "pairwise_scores": prefs,
        "r2_samples": r2,
        "donor_samples": donor,
    }


SURFACES: dict[str, Surface] = {
    "S01": s01_outline,
    "S02": s02_plan_ns,
    "S03": s03_plan_shenbi,
    "S04": s04_drafting,
    "S05": s05_continuity_ns,
    "S06": s06_audits_shenbi,
    "S07": s07_span_repair,
    "S10": s10_length,
    "S11": s11_packaging,
}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--donors", type=Path, required=True)
    parser.add_argument("--huohuo", type=Path, required=True)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--manuscript", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--surface", action="append", default=[])
    args = parser.parse_args()
    selection = StoryModelSelection.create(
        provider_id="bench", endpoint="ollama-chat", base_url=BASE_URL, model_id=MODEL, has_credential=False
    )
    limits = StoryLimits(input_tokens_max=10**9, output_tokens_max=10**9, wall_clock_max_seconds=10**7)
    gateway = AuthoringTextGateway(
        selection=selection,
        limits=limits,
        client=OllamaChatClient(base_url=BASE_URL),
        sink=_NullSink(),
        keep_alive="30m",
    )
    manuscript = [s["text"] for s in json.loads(args.manuscript.read_text(encoding="utf-8"))["offered"]["scenes"]]
    run = Run(Bench(gateway, selection), Donors(args.donors, args.huohuo), Upstream(args.upstream), manuscript)
    args.out.mkdir(parents=True, exist_ok=True)
    for key in args.surface or list(SURFACES):
        started = time.time()
        calls = run.bench.calls
        result = await SURFACES[key](run)
        result.update(
            {
                "seconds": round(time.time() - started),
                "model_calls": run.bench.calls - calls,
                "donor_hashes": dict(run.donors.hashes),
                "seeds": SEEDS,
                "model": MODEL,
            }
        )
        (args.out / f"{key}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "surface": result["surface"],
                    "verdict": result["verdict"],
                    "r2": result["r2"],
                    "donor": result["donor"],
                    "preference": result.get("pairwise_r2_preference"),
                    "seconds": result["seconds"],
                },
                ensure_ascii=False,
                default=str,
            ),
            flush=True,
        )


if __name__ == "__main__":
    asyncio.run(main())
