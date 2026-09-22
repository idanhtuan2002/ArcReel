# ArcReel

AI 视频创作平台，将小说、剧本或创作构想转化为短视频。三层结构：`frontend/`（React SPA）→ `server/`（FastAPI，`agent_runtime/` 封装 Claude Agent SDK）→ `lib/`（核心库）。内嵌创作 Agent 的配置源在 `agent_runtime_profile/`，与开发态 `.claude/` 分离。

## 工具链与校验

后端使用 `uv`，前端与文档站使用 `pnpm`。修改代码或测试时，先按 `CONTRIBUTING.md`「测试选择」运行相关测试；任务完成和 push 前执行受影响域的全量闸门：

```bash
uv run ruff check . && uv run ruff format . && uv run basedpyright --warnings && uv run lint-imports && uv run deptry lib server alembic scripts tests r2 && uv run python -m pytest -n 4 --dist loadfile
uv run python scripts/audit_tests.py --check   # 改动测试文件时；同时扫后端 tests/ 与前端 *.test.*
uv run pre-commit run --all-files actionlint && uv run pre-commit run --all-files zizmor   # 改动 .github/ 时
(cd frontend && pnpm check)
(cd website && pnpm check)
```

相关测试必须实际运行且通过；若选择结果为 0 个测试，须扩大范围。启动开发服务器、数据库迁移、测试选择与规范（分层/替身/判据/闸门）、分支与提交规范、依赖管理、注释规范、静态工具的豁免规范见 `CONTRIBUTING.md`。

## 通用规范

- 面向用户的文本须同步添加全部已支持语言的翻译 key（语言清单以 `frontend/src/i18n/` 为准，由 `tests/unit/lib/i18n/test_i18n_consistency.py` 校验）。例外：卡片与区块顶部的 mono kicker（`SectionCard` / `ChannelCard` / `SectionShell` / `PlaceholderTile` 的 `kicker` 及同款 eyebrow 标签）是 Darkroom 设计语言的一部分，固定英文直接写在组件里，不进 i18n。
- 代码与测试注释仅描述当前行为与约束；变更原因与议题编号写在 commit message / PR 描述中。
- 结构性代码查找（找定义、实现、调用方、依赖关系）默认先用 codebase-memory MCP（`search_graph` / `get_code_snippet` / `trace_path` / `search_code`），grep/Read 只在其不可用或覆盖不足时兜底，不是默认路径。这条规则容易被跳过，动手 grep/Read 前先想一下能不能用 codebase-memory。

## 研究、决策与会话连续性

- **Research-first：**提出或接受架构、产品、供应商、工作流或权限边界决策前，先检查当前 Git/代码/既有 ADR 与计划，再核验一手资料；主动对照相关外部项目、仓库和固定 commit 的实际源码、fixture、能力与缺陷。研究结果须区分事实、推断、未知项和备选方案；研究未完成时不得把候选方案写成已定决策。
- **Reuse-first：**先穷尽可复用的本仓库模块、契约、测试、工具和已调研 donor，再考虑新建；复用必须验证真实调用面、版本 pin、同 fixture 行为和 authority 边界，不把仅规划或未验收的接口当作可用实现。
- **License 不在范围内：**按 sponsor 明确决定，所有 license 调研、判断、证据、建议和 gate 均跳过；license 不得成为设计、复用、review 或 acceptance blocker。
- **Quality-first, quota-efficient：**始终以可达到的最高工作质量为目标，不得因 quota 主动缩小必要研究范围、跳过证据或验证、弱化设计标准或提前下结论。额度只改变工作组织方式：复用已验证证据，使用窄而精确的查询，避免重复读取、重复扫描、无关 full suite 和非必要产物，先完成最高价值的当前 gate，并及早保存可恢复 checkpoint。
- **后台 agent 预算：**默认由主 agent 串行完成；仅当独立研究或 review 明显提高质量时启用至多一个后台 agent，并禁止其继续派生子 agent。用户未明确要求时不做并行 fan-out；quota 紧张时先停止后台 agent，不能以降低研究或验证质量来换额度。
- **进度可恢复：**每个 research、ADR、spec、plan、review 和 commit gate 后，简短报告已完成、证据/结果、当前 blocker 与下一步。长任务或额度接近边界时，先停止新工作，把 exact HEAD、dirty paths、已定决策、已运行命令与结果、未完成 gate 和恢复入口写入仓库内的 durable handoff/evidence，再结束会话。
- **恢复与保全：**继续旧任务时以实时 `git status`、提交历史和 durable handoff 为准，不依赖聊天记忆；保留所有无关 dirty work。提交仅包含当前 scope 的明确文件，未提交工作不得被覆盖、清理或误报为已验收。
- **验证与沟通：**按风险运行最小充分且可复现的验证，避免重复扫描和无关 full suite；任何通过、完成或 acceptance 声明都必须绑定当前 HEAD、实际命令输出和覆盖限制。执行过程中持续更新关键进度，避免到额度耗尽时才汇报。

## 架构

架构总览、扩展新供应商、扩展新工作流阶段：`website/docs/dev/architecture.md`。

## Agent skills

- 议题追踪：GitHub Issues，用 `gh` CLI 操作；Spec 与细分 issue 的约定见 `docs/agents/issue-tracker.md`。
- Triage 标签状态机：`docs/agents/triage-labels.md`。
- 领域文档（`CONTEXT.md` + `docs/adr/`）的使用方式：`docs/agents/domain.md`。

<!-- codex-model-routing:project:start -->
## Codex model routing

- Main agent retains final authority for integration, architecture, acceptance, and any high-risk conclusion.
- Keep the repository's existing stricter background-agent budget: **at most one background agent** unless the user explicitly requests otherwise. Do not recursively spawn subagents.
- Use `gpt-5.6-luna` only for read-only discovery, inventory, log/test summarization, and provisional evidence.
- Use `gpt-5.6-terra` for bounded implementation with explicit ownership and task-relevant verification.
- Use `gpt-5.6-sol` for security/auth, database/migrations/transactions, concurrency/idempotency, cross-module work, public contracts, architecture, release/authority boundaries, critical review, and final acceptance.
- Before structural code changes, follow the repository's codebase-memory-first policy and determine blast radius.
- If a Luna/Terra task stops being bounded, evidence conflicts, verification fails, or risk is unclear, return it to main Sol rather than continuing on the cheaper model.
- If the runtime cannot prove that a reviewer/auditor child is actually using Sol, do not use that child for the final critical review; main Sol performs it.
- `gpt-6-astra` and `gpt-5.3-codex` are intentionally not part of this project's routing policy.
<!-- codex-model-routing:project:end -->
