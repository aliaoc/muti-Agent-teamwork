---
name: teamwork
description: 用户要求用 teamwork 跑任务时使用（`teamwork, N=<数字|?> 任务描述`、`用 teamwork 跑：N=3 …`、`/teamwork:run N=3 …` 均可）：把任务按 Small/Medium/Large 分级，主 Agent 规划派发、跨轮优先复用 Worker、S/M 级由主 Agent 直接汇总（L 级另开全新 Final Agent）、独立审核 Agent 评分（L 级默认双评审，B 专责核验数据来源与引用真伪）、COACH 阶段产出可执行改进条目并按 applies_to 切片下发给 Worker、末轮向用户播报分数与"是否续跑/续几轮"、按 N 轮迭代；全程 Markdown 产物落盘，每阶段渲染协作框架图与 i/N 进度。触发词：teamwork、多智能体团队、子 Agent 协作、迭代审核、N=几。
---

# teamwork：多子 Agent 协作 Skill（v2.0）

## 何时启用

- **只在用户明确要求用 teamwork 时启用**，以下写法等价：`teamwork, N=<数字|?> <任务描述>`、`teamwork，N=3 …`、`用 teamwork 跑：N=3 …`、`/teamwork:run N=3 …`。
- `N` 必填：数字 1–10；`?` 表示由主 Agent 按等级自动决定轮数，并当场告知用户选了多少轮。
- 用户没提出用 teamwork 时**不要**启动本流程，按普通任务处理（哪怕任务看起来适合拆给多 Agent）。
- 任务描述必须非空；命令格式错误（缺 N、缺任务）时让用户补全，不启动。

## 三个时间尺度（先理解这个，再执行）

| 尺度 | 频率 | 改什么 | 谁负责 |
|---|---|---|---|
| 环内 | 每轮 | **做法**（拆分、取证、格式、验证） | COACH + Worker |
| 环间 | 每 run 一次 | 继续还是收尾 | 脚本算数字 + 用户决定 |
| 环外 | 天/周级 | 教训沉淀、规划参数、评分标准 | `sleep.py` / `dream --offline` |

**环内不改评分标准。** rubric 是裁判，裁判不能自己改判罚尺度；尺子演进只在环外、跨 run、带 holdout 发生。
代码负责：分级、门禁、评分合成、引用核验、教练条目切片、轮次建议、证据 sha256。
Agent 负责：语义判断（这条来源是否真支持该结论、这条建议是否真能落地）。

## 运行环境

| 项 | 说明 |
| --- | --- |
| Python | 3.10+；下文命令写 `python3`（Windows 用 `python`） |
| 依赖 | 必需 `PyYAML`；可选 `matplotlib`（缺失时跳过 PNG，`framework.mmd` / `PROGRESS.md` 照常生成） |
| 技能目录 | 本 `SKILL.md` 所在目录；下文用 `$SKILL_DIR` 指代 |
| 默认 run 根目录 | `$TEAMWORK_RUNS_ROOT`，未设置时用 `./teamwork-runs`；`init --root` 可覆盖 |
| 经验库 | `$TEAMWORK_EXPERIENCE_HOME`，默认 `~/.teamwork/experience` |
| 状态账本 | `<run>/.teamwork/state.json`（唯一 JSON 例外） |
| 图 | `<run>/framework.png`、`framework.mmd`、`PROGRESS.md`；收尾时 `score_trend.png` |

## 启动（只做一次）

先确认技能装在哪（下文统一用 `$SKILL_DIR`）：

| 运行时 | `$SKILL_DIR` 典型位置 |
| --- | --- |
| Claude Code 插件 | `<CLAUDE_PLUGIN_ROOT>/skills/teamwork` |
| Claude Code 项目技能 | `<项目>/.claude/skills/teamwork` |
| Claude Code 个人技能 | `~/.claude/skills/teamwork` |
| DeepSeek Harness | `<DSH_HOME>/data/skills/teamwork`（Windows 默认 `D:/apps/deepseek-harness/data/skills/teamwork`） |
| WorkBuddy | `~/.workbuddy/skills/teamwork` |
| 纯 CLI | 仓库内 `./skills/teamwork` |

```bash
export PYTHONIOENCODING=utf-8
export SKILL_DIR="${SKILL_DIR:-./skills/teamwork}"   # 按上表改成实际安装位置
python3 "$SKILL_DIR/scripts/orchestrator.py" init --cmd "teamwork, N=3 任务描述" --json
```

