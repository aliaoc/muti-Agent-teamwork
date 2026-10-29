# 产物、目录与字段规范

## 目录树

```
<root>/teamwork-runs/<run-id>/
├─ .teamwork/state.json              # 唯一非 Markdown 的内部账本
├─ 00_intake/task.md                 # init 自动生成
├─ 00_intake/classification.md
├─ 01_plans/plan-iter-01.md
├─ 01_plans/dispatch-iter-01.md
├─ iterations/iter-01/
│  ├─ workers/w01_result.md
│  ├─ workers/w01_artifacts/...
│  ├─ final_result.md                # 含 sources[]（L 级必需）
│  ├─ run_report.md
│  ├─ review_packet.md               # make-packet 生成，禁止手改
│  ├─ gate.md
│  ├─ review_report_A.md … _<k>.md   # 每位独立审核各一份（L 级默认 A+B）
│  ├─ review_scores.md               # advance 自动合成，禁止手改
│  ├─ rsi_report.md                  # COACH 产出（教练条目）
│  ├─ iteration_advisory.md          # 末轮，脚本生成，禁止手改
│  └─ iteration_summary.md
├─ review_policy/v0.md
├─ review_policy/replay_ledger.md    # 环外提案镜像（可选）
├─ final_report.md
├─ final_report.iter-NN.md           # extend 时旧报告归档
├─ PROGRESS.md
├─ framework.png / framework.mmd
└─ score_trend.png                   # finish 时生成
```

- 每轮一个 `iter-NN/`；**历史轮只追加不覆盖**，修正用新文件 + 说明，不删旧证据。
- 除 `.teamwork/state.json` 外，中间产物一律 **Markdown + YAML frontmatter**：frontmatter 给脚本校验，正文给人读。
- `extend` 追加轮次时，旧 `final_report.md` 归档为 `final_report.iter-NN.md`（`--force` 才允许覆盖已有归档）。

## 通用约定

- 每个文件都写 `schema_version: 1`（`task.md` 由脚本生成）。
- 路径一律写 run 相对路径（例如 `iterations/iter-01/workers/w01_artifacts/out.md`），必须位于 run 目录内。
- `sha256` 必须是文件真实摘要（64 位小写十六进制）；文件改写后要同步更新。计算：
  `python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" 文件路径`
- 空列表写 `[]`；必填键不能省略；字段类型严格（布尔不要写成字符串）。
- frontmatter 用 `---` 包住，之后空一行写正文标题。

## 各文件字段

### task.md（自动）
`schema_version, command, task, n_mode(auto|explicit), explicit_n, created_at`

### classification.md
| 字段 | 说明 |
| --- | --- |
| `tier` | `Small|Medium|Large` |
| `tier_reason` | 非空，引用 signals 中的具体项 |
| `signals` | `{files:int, external:bool, verifiable:bool, parallel:bool, risk:low|medium|high, user_demand:bool}` |
| `n_adjust` | -1 / 0 / 1；非 0 时必须写 `n_reason` |
| `n_reason` | 调整轮数的理由 |
| `workers_planned` | 1–7，且在该 tier 范围内（人数按单个任务计数；L 级 Worker+Final 合计 ≤8） |
| `user_confirmed` | 可选 bool |

> L 级且引用核验为 `auto` 时，推进 CLASSIFY 会自动把 `review.reviewers` 设为 2、`review.roles` 设为 `{A: general, B: citation_audit}`（若用户显式设过人数则不覆盖）。

### plan-iter-NN.md
| 字段 | 说明 |
| --- | --- |
| `iteration` | 与当前轮一致 |
| `tier` | 当前等级 |
| `objective` | 一句话可验收目标 |
| `breakdown` | `[{desc, assignee: wNN|main}]`，与 `worker_count` 一致 |
| `accepted_criteria` | 可验证的验收标准列表 |
| `risks` | 风险列表；Medium/Large 至少 1 条 |
| `worker_count` | 1–7，且在该 tier 范围内 |
| `alternatives` | 仅 Large 必需：≥2 个备选方案 + 选择理由 |
| `addresses_errors` | **当 `state.coach.stuck_classes` 非空时必填**：`[{class, mitigation}]`，逐条说明计划层怎么治 |

### dispatch-iter-NN.md
| 字段 | 说明 |
| --- | --- |
| `iteration` | 当前轮 |
| `mode` | `parallel` 或 `staged`（staged 时 worker 里写 `dependencies: [wNN]`） |
| `coach_applied` | 本轮决定执行的教练条目 id 列表 |
| `coach_deferred` | `[{id, reason}]`：不下发的条目**必须**写理由，不许静默丢弃 |
| `lessons_applied` | 可选：从经验库检索注入的教训 id |
| `workers` | `[{id:wNN, scope, deliverables:[相对路径], acceptance, coach_items?:[{id, action}], dependencies?}]` |

