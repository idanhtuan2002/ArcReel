# Why R2 went off course, and how it stays on course

Date: 2026-11-23, round 2 (deeper). Asked by the sponsor: "we have gone too far from the original expectation; stop
current work, research the whole project, find why it went wrong and how never to go wrong again", then "one more,
deeper round". All work is stopped (run 010a7912 left blocked). Labels: **FACT** (with source), **INFER**.
Companions: [donor ports](2026-11-23-r2-why-donor-units-were-not-ported.md),
[resource waste](2026-11-23-r2-resource-waste-audit.md).

Round 1 dated the "take the donors whole" goal to 10-21 and read the cause as a goal that changed later. The sponsor's
own messages show the goal was there from the second day of R2 and never changed; round 2 corrects this.

## 1. Sources read in round 2

- **Every sponsor message** in the session transcripts: 384 in Codex sessions (`~/.codex/sessions`, main threads
  only, 2026-09-06 … 11-09) and 315 in Claude Code sessions (2026-10-20 … 11-23); 698 after de-duplication.
- The pre-R2 packages (`~/content-os-r1-8/`: R1.8 evaluation, R2-M0 bootstrap that imported the freeze).
- The frozen package (`docs/r2/`), the October reset and its audit, the 09-13 reuse-first research, the 10-30
  expectations assessment, git history since 2026-09-06.

## 2. What the sponsor asked for (FACT: transcripts, verbatim)

The goal is stated the same way from the start:

| Date | Message |
|---|---|
| 09-07 | "mục tiêu của chúng ta là hoàn thành dự án với chất lượng cao nhất, tận dụng triệt để những gì tốt nhất, có sẵn từ các repo, các workflow khác, **không xây lại thứ đã có** … hệ thống do **một mình tôi vận hành**" (answering four architecture questions: "tôi không có câu trả lời cụ thể") |
| 09-09 | "phải đảm bảo việc reuse/merge donor phải có chất lượng, chức năng **≥ bản gốc**" |
| 09-13 | "các lựa chọn có đảm bảo tận dụng được phần tốt nhất từ các donor không, có đảm bảo chất lượng >= bản gốc không" |
| 09-27 | "quy tắc quan trọng nhất của dự án là: tận dụng triệt để những gì có sẵn … đã được áp dụng đầy đủ chưa?" |
| **10-06** | "tôi cảm thấy tiến độ … khá chậm, **dự án của chúng ta đơn giản chỉ là ghép các phần tốt nhất từ các donor lại với nhau**. chúng ta đã có sẵn code của các phần cần ghép … vậy tại sao tiến độ lại chậm như vậy" |
| 10-12 | "ghi nhớ, luôn kiểm tra, tận dụng những gì có sẵn và đạt yêu cầu, trước khi viết bất phần mới nào" |
| 10-21 | "kể cả áp dụng toàn bộ từ các donor, hạn chế xây dựng mới"; "ưu tiên tính tự động trong cách làm của các donor" |
| 11-08 | "chuyển thể, biên kịch, chia tập … phải đầy đủ, không thua kém các donor" |
| 11-10 | "tại sao phải ký quyền có thời hạn, tại sao phải làm nhiều thao tác phức tạp như vậy?" |
| 11-22 | "có phải chúng ta đang đi sai hướng … dự án của chúng ta từ ban đầu chính là ghép những phần tốt nhất của các donor" |

Counted over all 698 messages: the reuse / donor / "≥ the original" goal is restated **20+ times**; "research before
proposing" **8+ times**. 70 messages manage sessions and quota, 18 relay a deploy, 36 paste instructions for another
agent, 23 relay a design review written elsewhere (15 of them in September), 38 approve or confirm a technical choice
(for example 09-09 "xác nhận chọn semantics admission-time currentness + durable handoff-admission receipt").

## 3. What was built instead (FACT)

1. **The foundation came from a separate design process and was imported whole on 09-06.** The R2-M0 bootstrap
   package "copies the approved R2.1–R2.7 freeze artifacts to `docs/r2`". Its vision is an "AI-native Creative
   Production Operating System" with Canon, five authority planes, four human gates and a learning loop
   (`docs/research/r2-origin/00_PRODUCT_VISION.md`); its roadmap says "Implementation proceeds by executable vertical
   milestones, **not by wholesale donor merge**" and invariant 6.3 "**Do not merge donor repositories wholesale**";
   its architecture gives donors roles and the "R2 custom core" authority, lineage, context, transactions, routing
   (§26), and closes broad donor research (§28.7). Neither file has changed since 09-06.
2. **The sponsor's goal was never written into that foundation.** The frozen decision log (R2-DEC-001 … 030) opens with
   ten decisions on authority, Canon and narrative truth; the host is chosen for operations — R2-DEC-011 "ArcReel-derived
   Host … Rationale: R1.8 … PostgreSQL, restart, fault/recovery, idempotency, and backup/restore checks". No decision
   measures film quality, time to a first film, or how much donor code is taken.
3. **Research applied the foundation as its first filter.** The 09-13 reuse-first research opens its gates with an
   *Authority gate* and an *Operational gate* and reads "frozen R2" first (Round A); it concludes, e.g., "Because R2
   uses PostgreSQL authority and M7 durable execution, donor filesystem persistence should not be transplanted".