`N=?` 时 init 不写 n，由分级阶段按等级自动决定。
启动后向用户播报：run_id、等级、轮数、评审人数与角色（L 级默认 `A general / B citation`）。

## 主循环（每轮都照做）

1. `orchestrator.py next --json`，读 `phase`、`role`、`instruction`、`outputs`、`subagents`。
2. 按角色执行该阶段；角色 prompt 见 `references/protocol.md`。
3. 产物必须写到 `outputs` 指定路径，frontmatter 字段按 `references/artifacts.md`。
4. `orchestrator.py advance`；校验失败 exit 2 → 按 stderr 补产物，**不许绕过或手改状态**。
5. 推进后贴框架图与状态行（含 `Score` 与建议）。

| 阶段 | 角色 | 关键产物 |
| --- | --- | --- |
| INIT | 主 Agent | task.md 已生成；直接 advance |
| CLASSIFY | 主 Agent | `classification.md`（tier/signals/workers_planned/n_adjust） |
| PLAN | 主 Agent | `plan-iter-NN.md`（含 `addresses_errors`：卡住类别必须正面处理） |
| DISPATCH | 主 Agent | `dispatch-iter-NN.md`（workers + **coach_items 切片**） |
| WORKERS | 子 Agent 并行 | `wNN_result.md` + `wNN_artifacts/`（claims 可带 `sources[]`） |
| FINAL | S/M：主 Agent；L：全新 Final Agent | `final_result.md`（L 级必须登记 `sources[]`）+ `run_report.md`；随后 `make-packet` |
| GATE | 主 Agent | `gate.md`：PASS/REWORK（REWORK 必须列 rework_targets，最多 2 次） |
| REVIEW | 独立审核 Agent ×k | `review_report_A.md`…；L 级 B 写 `citation_audit` |
| COACH | **全新 RSI 教练** | `rsi_report.md`（末轮另有脚本生成的 `iteration_advisory.md`） |
| DONE | 主 Agent | `final_report.md`（`advisory_response` 必填）→ `finish` |

轮次流转：`REVIEW → COACH`；`iter < n` 回 `PLAN`，`iter == n` 进 `DONE`。

## 子 Agent 纪律

- **Worker**：跨轮优先复用（同 id 沿用上下文，`workers.registry` 记账）；S/M 第 2 轮起原则上不新建；
  只做 dispatch 里自己的 scope，只写 `iterations/iter-NN/workers/wNN_*`；返回 ≤15 行摘要 + 产物路径。
  **物理 teammate 名称必须用 `next` 输出里的 `agent_name`（带 run 指纹）**，禁止挪用别任务的 Worker。
- **人数**：S 1–2、M 3–4、L 5–7，L 级 Worker+Final Agent 合计上限 8。**所有上限只按单个 run 计数**；
  同一对话多个任务各自独立计数。审核 Agent 不受 8 人上限约束。
- **Final**：只汇总已有事实，不新增结论；L 级必须把外部来源登记为 `sources[]`（id/url/title/locator/contributed_by），
  否则引用核验会空转。
- **Reviewer A（general）**：全新、独立、只读 `review_packet.md` 及其 artifacts；禁读 run_report/state/其他评审。
  `errors` 用对象格式 `{id, class, located, recurred_from}`；PASS 需每维 ≥2 条 evidence 且至少 3 条指向实质产物。
- **Reviewer B（citation_audit）**：只做引用核验，逐条给 `verified/unverifiable/misattributed/fabricated/stale`，
  100% 覆盖 packet.citations；`verified` 必须带 `method + checked_at + locator`；离线模式禁止判 verified。
- **Coach（RSI）**：全新实例、不继承评审上下文；只读本轮评审与产物；**不评分、不改产物、不派活**；
  条目必须结构化（`from_error/root_cause/action/verification/applies_to`），不得引入 packet 之外的 URL，
  不得提及其他 worker 的产物路径；末轮只产 `advisory_input`。
- 同一文件同一时刻只允许一个 Agent 写；有依赖的 worker 用 `mode: staged`。

## 运行时差异（怎么起子 Agent）

| 运行时 | 起子 Agent | 跨轮复用 |
| --- | --- | --- |
| DeepSeek Harness | `spawn_teammate`（durable，名字用 `next` 给的 `agent_name`） | `send_message` 发给同一 `agent_name`，物理会话保留 |
| Claude Code | `Task` 工具（一次性 subagent） | 沿用同一逻辑 id `wNN`，把上轮 `wNN_result.md` 与 artifacts 路径作为新 Task 的输入（文件交接） |
| WorkBuddy / 其它 | 按其 subagent 机制；没有就用主 Agent 顺序执行并保持产物契约 | 同 Claude Code：逻辑 id + 文件交接 |

