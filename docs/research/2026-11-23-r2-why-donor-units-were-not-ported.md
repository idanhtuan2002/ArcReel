# Why donor units were studied but not ported whole

Date: 2026-11-23. The sponsor asked why "take the best donor parts whole", agreed many times, is still not applied.
Labels: **FACT** (read here, with source), **INFER**. Companion to the
[donor port audit](2026-11-22-r2-donor-port-audit.md) (what was re-implemented); this note is about why.

## The sponsor's instructions (FACT: session transcripts, user messages)

| Date | Instruction (Vietnamese, quoted) |
|---|---|
| 2026-10-21 | "ưu tiên của chúng ta là tận dụng những gì có sẵn, kể cả áp dụng toàn bộ từ các donor, hạn chế xây dựng mới" |
| 2026-11-08 | "ưu tiên quy tắc tận dụng những gì có sẵn"; "chuyển thể, biên kịch, chia tập.. phải đầy đủ, không thua kém các donor" |
| 2026-11-09 | "rà soát lại phiên bản hiện tại đã kế thừa, bao phủ toàn bộ những gì tốt nhất từ các donor chưa, ví dụ engine viết tiểu thuyết đầy đủ của huohuo, 74 skill của shenbi, nhập file truyện và chia tập của DramaClaw" |
| 2026-11-11 | "so sánh từng bước … với các donor … sửa nếu cách làm, chất lượng sản phẩm của chúng ta không bằng donor" |
| 2026-11-15 | "chuẩn bị để app sẵn sàng với tất cả các hình thức, thể loại … mà các donor hỗ trợ được" |
| 2026-11-16 | "rà soát cả các bản test của các donor … nếu cần có thể sử dụng trực tiếp test từ donor" |
| 2026-11-22 | "khi lấy một phần nào của donor, tại sao chúng ta [không] lấy luôn tất cả các phần có liên quan (cấu hình, các bài test,..)" |
| 2026-11-22 | "app của chúng ta là lấy những phần tốt nhất và giống với các donor nhất" |

## What happened instead (FACT)

1. **Every donor study ended in a mechanism description, not a port list.** The donor research docs of 11-08 … 11-16
   ([stage mechanisms](2026-11-08-r2-donor-stage-mechanisms.md),
   [long novel and skill gaps](2026-11-09-r2-donor-long-novel-and-skill-gaps.md),
   [stage by stage](2026-11-11-r2-donor-stage-by-stage.md),
   [checks and tests gap](2026-11-16-r2-donor-checks-and-tests-gap.md)) cite donor files by line and conclude with
   "ABSENT / parity / defer / adopt", and the ADRs that follow (0112, 0114–0120, 0126–0128, 0134, 0141–0146, 0158)
   implement the behaviour in our own code. Only `vendor/openmontage/remotion-composer` is vendored.
2. **No ADR before 11-22 states why it rewrote instead of porting.** ADR-0119 and ADR-0158 (genre packs) name
   huohuo as the source and contain no reason; the result is ~27 KB of Vietnamese summaries
   (`server/story_authoring/genre_packs.py`) for ~300 KB of huohuo skills (`agent-skills/novel_*`).
3. **A partial port that was decided was not done.** The catalog (2026-11-15, decision 4) says genre packs keep
   "`zh` close to huohuo's original skills"; no `zh` pack content exists.
4. **The 10-21 instruction was never written into a rule or memory.** The repo rule "Reuse-first" (AGENTS.md, since
   2026-09-22) asks to exhaust donors first but sets a verification bar (real call surface, version pin, same-fixture
   behaviour, authority boundary) and never says "port the unit". The rule "Donor 整体移植" and the memory
   `port-donor-units-whole` were written only on 2026-11-22.
5. **The frozen architecture gives donors roles, not code ownership.** `docs/r2/R2_01_FROZEN_ARCHITECTURE.md` §26
   lists each donor's "role" next to an "R2 custom core" that owns authority, context, transactions, routing; §28
   rule 2 forbids a donor store becoming authoritative and rule 7 says "Broad donor research is closed".
   R2-DEC-007: donor context systems "cannot define authoritative visibility rules".
6. **After the 11-22 rule, the ports did not start.** ADR-0168 (DramaClaw identity planner) is still *proposed*;
   the ViMax selectors are not started. 11-22 … 11-23 went to reviewer qualification (ADR-0167, ADR-0169) and to
   fixing the drama smoke run (r2-v2.5.85 … 2.5.87).

## Causes (INFER, from the facts above)

1. **The instruction was translated into a research method, not a delivery rule.** Each "review against the donors"
   produced a better comparison, then a re-implementation of the gap. The output format of the research
   (mechanism + gap) made rewriting the default next step; a port list was never a required output.
2. **The architecture made porting look expensive.** Donor units come with their own stores and frameworks
   (DramaClaw: `sqlite_store`, `cognee`, `pydantic_ai`; huohuo: TypeScript), and the frozen architecture keeps
   authority in our core. Rewriting into our contracts looked smaller than writing a seam, so it was chosen each
   time without being written down as a choice.
3. **Language and stack were accepted as blanket reasons.** huohuo is TypeScript with Chinese prompts, the product is
   Vietnamese first, so prompt packs were rewritten in Vietnamese. That covers the prose of a prompt, not its
   structure, rules and coverage, which could have been carried whole (verbatim `zh`, translated `vi`/`en`).
4. **The agreement did not persist across sessions.** It lived in chat, not in AGENTS.md, memory or an ADR checklist,
   so later sessions (and compactions) worked from the older "Reuse-first" wording.
5. **Unblocking live runs always took priority.** Each session had a production run blocked; fixes to our own
   pipeline were the nearest step, and the ports stayed in "next".

## What would make the rule hold (proposal)

1. An ADR that adopts a donor mechanism has a **Port** section: donor repo @ commit, the files and tests taken, the
   seam written by us; or a **Why not ported** paragraph. A missing section is a review finding.
2. Donor research ends with a **port list** (unit, files, tests, seam, size), not only a gap table.
3. Re-check the shipped re-implementations against that bar, in this order: DramaClaw identity unit (ADR-0168) and
   ViMax selectors; huohuo `agent-skills` verbatim (`zh`) with `vi`/`en` translated from them, replacing the
   summaries; OpenMontage pipelines for the non-fiction and remake forms.
4. Ports go first in the queue once the running smoke film ends, not after the next blocker.
