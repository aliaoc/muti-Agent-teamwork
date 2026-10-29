# teamwork 架构说明

本文说明插件 v2.0 的分层结构、状态机、文件即接口协议与扩展点。**运行时行为以 `scripts/orchestrator.py` + `scripts/teamwork_lib.py` + `scripts/rsi_store.py` 为准**，本文只做解释。

---

## 1. 五层结构

```text
┌──────────────────────────────────────────────────────────────────┐
│ 控制层（主 Agent）                                                 │
│   判级 / 规划 / 派发 / 验收 / 终稿播报 / 调参 / 环间决定             │
├──────────────────────────────────────────────────────────────────┤
│ 执行层（Worker 子 Agent，1–7 个/run，可跨轮复用）                    │
│   只写自己的 wNN_artifacts/ 与 wNN_result.md                       │
├──────────────────────────────────────────────────────────────────┤
│ 汇总层（S/M：主 Agent；L：全新 Final Agent）                        │
│   只汇总不新增事实：final_result.md（L 级含 sources[]）+ run_report │
├──────────────────────────────────────────────────────────────────┤
│ 审核层（全新独立审核 Agent 1–26 位；L 级默认 A 通用 + B 引用核验）      │
│   只读 review_packet.md：六维评分 + 一票否决 + 引用逐条核验           │
├──────────────────────────────────────────────────────────────────┤
│ 教练层（RSI 教练，全新实例，环内）                                    │
│   读评审 → 结构化改进条目 → 按 applies_to 切片下发（不评分/不改产物）   │
└──────────────────────────────────────────────────────────────────┘
              ▲ 所有跨层通信只通过 Artifact Store（文件）
              ▼
   环外：经验库（runs/lessons/policies/golden/metrics），由 sleep.py 与 dream 维护
```

设计原则：**文件即接口**。角色之间不通过对话上下文传递事实，只通过 run 目录里的 Markdown 产物传递；每条事实带证据路径与 sha256。

三个时间尺度的职责分离（详见 `docs/RSI-DESIGN.md`）：环内改做法、环间决定是否收尾、环外改尺子。**环内不允许改 rubric**。

---

## 2. 状态机（10 阶段）

```text
INIT
  │
  ▼
CLASSIFY ──► PLAN ──► DISPATCH ──► WORKERS ──► FINAL ──► GATE
                  ▲                    ▲                  │
                  │                    └──── REWORK ◄─────┤
                  │                                       │ PASS
                  │                                       ▼
                  └──────────── COACH ◄─────────────── REVIEW
                                   │ iter < n
                                   ▼ iter == n
                                  DONE ──► final_report.md ──► finish
```

转移规则（`teamwork_lib.advance_run`）：

| 当前 | 条件 | 下一阶段 | 该阶段落库动作 |
|------|------|----------|----------------|
| CLASSIFY | classification 校验通过 | PLAN | 写 tier / n（显式或自动）/ workers.planned；L 级自动设 A+B 双评审 |
| PLAN | plan 校验通过 | DISPATCH | — |
| DISPATCH | dispatch 校验通过（含切片锁） | WORKERS | 记录 workers.ids / agents / registry / reused / new_ids |
| WORKERS | 所有 worker_result 校验通过 | FINAL | — |
| FINAL | final_result + run_report + packet 校验通过 | GATE | 调 make_review_packet（含 citations） |
| GATE | PASS | REVIEW | 重置 rework_count |
| GATE | REWORK（≤2 次） | WORKERS | rework_count += 1 |
| REVIEW | 评审报告 + review_scores 校验通过 | COACH（iter<n）或 DONE | 合成分数、追加 scores 历史、算教练命中率与 stuck_classes |
| COACH | rsi_report 校验通过（末轮另生成 iteration_advisory.md） | PLAN（iter+1） | 记录 coach.history、stuck_classes |
| DONE | final_report 校验通过（含 advisory_response） | — | finish 时落库经验库 |

`check` 与 `advance` 是唯一推进入口；跳阶段、缺产物、算术不一致、锁被违反都会 `exit 2`。

阶段名兼容：旧 state 里的 `DREAM` 在 `load_state` 时迁移为 `COACH`（`PHASE_ALIASES`），历史 run 可继续 resume。

