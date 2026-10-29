---
name: teamwork
description: 用户明确输入 `teamwork, N=<数字|?> 任务描述` 时使用：把任务按 Small/Medium/Large 分级，主 Agent 规划派发、跨轮优先复用 Worker、S/M 级由主 Agent 直接汇总（L 级另开全新 Final Agent）、全新独立审核 Agent（默认 1 人，可按任务需要增加）评分出审核报告，按 N 轮迭代并做 Dream-RSI 式审核策略复盘；全程 Markdown 产物落盘，每阶段渲染协作框架图与 i/N 进度。触发词：teamwork、多智能体团队、子 Agent 协作、迭代审核、N=几。
---

# teamwork：多子 Agent 协作 Skill

## 何时启用

- **只在用户明确输入启动命令时启用**：`teamwork, N=<数字|?> <任务描述>`。
- `N` 必填：数字 1–10；`?` 表示由主 Agent 按等级自动决定轮数，并当场告知用户选了多少轮。
- 用户没写这条命令时**不要**启动本流程，按普通任务处理。
- 任务描述必须非空；命令格式错误（缺 N、缺任务）时让用户补全，不启动。

## 跨 Agent 运行时（DSH / Claude Code / 通用）

脚本与协议是运行时无关的，差异只在“怎么派子 Agent”：

| 运行时 | 派发方式 | 跨轮复用方式 |
| --- | --- | --- |
| DeepSeek Harness | `spawn_teammate` 建 durable teammate，或 `subagent` | `send_message` 发给同一 `agent_name` |
| Claude Code | Task 工具起 subagent（无持久会话） | 新 subagent 只读上一轮 `wNN_result.md` + `wNN_artifacts/`，逻辑 id / registry 不变 |
| 其它框架 | 任意支持并行子 Agent 的机制 | 文件即接口：子 Agent 只返回 ≤15 行摘要 + 产物路径 |

`next --json` 会给出每个 worker 的 `agent_name`（带 run 指纹）。没有 durable teammate 的运行时，把它当作**角色标签**写进 subagent prompt 即可，流程与产物完全一致。

## 运行环境（跨平台，先检测）

| 项 | 说明 |
| --- | --- |
| Python | 3.10+；下文命令写 `python3`（Windows 用 `python`） |
| 依赖 | 必需 `PyYAML`；可选 `matplotlib`（缺失时跳过 PNG，`framework.mmd` / `PROGRESS.md` 照常生成） |
| 技能目录 | 本 `SKILL.md` 所在目录；下文用 `$SKILL_DIR` 指代 |
| 默认 run 根目录 | `$TEAMWORK_RUNS_ROOT`，未设置时用 `./teamwork-runs`（相对当前工作目录）；`init --root` 可覆盖 |
| 控制台编码 | Windows 建议 `PYTHONIOENCODING=utf-8`；macOS/Linux 一般无需设置 |
| 状态账本 | `<run>/.teamwork/state.json`（唯一 JSON 例外；其余中间产物都是 Markdown + YAML frontmatter） |
| 图 | `<run>/framework.png`、`framework.mmd`、`PROGRESS.md`；收尾时 `score_trend.png` |

## 启动（只做一次）

1. 识别命令：必须以 `teamwork, N=...` 开头。
2. 建 run：

   ```bash
   export PYTHONIOENCODING=utf-8        # Windows: set PYTHONIOENCODING=utf-8
   export SKILL_DIR="${SKILL_DIR:-.claude/skills/teamwork}"   # DSH 下改成本机技能目录
   python3 "$SKILL_DIR/scripts/orchestrator.py" init --cmd "teamwork, N=2 任务描述" --json
   ```

   后续命令同理：所有 `orchestrator.py` 调用都写成 `python3 "$SKILL_DIR/scripts/orchestrator.py" <子命令>`。

   `N=?` 时 init 不写 n，由分级阶段按等级自动决定。
3. 向用户播报：run_id、等级（分级后补）、轮数（自动模式下说明为什么）、计划子 Agent 数。

## 主循环（每轮都照做）

1. `orchestrator.py next --json`，读 `phase`、`role`、`instruction`、`outputs`、`templates`、`subagents`。
2. 按角色执行该阶段；角色 prompt 见 `references/protocol.md`。
3. 产物必须写到 `outputs` 指定路径，frontmatter 字段按 `references/artifacts.md`。
4. `orchestrator.py advance` 推进；校验失败会 exit 2 → 按 stderr 补产物，**不许绕过或手改状态**。
5. 推进后（advance 会自动渲染）在聊天里贴 `![框架图](<run>\framework.png)` 和状态行。
6. 阶段、角色与关键产物：

| 阶段 | 角色 | 关键产物 |
| --- | --- | --- |
| INIT | 主 Agent | task.md 已生成；直接 advance |
| CLASSIFY | 主 Agent | `00_intake/classification.md`（tier/signals/workers_planned/n_adjust） |
| PLAN | 主 Agent | `01_plans/plan-iter-NN.md`（objective/breakdown/accepted_criteria/risks） |
| DISPATCH | 主 Agent | `01_plans/dispatch-iter-NN.md`（mode/workers[{id,scope,deliverables,acceptance}]） |
| WORKERS | 子 Agent 并行 | `iterations/iter-NN/workers/wNN_result.md` + `wNN_artifacts/` |
| FINAL | S/M：主 Agent 直接汇总；L：全新 Final Agent | `final_result.md` + `run_report.md`；随后 `make-packet` |
| GATE | 主 Agent | `gate.md`：PASS/REWORK（REWORK 必须列 rework_targets，最多 2 次） |
| REVIEW | 全新独立审核 Agent ×k（默认 1） | `review_report_A.md` … `_<k>.md` |
| DREAM | 审核 Agent（做梦模式） | `review_policy/replay_ledger.md`，promote 时写 `vN.md` |
| DONE | 主 Agent | `final_report.md`，然后 `finish` |

