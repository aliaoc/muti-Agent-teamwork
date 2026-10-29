# teamwork 架构说明

本文说明插件的分层结构、状态机、文件即接口协议与扩展点。**运行时行为以 `scripts/orchestrator.py` + `scripts/teamwork_lib.py` 为准**，本文只做解释。

---

## 1. 五层结构

```
┌─────────────────────────────────────────────────────────────┐
│ 控制层（主 Agent）                                            │
│   判级 / 规划 / 派发 / 验收 / 合成最终报告 / 调参              │
├─────────────────────────────────────────────────────────────┤
│ 执行层（Worker 子 Agent，1–7 个/run，可跨轮复用）               │
│   只写自己的 wNN_artifacts/ 与 wNN_result.md                  │
├─────────────────────────────────────────────────────────────┤
│ 汇总层（S/M：主 Agent；L：全新 Final Agent）                    │
│   只汇总不新增事实：final_result.md + run_report.md            │
├─────────────────────────────────────────────────────────────┤
│ 审核层（全新独立审核 Agent 1–26 位）                            │
│   只读 review_packet.md：六维评分 + 一票否决 + errors/优化项     │
├─────────────────────────────────────────────────────────────┤
│ 复盘层（Dream Agent，轮间离线）                                 │
│   历史桶 replay + 审核策略候选 + 晋级判定                       │
└─────────────────────────────────────────────────────────────┘
              ▲ 所有跨层通信只通过 Artifact Store（文件）
```

设计原则：**文件即接口**。任何角色之间不通过对话上下文传递事实，只通过 run 目录里的 Markdown 产物传递；每条事实带证据路径与 sha256。

---

## 2. 状态机

```
INIT
  │
  ▼
CLASSIFY ──► PLAN ──► DISPATCH ──► WORKERS ──► FINAL ──► GATE
                  ▲                    ▲                  │
                  │                    └──── REWORK ◄─────┤
                  │                                       │ PASS
                  │                                       ▼
                  └──────────── DREAM ◄─────────────── REVIEW
                                   │ iter < n
                                   ▼ iter == n
                                  DONE ──► final_report.md
```

转移规则（`teamwork_lib.advance_run`）：

| 当前 | 条件 | 下一阶段 | 该阶段落库动作 |
|------|------|----------|----------------|
| CLASSIFY | classification 校验通过 | PLAN | 写 tier / n（显式或自动）/ workers.planned |
| PLAN | plan 校验通过 | DISPATCH | — |
| DISPATCH | dispatch 校验通过 | WORKERS | 记录 workers.ids 与 agents 映射（registry 累加） |
| WORKERS | 所有 worker_result 校验通过 | FINAL | — |
| FINAL | final_result + run_report + packet 校验通过 | GATE | 调 make_review_packet |
| GATE | PASS | REVIEW | 重置 rework_count |
| GATE | REWORK（≤2 次） | WORKERS | rework_count += 1 |
| REVIEW | 评审报告 + review_scores 校验通过 | DREAM（iter<n）或 DONE | 合成分数、追加 scores 历史 |
| DREAM | ledger 校验通过 + promote 合法 | PLAN（iter+1） | 若 promote 则 policy_version+1 |
| DONE | final_report 校验通过 | — | — |

`check` 与 `advance` 是唯一的推进入口；跳阶段、缺产物、算术不一致都会 `exit 2`。

---

## 3. 模块地图

| 文件 | 职责 | 关键接口 |
|------|------|----------|
| `scripts/teamwork_lib.py` | 全部领域逻辑：常量、路径映射、命令解析、各阶段校验、评分合成、状态读写 | `create_run()`、`advance_run()`、`build_next()`、`validate_*()`、`compute_merged_review()`、`make_review_packet()`、`agent_name()` |
| `scripts/orchestrator.py` | 命令行外壳：参数解析、错误码、人读输出 | 子命令 `init/next/status/check/advance/make-packet/merge-review/render/finish/set-n/set-tier/dual-review/reviewers/stop` |
| `scripts/validate.py` | 独立校验器（不推进状态，供调试/CI） | `--phase` 覆盖当前阶段 |
| `scripts/render_text.py` | 无依赖文字产物 | `write_mermaid()`、`write_progress()`、`render_text_assets()` |
| `scripts/render_diagram.py` | 可选 PNG 渲染 | `render_run()`、`render_png()`、`render_score_trend()` |
| `scripts/selftest.py` | 13 阶段端到端自检 | 生成临时 run，覆盖双评审、REWORK、自动 N、命令格式、复用、兼容性 |
| `references/*.md` | 渐进披露文档 | protocol / tiers / review-rubric / artifacts / diagrams |
| `assets/templates/*.md` | 产物模板 | 10 个阶段产物（classification…final_report） |