> `coach_items` 按上一轮 `rsi_report.items[].applies_to` 切片：条目只能下发给它声明的 worker；脚本核对「声明已下发」与「该 worker 的 coach_items」是否一致，并拦截越权下发。

### workers/wNN_result.md
| 字段 | 说明 |
| --- | --- |
| `worker_id` | `w01`… |
| `iteration` | 当前轮 |
| `scope` | 与 dispatch 一致 |
| `status` | `completed|failed|blocked` |
| `deliverables` | `[{path, sha256}]`，completed 至少 1 个 |
| `claims` | `[{text, evidence:[路径]}]`，每条证据必须真实存在 |
| `open_questions` | 列表（可空） |
| `confidence` | `high|medium|low` |

### final_result.md
`iteration, summary, deliverables:[{path,sha256}], coverage:[{requirement,where,status:covered|partial|missing}], sources:[...], unresolved:[]`；可选 `delivery:[{path, sha256}]`，用于已落盘到 run 目录外的交付物（只有实际复制成功后才能写）。

`sources[]` 是 L 级引用核验的唯一输入：

| 字段 | 说明 |
| --- | --- |
| `id` | `S01` 形式，全局唯一（脚本去重） |
| `claim_ref` | 该来源支撑的结论位置（如 `coverage[0]`、`§2.1`） |
| `url` | `https://…` 或 `doi:` / `isbn:` / 内部路径 |
| `title` / `publisher` / `published_at` | 文献元信息 |
| `quote` | 被引用的原文片段（≥ 一行） |
| `locator` | **必填**：摘要/页码/章节/表格号 |
| `contributed_by` | 本轮 worker id（信用可追溯） |

### run_report.md
`iteration, tier, workers:int, highlights:[≥1], issues:[], next_suggestions:[]`

### review_packet.md（自动生成，勿改）
`iteration, tier, task, acceptance, rubric_version, reviewers:int, roles:{A,B…}, artifacts:[{path,sha256}], citations:[...], citation_policy:{required, mode, min_verified_ratio}, forbidden:[...]`

- `forbidden` 一定含 `run_report.md` 与 `state.json`（Reviewer 只准读 packet + artifacts）。
- `artifacts` 由脚本自动收录 final deliverables、worker deliverables 与 worker claims 证据。
- `citations` 来自 `final_result.sources[]`，上限 40 条。

### gate.md
`iteration, verdict:PASS|REWORK, checklist:[{item,pass}], rework_targets:[], citation_spotcheck:[...], note`

- REWORK 时 `rework_targets` 写具体 worker id / 产物。
- `citation_spotcheck`：L 级从 B 的 `verified` 里随机抽 ≥2 条复核，写 `{id, ok, note}`；抽查失败 → B 报告作废重写。

### review_report_A.md（B…k 同理）
| 字段 | 说明 |
| --- | --- |
| `reviewer` | `A`…`Z`（k 位评审各自一份） |
| `role` | `general` / `citation_audit`（必须与 `state.review.roles` 一致） |
| `iteration` | 当前轮 |
| `rubric_version` | 如 `v0` |
| `inputs_read` | 只允许 packet 及其 artifacts；不得出现 run_report/state.json/iteration_summary/其他评审报告 |
| `independence_attestation` | 必须 `true` |
| `dimensions` | 六维 `[{name, weight, score(0-100 整数), evidence:[路径]}]`；`weight` 必须等于当前 rubric |
| `gates_triggered` | 一票否决项列表 |
| `errors` | `[{id, class, located, recurred_from}]`；`class` 必须在 `ERROR_CLASSES` 内 |
| `optimizations` | `[{suggestion, expected_gain}]`，按收益排序 |
| `total` | 与加权计算一致 |
| `verdict` | 与阈值一致（<60 FAIL / <85 REVISE / ≥85 PASS） |
| `citation_audit` | **仅 `citation_audit` 角色**可写：`{mode, coverage, items}` |

PASS 的额外要求（C4）：无 errors、每维 ≥2 条 evidence、≥3 条 evidence 不指向 packet 自身。