7. 轮次自动流转：REVIEW 后若 `current_iter < n` → DREAM → 下一轮 PLAN；否则 DONE。

## 子 Agent 纪律（防自做自评 / 防写冲突）

- **Worker**：跨轮优先复用（同 id 沿用上下文与产物，`workers.registry` 记账）；S/M 级第 2 轮起原则上不新建，确需新建时校验会给 warning；只做 dispatch 里自己的 scope，只写 `iterations/iter-NN/workers/wNN_*`；完成后返回 ≤15 行摘要 + 产物相对路径。文件即接口，不要把全文塞回主上下文。**物理 teammate 名称必须用 `next` 输出里的 `agent_name`（带本任务指纹）**；同一对话里其它任务有各自命名空间，禁止挪用别任务的 Worker/上下文。
- **人数**：S 1–2、M 3–4、L 5–7，L 级 Worker+Final Agent 合计上限 8。**所有人数上限只按「单个任务（单个 run）」计数**：一个对话/上下文里可以有多个任务，每个任务各自拥有自己的 Worker 集合、各自计数、互不占用名额；不要把同一对话里多个任务的 Worker 加总去比 8。审核 Agent 数量不受 8 人上限约束（默认 1；当前实现 A–Z 支持 1–26 位，按迭代次数/任务需要增加，同样按单个任务计数）。
- **Final**：S/M 级由主 Agent 直接汇总（不再开子 Agent）；L 级开 1 个全新 Final Agent。只汇总已有事实，不新增结论、不编造证据；缺失/冲突写入 `unresolved`；需要交付到 run 目录外时在 `delivery` 写绝对路径 + sha256。
- **Reviewer**：全新、独立、不继承上下文；**只准读 `review_packet.md` 及其中的 artifacts**；禁读 `run_report.md`、`iteration_summary.md`、其他评审报告、主 Agent 观点；frontmatter 必须写 `independence_attestation: true`。
- **多评审**：默认 1 人。需要 k>1 时**先问用户确认成本**，再 `orchestrator.py reviewers --count k`；A…k 各自独立、互不可见，脚本合成（平均分，任一 FAIL 即 FAIL，维度最大分歧写进 disagreements）。
- 同一文件同一时刻只允许一个 Agent 写；有依赖的 worker 用 `mode: staged`。

## 审核（详见 `references/review-rubric.md`）

- rubric v0 权重：正确性 30 / 完整性 20 / 证据与可验证性 20 / 鲁棒性 10 / 可维护与可回滚 10 / 成本效率 10。
- 一票否决：无证据断言、虚构证据、答非所问、未运行却声称通过。
- 阈值：<60 FAIL、<85 REVISE、≥85 PASS；多评审取平均，任一 FAIL 即 FAIL。
- 审核报告必须写 errors（文件 + 行/证据）与 optimizations（按收益排序），禁止“整体不错”式空话。

## 复盘 / 做梦（DREAM，Dream-RSI 式）

- 历史迭代桶 = replay world：候选 rubric 变体 ≤3 个，用历史迭代产物**重放打分**，不重新执行任务。
- 晋级门槛：在 ≥2 条历史迭代上不差于当前版本、不低于噪声下限（5 分）、不触发成本规则（新增检查项要提升区分度）；每次最多改 3 处，且**只改** `review_policy/vN.md`，不改 Worker/Final 的模型与任务。
- 写 `replay_ledger.md`（含本轮 entry）；promote 时写 `vN.md` 且 ledger 里 `decision: promote`。

## 展示与进度（实时）

- 每阶段推进后贴框架图，并输出一行状态：
  `Iteration i/N · Phase 阶段 · Tier 等级 · Workers k · Score s VERDICT · 策略 vX`
- 用户随时可看 `PROGRESS.md`；需要大图时用 `sidebar_open` 打开 run 目录。
- 框架图包含：主 Agent、8 阶段蛇形流程、Worker 池状态、Artifact Store、i/N 角标与分数轨迹。

## 收尾

- DONE：写 `final_report.md`（含分数轨迹）→ `orchestrator.py finish` → 生成 `score_trend.png`。
- 向用户报告：run_dir、各轮分数轨迹、最终 verdict、产物清单、遗留 unresolved。

## 维护命令

- `status` 看阶段；`check` 跑校验；`set-n 3` 改轮数；`set-tier Large "理由"`；`reviewers --count 2`（先问用户）；`stop "原因"` 提前收尾。
- 校验/推进失败一律 exit 2，按提示修复；不要手改 `.teamwork/state.json`。
- 模板在 `assets/templates/`，写文件前先读对应模板。

## 参考

- `references/protocol.md`：角色 prompt 与各阶段细则
- `references/tiers.md`：Small/Medium/Large 判定
- `references/artifacts.md`：目录、frontmatter 字段、hash 规则
- `references/review-rubric.md`：评分、多评审合并、重放晋级
- `references/diagrams.md`：框架图、状态行、PROGRESS 规范
