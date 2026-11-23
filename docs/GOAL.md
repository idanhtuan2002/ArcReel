# GOAL — the charter (above every other document)

Set 2026-11-23 from the sponsor's own words. Every ADR, plan, rule, frozen document, review and task is subordinate to
this page. Where any of them conflicts with it, this page wins and the conflict is reported to the sponsor the same day.

## The goal (sponsor's words)

> "Ý tưởng ban đầu của tôi chỉ là ghép các phần mà các donor làm tốt nhất lại với nhau … phần viết truyện của donor được
> đánh giá làm tốt nhất thì lấy toàn bộ phần viết truyện đó, phần làm phim của donor nào làm tốt nhất thì cũng lấy
> nguyên toàn bộ phần làm phim của donor đó … việc của chúng ta đơn giản chỉ là kết nối, làm cho chúng hoạt động được
> một cách hiệu quả với nhau như một thể thống nhất." (2026-11-23)
>
> "Chất lượng, chức năng ≥ bản gốc" (09-09); "không xây lại thứ đã có" (09-07); "hệ thống do một mình tôi vận hành"
> (09-07); "tự động hoàn toàn" (11-01, 11-23); "đừng tự vẽ ra thêm nhiều việc phức tạp" (11-23).

## The product

| Form | Made by (whole) | Accepted when |
|---|---|---|
| Story (any genre, Vietnamese) | huohuo-drama novel engine → translation to Vietnamese | the story reads as natural Vietnamese, complete chapters, no Chinese left |
| Drama / narrated film from a story | DramaClaw film pipeline | an episode film is produced with no human step; Vietnamese voices; characters consistent; both reviewers accept or the sponsor accepts by eye |
| Non-fiction and repurposed video | OpenMontage pipelines | (after the drama path) a film of the form is produced with no human step |

## Rules that keep the direction

1. **Take the donor's part whole; only connect and configure.** Changing code inside a donor is allowed only when a
   required model has no substitute, **or to add an interface language the sponsor requires** (amendment
   2026-11-23: Vietnamese UI for DramaClaw), and is recorded in that donor's PORTING notes with the reason.
2. **Build nothing a donor already does.** Our code is: the connector, model configuration, small adapters at a donor's
   model boundary, and post-stages on a donor's output where no donor has the step.
3. **No governance machinery.** No grants, custody, qualification, fences or authority layers. Failures are retried,
   logged and reported; that is all.
4. **A film is the measure.** A task is done when the film (or story) it serves is produced and checked — not when a
   document or a test passes.
5. **Direction questions get a direction answer.** When the sponsor questions direction or speed, the answer names the
   documents and clauses involved and offers Go / Kill / Hold / Recycle — never a process change alone.
6. **The sponsor decides product questions only** (goal, money, publication, direction); the agent decides technical
   choices after research and records them in the plan.

## Tolerances (escalate to the sponsor only when exceeded)

- A milestone of the [assembly plan](r2/ASSEMBLY_PLAN.md) running more than 2× its estimate.
- A required donor code change (rule 1).
- A paid model or a spend above zero.
- Our own code growing beyond the plan's estimate for a milestone by more than 50 %.