---

## 4. 文件协议（Artifact Store）

### 4.1 路径生成

`run_paths(run_dir, iteration)` 统一生成路径，避免各脚本各写一套：

```
00_intake/task.md
00_intake/classification.md
01_plans/plan-iter-01.md
01_plans/dispatch-iter-01.md
iterations/iter-01/workers/w01_result.md
iterations/iter-01/workers/w01_artifacts/...
iterations/iter-01/final_result.md
iterations/iter-01/run_report.md
iterations/iter-01/review_packet.md
iterations/iter-01/gate.md
iterations/iter-01/review_report_A.md
iterations/iter-01/review_scores.md
iterations/iter-01/iteration_summary.md
review_policy/v0.md
review_policy/replay_ledger.md
final_report.md
PROGRESS.md
framework.png / framework.mmd / score_trend.png
.teamwork/state.json
```

### 4.2 文件格式

- **Markdown + YAML frontmatter**：机器字段全部在 frontmatter；正文给人读。
- **state.json**：唯一机器账本（run_id、phase、tier、n、current_iter、workers{planned,ids,registry,agents}、review{policy_version,reviewers}、scores 历史等）。
- **append-only**：历史轮次的目录不覆盖；新轮次写 `iter-NN/`。
- **sha256**：deliverable 与 packet artifact 必带（`sha256` 字段），校验器会重算比对。

### 4.3 隔离规则

`make_review_packet()` 生成审核证据包时：

- 只纳入 final_result、报告、worker result 与 artifacts；
- `forbidden` 字段明确列出：`run_report.md`、`state.json`、`iteration_summary.md`、其他评审记录、主 Agent 的规划评价；
- 审核报告校验时检查 `inputs_read` 不含违规路径；
- 审核 Agent 的 prompt 明确要求"不要读取 run 目录下除 packet 与列出的 artifacts 之外的文件"。

---

## 5. 并发与复用

- **派发模式**：`parallel`（无依赖，一次开多个 worker）或 `staged`（有依赖，前序完成后启动后续）。
- **worker 逻辑 id**：`w01…wNN`，在 dispatch 中声明；state.workers.registry 记录每个 id 使用次数。
- **跨轮复用**：同一 run 第 2 轮起沿用既有 id（`reused: true`）；物理上：
  - DeepSeek Harness：`spawn_teammate` 首次创建、`send_message` 后续复用（Agent 持久）；
  - Claude Code：Task 子 Agent 不持久，复用 = 相同逻辑 id + 把上轮产物交给新 Task；
  - 两者对状态机透明（只认 id 与产物）。
- **人数上限**：按 run 累计，`registry ∪ 本次 ids` 不得超过等级上限；审核人数不在 Worker 额度内。

---

## 6. 扩展点

1. **新领域**：改 `plan/dispatch` 的 worker 划分与 prompt（`references/protocol.md` 的模板），状态机不动。
2. **更严的审核**：改 `review_policy/v0.md` 或 `references/review-rubric.md`；如需多评审，`reviewers --count k`。
3. **新产物类型**：在 `teamwork_lib` 的 `TEMPLATES` 与对应 `validate_*` 增加字段与校验。
4. **新运行时**：实现"启动子 Agent / 回收结果"的适配层，把产物写入契约路径即可；参考 `SKILL.md` 的「跨 Agent 运行时」表。
5. **CI 集成**：`orchestrator.py check --json` 的退出码可直接当门禁；`selftest.py` 适合作为 skill 仓库回归测试。