4. **The October question got a process answer.** The 10-06 message above led to `R2_DELIVERY_RESET_2026-10-06.md`,
   which found the cause ("treating many internal custody and authority increments as separate completion points") and
   then stated it "changes the delivery workflow, **not the frozen architecture, authority contracts, release gates**".
   October went on to M8–M12 authority packets.
5. **The 10-30 expectations assessment measured against the frozen vision** ("North Star … Canon … provenance …
   human decision rights"), not against "ghép các phần tốt nhất, chất lượng ≥ donor". It found gaps in "quality and
   end-to-end experience" and proposed more work inside the same frame.
6. **Where the effort went** (1 981 commits since 09-06): 764 docs-only (39 %); 726 on governance, authority,
   custody, grants, fences, attestation, lineage, Canon, acceptance, review, evidence or qualification; 152 on media,
   film, render, video or TTS. `r2/` 45 198 lines + `server/production_run/` 12 763; tests 344 965 lines;
   162 ADRs, 147 research notes, 301 evidence files. First automatic film 11-08 (REWORK); 91 releases 11-10 … 11-23,
   44 % repairing the run-governance layer.
7. **The same pattern in the last two days**: the first donor unit taken whole (DramaClaw's identity planner) passed
   its 113 tests unchanged, then — fed by our own cast extraction — produced an empty appearance, Chinese identity
   names, and a second character who was never registered (run 010a7912).

## 4. Why (INFER from §2–§3, ordered by weight)

1. **The written goal and the sponsor's goal were two different things, and the written one won.** The foundation
   (an authority-first production OS) was imported as frozen authority; the sponsor's goal (assemble the donors' best
   parts, quality ≥ donor, one operator) lived only in chat. Agents are instructed to respect frozen authority and
   "authority 边界" (AGENTS.md), so a chat instruction was always applied *within* the frozen frame: "reuse" became
   "port behaviour into our contracts", "automatic" became grants and preflights around human gates.
2. **Every check measured against the frozen frame.** Research gates, external design reviews (relayed by the
   sponsor), acceptance packets and the 10-30 assessment all asked "is it correct under R2's authority model?"; none
   asked "is it the donor's best part, at donor quality, with less of our own code?". The reviews therefore produced
   more authority rigour (September: 15 relayed reviews, each with blockers), not less code.
3. **The decision that could have corrected course was answered at the wrong level.** On 10-06 the sponsor named the
   cause; the reset fixed the workflow and explicitly kept the architecture. Nobody (the agents included) offered to
   reopen the freeze, because the frozen rules say the freeze stands until an explicit architecture-change approval —
   which only the sponsor can give and was never asked for.
4. **The sponsor was used as an approver of technical semantics and a message relay** (38 technical confirmations,
   23 relayed reviews, 36 pasted agent instructions, 70 session/quota messages), while the product goal had no
   owner in the process.
5. **No product yardstick until 11-08.** Progress was counted in milestones and accepted packets; a film was first
   produced two months in, and nothing compared it with what a donor produces from the same story.
6. **The host was chosen for operational robustness, not for the product.** DramaClaw — a complete drama pipeline —
   was assigned "Creative Canvas"; ArcReel's queue and artifact machinery became the core, and the film pipeline was
   rebuilt around it.
7. **Agent behaviour amplified it**: goals restated 20+ times were not kept across sessions; fixes were local; until
   today's hooks, rules depended on memory.

## 5. What keeps it from happening again

Mechanisms, each answering a cause above.

1. **One goal charter above every other document** (cause 1). `docs/GOAL.md`, in the sponsor's words: "ghép những
   phần tốt nhất của các donor; chất lượng, chức năng ≥ bản gốc; không xây lại thứ đã có; tự động; một người vận
   hành". Every frozen document, ADR, rule and review is subordinate; where one conflicts, the charter wins and the
   conflict is reported the same day. The per-turn hook prints the charter's first line.
2. **The donor is the yardstick** (causes 2, 5). For each form, the baseline is the donor's own output on the same
   story (for drama: DramaClaw end to end). A change is done when our film is at least as good on that story (same
   reviewers plus the sponsor's eye), and its share of our own code is stated. Reviews and research are asked that
   question first; authority correctness comes second.
3. **Reopening is a standing duty** (cause 3). When the sponsor questions direction or speed, the agent's first answer
   names the frozen clauses involved and asks whether to reopen them — never a workflow change alone.
4. **The sponsor decides product questions only** (cause 4). Technical semantics are decided by the agent after
   research and recorded; the sponsor is asked about goals, money, publication and direction. Reviews are run by the
   agent, not relayed.
5. **Rules in hooks, not memory** (cause 7; in place): codebase-memory first; `Donor:`/`Consumers:` in code commits;
   per-turn reminder; run block ledger; donor research ends in a port list.
6. **Re-foundation decision** (cause 6). Before any new work: run the donor baseline (DramaClaw on
   "Chiếc đồng hồ của ông"), then research with that evidence the options — (a) keep the R2 core and port units;
   (b) each form runs on a donor pipeline taken whole (DramaClaw for drama, OpenMontage for non-fiction,
   huohuo for novels) with ArcReel/R2 as the shell (settings, accounts, run panel, storage); (c) a mix — judged by
   film quality against the baseline, time to it, recurring cost and how much of our own core survives.