无论哪种运行时，状态机只认**逻辑 id 与产物文件**，不认物理会话：换运行时不会改变 run 的合法性。
审核 Agent 每轮都必须是全新实例（独立性），与运行时无关。

## 审核与门禁（详见 `references/review-rubric.md`）

- rubric v0 权重：正确性 30 / 完整性 20 / 证据 20 / 鲁棒性 10 / 可维护 10 / 成本 10。
- 一票否决：无证据断言、虚构证据、答非所问、未运行却声称通过、**虚构来源**。
- 阈值：<60 FAIL、<85 REVISE、≥85 PASS；多评审取平均，任一 FAIL 即 FAIL。
- **分歧 >10 分禁止 PASS**（强制降级 REVISE 并写 `downgrade_reason`）。
- **引用**：`misattributed ≥1` → evidence 封顶 60；`unverifiable >20%` → 不得 PASS。
- **教练命中率**：下一轮 error 标 `recurred_from` 后由脚本计算；某类连续两轮复发 → 标记 `stuck`，
  下一轮 PLAN 必须在 `addresses_errors` 正面回应，COACH 必须在 `escalations` 升级，否则 advance 被拒。

## 末轮建议（仅显式 N）

`iteration == n` 的 COACH 阶段，脚本生成 `iteration_advisory.md`：分数、delta、趋势、短板、建议续跑轮数全部由代码算，
理由由教练写。**主 Agent 必须原样播报三句话**：

> 本轮 **82 分 / REVISE**（较上轮 +4，短板：证据 68）。**建议再迭代 1 轮**：差距 3 分，历史单轮最大提升 6 分。
> 如需继续，运行 `extend --rounds 1`；若就此收尾，遗留项会写入最终报告。

用户决定记进 `final_report.advisory_response: accept|decline`（decline 需 `advisory_reason` ≥10 字），
否则 `finish` 拒绝收尾。续跑用 `orchestrator.py extend <run> --rounds k [--force]`；旧 `final_report.md`
会被归档为 `final_report.iter-NN.md`（append-only）。

## 展示与进度

- 状态行：`Iteration 3/3 · Phase 教练复盘 · Tier Large · Workers 6/6 · Reviewers 2 · Audit A:general/B:citation_audit · Score 82 REVISE · 建议 +1 轮`
- 用户随时可看 `PROGRESS.md`；需要大图时打开 run 目录。

## 收尾

- DONE：写 `final_report.md`（分数轨迹 + `advisory_response`）→ `finish`（生成 `score_trend.png`，并把 run 落库到经验库）。
- 向用户报告：run_dir、各轮分数轨迹、最终 verdict、产物清单、遗留 unresolved、建议与用户决定。

## 维护命令

| 命令 | 作用 |
|---|---|
| `status` / `check` / `next` | 看阶段 / 跑校验 / 打印唯一合法下一步 |
| `set-n 3` / `set-tier Large "理由"` / `reviewers --count 2` | 调整配置（审核开始前） |
| `citation-audit --on/--off --reason "..."` | 开关 L 级引用核验 |
| `coach-show` | 查看教练条目、命中率、卡住类别 |
| `extend --rounds k [--force]` | DONE 后追加轮次 |
| `dream --propose / --approve vN / --rollback vN` | 环外尺子演进 |
| `adopt-policy --version vN` | 把已批准策略采纳进当前 run |
| `stop "原因"` | 提前收尾（保留产物） |

校验/推进失败一律 exit 2，按提示修复；不要手改 `.teamwork/state.json`。

## 经验库（环外，可选但推荐）

```bash
python3 "$SKILL_DIR/scripts/sleep.py" all <run_dir>...   # 落库 + 蒸馏 + 淘汰 + 看板
python3 "$SKILL_DIR/scripts/sleep.py" metrics            # 首轮通过率/命中率/复发率/校准误差
python3 "$SKILL_DIR/scripts/sleep.py" calibrate          # 什么规模配几个人（只报告，不自动改）
```

## 参考

- `references/protocol.md`：各角色 prompt 与阶段细则
- `references/tiers.md`：Small/Medium/Large 判定
- `references/artifacts.md`：目录、frontmatter 字段、hash 规则
- `references/review-rubric.md`：评分、引用核验口径、合并规则、建议规则
- `references/diagrams.md`：框架图、状态行、PROGRESS 规范