---

## 3. 模块地图

| 文件 | 职责 | 关键接口 |
|------|------|----------|
| `scripts/teamwork_lib.py` | 全部领域逻辑：常量、路径映射、命令解析、各阶段校验、评分合成、引用核验、教练校验、状态读写 | `create_run()`、`advance_run()`、`build_next()`、`validate_*()`、`compute_merged_review()`、`make_review_packet()`、`compute_advisory()`、`agent_name()` |
| `scripts/orchestrator.py` | 命令行外壳：参数解析、错误码、人读输出 | `init/next/status/check/advance/make-packet/merge-review/render/finish/set-n/set-tier/dual-review/reviewers/citation-audit/coach-show/extend/stop/dream/adopt-policy` |
| `scripts/rsi_store.py` | 环外经验库：run 落库、教训蒸馏、指标、规划校准、尺子提案与批准/回滚、golden 反漂移 | `record_run()`、`distill_lessons()`、`metrics()`、`build_proposal()`、`approve()`、`rollback()` |
| `scripts/sleep.py` | 环外"睡眠任务"CLI | `record / distill / retire / metrics / calibrate / all` |
| `scripts/validate.py` | 独立校验器（不推进状态，供调试/CI） | `--phase` 覆盖当前阶段 |
| `scripts/render_text.py` | 无依赖文字产物 | `write_mermaid()`、`write_progress()`、`render_text_assets()` |
| `scripts/render_diagram.py` | 可选 PNG 渲染 | `render_run()`、`render_png()`、`render_score_trend()` |
| `scripts/selftest.py` | 23 阶段端到端自检 | 生成临时 run，覆盖全部门禁与锁 |
| `references/*.md` | 渐进披露文档 | protocol / tiers / review-rubric / artifacts / diagrams |
| `assets/templates/*.md` | 产物模板 | 13 个模板（classification…final_report + rsi_report + review_report_citation + iteration_advisory） |

---

## 4. 文件协议（Artifact Store）

### 4.1 路径生成

`run_paths(run_dir, iteration)` 统一生成路径，避免各脚本各写一套：

```text
00_intake/task.md
00_intake/classification.md
01_plans/plan-iter-NN.md
01_plans/dispatch-iter-NN.md
iterations/iter-NN/workers/wNN_result.md
iterations/iter-NN/workers/wNN_artifacts/...
iterations/iter-NN/final_result.md
iterations/iter-NN/run_report.md
iterations/iter-NN/review_packet.md
iterations/iter-NN/gate.md
iterations/iter-NN/review_report_A.md … _<k>.md
iterations/iter-NN/review_scores.md
iterations/iter-NN/rsi_report.md
iterations/iter-NN/iteration_advisory.md
iterations/iter-NN/iteration_summary.md
review_policy/v0.md
review_policy/vN.md（v1 run 可能残留 replay_ledger.md，仅作兼容读取）
final_report.md / final_report.iter-NN.md
PROGRESS.md
framework.mmd / framework.png / score_trend.png
.teamwork/state.json
```

### 4.2 文件格式

- **Markdown + YAML frontmatter**：机器字段全部在 frontmatter；正文给人读；每个文件带 `schema_version: 1`。
- **state.json**：唯一机器账本，字段见 `references/artifacts.md`（含 `workers{planned,ids,registry,agents,reused,new_ids}`、`review{policy_version,reviewers,roles,citation_audit}`、`scores[]`、`coach{entries,stuck_classes,ineffective}`、`advisory`、`extended`）。
- **append-only**：历史轮次的目录不覆盖；新轮次写 `iter-NN/`；`extend` 归档旧 `final_report.md` 为 `final_report.iter-NN.md`。
- **sha256**：deliverable 与 packet artifact 必带（校验器重算比对）。
- **路径纪律**：run 内写相对路径；交付到 run 外的产物写 `final_result.delivery`（绝对路径 + sha256），不进 `deliverables`。

### 4.3 隔离规则

`make_review_packet()` 生成审核证据包时：

