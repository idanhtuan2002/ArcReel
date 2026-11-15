---
status: accepted
---

# Repairs escalate from a span patch to a scene rewrite to a replan

Decided 2026-11-15 by the main agent with the sponsor ("đồng ý, làm theo đề xuất"), after trial 4.

In trial 4 (`particle-1:free`) chapter 1 was replanned twice, which redrafts the chapter plan and every scene of the chapter; its review alone took 61 calls. One replan note was a pronoun slip: "Linh là nhân vật nữ (sự thật đã khóa), nhưng đoạn văn gọi cô là …". The memo-compliance audit may report any issue under its dimension; every blocking, non-excess `MEMO_COMPLIANCE:*` finding was treated as a missing required change, so the scene was rewritten in each review cycle and the chapter replanned at the seal, never patched.

Donors (pins of `docs/research/2026-11-09-r2-donor-writing-capabilities.md`): huohuo patches spans (`novel-continuity-patch.ts`, the source of `repair.py`'s span repair) and rejects a result outside 0.85–1.15 of the length; shenbi routes a diagnosis to a specialist (`pipeline/revision_router.py` `SPECIALIST_SKILLS`), spot-fixes local issues with patches, regenerates only when the chapter's goal is unmet (`skills/shenbi-chapter-revision/SKILL.md`: "重生不是润色", "不超过 ±15% 长度变化 — 修订不是重写整章"), and keeps the text of scenes the feedback does not name (`pipeline/retry_routing.py`: "未点名场景的正文逐字保留，禁止全档重组").

1. In a review round's first cycle a plan finding gets the span patch every local finding gets; the rest of the scene stays byte-identical. A finding the patch removes was local.
2. When the patch places no fix, or the finding is still there in a later cycle, the scene is rewritten with the editor note (as before); one still there at the seal replans the chapter (as before, at most `PLAN_REPLANS`).
3. The patch attempt counts against the scene's call cap. The classification is by outcome, not by the auditor's label, so a mislabelled slip costs one patch call instead of a chapter.

Not done: keeping unnamed scenes through a replan — a new plan changes the scene list, so its scenes are drafted for it.