### rsi_report.md（COACH）
| 字段 | 说明 |
| --- | --- |
| `iteration` / `tier` | 当前轮 / 等级 |
| `verdict_in` / `score_in` | 必须等于本轮 `review_scores` 的合并结论与总分 |
| `error_taxonomy` | `[{class, count, attributed_to}]`，`attributed_to` 只能是 `wNN`/`plan.step-N`/`final`/`main`/`all` |
| `items` | ≤8 条；每条 `{id:C1, from_error[], root_cause, action, applies_to[], verification, priority}`；`must_fix` ≤3 |
| `escalations` | `[{class, reason}]`；连续两轮复发的类别必须在这里出现 |
| `dream_hints` | 可选：只写建议，环内不改尺子 |
| `rsi_skipped` | 本轮不教练的理由（PASS 轮可跳过，但必须有理由） |
| `advisory_input` | **仅末轮**：`{estimated_gain_next_round(0-30), remaining_gaps[], diminishing, rationale(≥10 字)}` |

### iteration_advisory.md（脚本生成，勿改）
`iteration, n_mode, score, verdict, prev_score, delta, trend, weakest_dimension{name,score}, gap_to_pass, recommendation(continue|stop), recommended_rounds(0-3), expected_gain, rationale, generated_at`

> 手改会被 `check` 逐字段与 `state.advisory` 比对后拒绝。

### review_policy/v0.md（及 vN）
`weights{6 维}, gates[], noise_floor, max_edits_per_iteration`；`validate_policy` 强制：核心门禁不可删、其余只允许 ±10 变动。

### review_policy/replay_ledger.md
环外提案的镜像，字段见 `assets/templates/replay_ledger.md`：`proposal, policy_before, noise_floor, sample{runs,tasks,train,validation,holdout}, baseline{all,train,validation}, candidates[{id,change,weights,edits,replay_score,validation_score,validation_delta,world_scores}], decision(promote|keep), policy_after, reason`

### final_report.md
`run, tier, iterations, trajectory:[{iteration,total,verdict}], outcome, advisory_response`（`advisory_response` 记录主 Agent 对末轮建议的回应：采纳/未采纳 + 理由）

### iteration_summary.md（工作流约定，供下一轮规划读）
`iteration, actions:[], scores:{total,verdict}, next_actions:[]`；正文写本轮做对/做错/下轮改什么（1–2 屏）。

## state.json 字段（只读，不要手改）

`schema_version, run_id, command, task, created_at, updated_at, n_mode, explicit_n, n, tier, tier_reason, current_iter, phase, finished, aborted, workers{planned, ids, registry:{wNN:首次出现轮次}, agents:{wNN:物理 teammate 名}, reused:[], new_ids:[]}, review{policy_version, reviewers, dual_review_approved, roles:{A:general,B:citation_audit}, citation_audit:auto|on|off}, rework_count, scores[{iteration,total,verdict,reviewers,policy_version,dimensions}], coach{entries:[{iteration,items,item_errors,covered,recurred,hit_rate,taxonomy_classes,stuck_classes,escalations,at}], stuck_classes, ineffective}, advisory, advisory_mode, extended, history[{at,event,detail}]`

`phase` 旧值 `DREAM` 会在 `load_state` 时迁移为 `COACH`（历史 run 可继续 resume）。

## 环外经验库（不在 run 目录内）

默认 `~/.teamwork/experience`，可用 `TEAMWORK_EXPERIENCE_HOME` 覆盖：

```
<experience>/
├─ runs/<run_id>.json          # 每个 run 一条结构化记录（分数/错误/教练/引用覆盖率）
├─ lessons/L-YYYYMMDD-NN.md    # 跨 run 蒸馏出的教训
├─ metrics.md                  # 指标看板（首轮通过率/达 PASS 中位轮数/教练命中率…）
├─ proposals/vN.md             # 尺子演进提案
├─ golden/index.json           # golden 集指纹（防漂移）
└─ policies/evaluator/vN.md    # 已批准的评估器版本 + CURRENT 指针
```

## 校验与排错

- `advance` / `check` 校验失败 → exit 2，stderr 给出缺哪个文件/字段；补齐后重跑同一命令即可。
- 不要手改 `state.json` 来跳过阶段；阶段推进只由 `advance` 写。
- `make-packet` 生成 packet 后，审核前不要改 final_result/artifacts，否则 packet 里的 sha256 会不一致。
- COACH 阶段报「escalations 缺 X」→ 说明 X 类错误连续两轮复发，必须在 `rsi_report.escalations` 升级，同时下一轮 `plan.addresses_errors` 要写处理办法。
- DISPATCH 报「coach_items 里没有」→ 该条目 `applies_to` 声明了某 worker，但该 worker 的切片里没写；补上或移到 `coach_deferred` 并写理由。