- 只纳入 final_result、报告、worker result 与 artifacts，以及 `citations[]`（来自 `sources[]`，上限 40）；
- `forbidden` 字段明确列出：`run_report.md`、`state.json`、`iteration_summary.md`、其他评审记录、主 Agent 的规划评价；
- 审核报告校验时检查 `inputs_read` 不含违规路径；
- 审核 prompt 明确要求"不要读取 run 目录下除 packet 与列出的 artifacts 之外的文件"。

COACH 与 REVIEW 具有同等独立性：教练不读 `run_report.md`，只读评审报告、`review_scores.md`、上轮 `rsi_report.md` 与上轮 dispatch。

---

## 5. 引用核验链路（L 级）

```text
final_result.sources[]  ──make-packet──►  packet.citations[]（≤40）
                                                │
                                    Reviewer B（citation_audit）
                                                │
                        review_report_B.md: citation_audit{items, coverage}
                                                │
                            advance 合成：覆盖率 100% / 算术一致 / 结构完整
                                                │
                    misattributed≥1 → evidence 封顶 60；unverifiable>20% → 禁 PASS
                    fabricated → 门禁 fabricated_citation（一票否决）
                                                │
                     GATE 后主 Agent 抽样复核 ≥2 条 → gate.citation_spotcheck
```

离线（`mode: offline`）只能判 `unverifiable / misattributed`，不得判 `verified`——离线核验不得让结论 PASS。

---

## 6. 并发与复用

- **派发模式**：`parallel`（无依赖，一次开多个 worker）或 `staged`（有依赖，前序完成后启动后续）。
- **worker 逻辑 id**：`w01…wNN`，在 dispatch 中声明；`state.workers.registry` 记录每个 id 首次出现轮次。
- **跨轮复用**：同一 run 第 2 轮起沿用既有 id（`reused: true`）；物理上：
  - DeepSeek Harness：`spawn_teammate` 首次创建、`send_message` 后续复用（Agent 持久）；
  - Claude Code：Task 子 Agent 不持久，复用 = 相同逻辑 id + 把上轮产物交给新 Task；
  - 两者对状态机透明（只认 id 与产物）。
- **人数上限**：按 run 累计，`registry ∪ 本次 ids` 不得超过等级上限（S 2 / M 4 / L 7，L +Final ≤ 8）；审核人数不占该额度。
- **物理名隔离**：`agent_name()`/`final_agent_name()`/`reviewer_agent_name()`/`coach_agent_name()` 都带 run 指纹，多任务并跑不串号。

---

## 7. 教练条目如何切片下沉

```text
rsi_report.items[].applies_to  ──►  dispatch.workers[].coach_items
        │                                    │
        │                          target 缺失 → 必须写 coach_deferred[{id,reason}]
        ▼                                    ▼
  归属锁（只允许 wNN / plan.step-N / final / main / all）
  切片锁（声明下发但目标 worker 没有 → 报错；静默删除 → 报错）
```

命中率与升级：`state.coach.history[]` 记录每轮条目覆盖的错误与下一轮是否复发，`hit_rate` 由脚本计算；某类错误连续两轮复发 → 进 `stuck_classes`，下一轮 `plan.addresses_errors` 与 `rsi_report.escalations` 必须正面回应。

---

## 8. 扩展点

1. **新领域**：改 `plan/dispatch` 的 worker 划分与 prompt（`references/protocol.md` 的模板），状态机不动。
2. **更严的审核**：改 `review_policy/v0.md` 或 `references/review-rubric.md`；评审人数用 `reviewers --count k`，引用核验用 `citation-audit --on/--off`。
3. **新产物类型**：在 `teamwork_lib` 的 `TEMPLATES` 与对应 `validate_*` 增加字段与校验，并加模板。
4. **新运行时**：实现"启动子 Agent / 回收结果"的适配层，把产物写入契约路径即可；参考 `SKILL.md` 的「运行时差异」表。
5. **CI 集成**：`orchestrator.py check --json` 的退出码可直接当门禁；`selftest.py` 适合作为技能仓库回归测试。
6. **环外策略**：`rsi_store` 的候选与门槛集中在 `_candidate_weights()` 与 `validate_proposal()`，新增正则化在那里加即可（不得绕过 holdout 与噪声下限）。
