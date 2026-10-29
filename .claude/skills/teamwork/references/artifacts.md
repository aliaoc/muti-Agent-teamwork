# 产物、目录与字段规范

## 目录树

```
<root>\teamwork-runs\<run-id>\
├─ .teamwork\state.json              # 唯一非 Markdown 的内部账本
├─ 00_intake\task.md                 # init 自动生成
├─ 00_intake\classification.md
├─ 01_plans\plan-iter-01.md
├─ 01_plans\dispatch-iter-01.md
├─ iterations\iter-01\
│  ├─ workers\w01_result.md
│  ├─ workers\w01_artifacts\...
│  ├─ final_result.md
│  ├─ run_report.md
│  ├─ review_packet.md               # make-packet 生成，禁止手改
│  ├─ gate.md
│  ├─ review_report_A.md … _<k>.md   # 每位独立审核各一份（k 默认为 1）
│  ├─ review_scores.md               # advance 自动合成，禁止手改
│  └─ iteration_summary.md
├─ review_policy\v0.md
├─ review_policy\replay_ledger.md
├─ final_report.md
├─ PROGRESS.md
├─ framework.png / framework.mmd
└─ score_trend.png                   # finish 时生成
```

- 每轮一个 `iter-NN/`；**历史轮只追加不覆盖**，修正用新文件 + 说明，不删旧证据。
- 除 `.teamwork/state.json` 外，中间产物一律 **Markdown + YAML frontmatter**：frontmatter 给脚本校验，正文给人读。

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

### plan-iter-NN.md
| 字段 | 说明 |
| --- | --- |
| `iteration` | 与当前轮一致 |
| `tier` | 当前等级 |
| `objective` | 一句话可验收目标 |
| `breakdown` | `[{desc, assignee: wNN|main}]`，与 `worker_count` 一致 |
| `accepted_criteria` | 可验证的验收标准列表 |
| `risks` | 风险列表；Medium/Large 至少 1 条 |
| `worker_count` | 1–7，且在该 tier 范围内（人数按单个任务计数；L 级 Worker+Final 合计 ≤8） |
| `alternatives` | 仅 Large 必需：≥2 个备选方案 + 选择理由 |

### dispatch-iter-NN.md
| 字段 | 说明 |
| --- | --- |
| `iteration` | 当前轮 |
| `mode` | `parallel` 或 `staged`（staged 时 worker 里写 `dependencies: [wNN]`） |
| `workers` | `[{id:wNN, scope, deliverables:[相对路径], acceptance}]`，数量在该 tier 范围 |

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
`iteration, summary, deliverables:[{path,sha256}], coverage:[{requirement,where,status:covered|partial|missing}], unresolved:[]`；可选 `delivery:[{path:绝对或相对路径, sha256}]`，用于已落盘到 run 目录外的交付物（只有实际复制成功后才能写）。

### run_report.md
`iteration, tier, workers:int, highlights:[≥1], issues:[], next_suggestions:[]`

### review_packet.md（自动生成，勿改）
`iteration, tier, task, acceptance, rubric_version, reviewers:int, artifacts:[{path,sha256}], forbidden:[...]`；`reviewers` 默认 1，可到 26；`forbidden` 一定含 `run_report.md` 与 `state.json`（Reviewer 只准读 packet + artifacts）；artifacts 由脚本自动收录 final deliverables、worker deliverables 与 worker claims 证据。

### gate.md
`iteration, verdict:PASS|REWORK, checklist:[{item,pass}], rework_targets:[], note`；REWORK 时 rework_targets 写具体 worker id / 产物。

### review_report_A.md（B…k 同理）
| 字段 | 说明 |
| --- | --- |
| `reviewer` | `A`…`Z`（k 位评审各自一份） |
| `iteration` | 当前轮 |
| `rubric_version` | 如 `v0` |
| `inputs_read` | 只允许 packet 及其 artifacts；不得出现 run_report/state.json/iteration_summary/其他评审报告 |
| `independence_attestation` | 必须 `true` |
| `dimensions` | 六维 `[{name, weight, score(0-100 整数), evidence:[路径]}]` |
| `gates_triggered` | 一票否决项列表 |
| `errors` | 具体错误（文件 + 行/章节） |
| `optimizations` | `[{suggestion, expected_gain}]`，按收益排序 |
| `total` | 与加权计算一致 |
| `verdict` | 与阈值一致（<60 FAIL / <85 REVISE / ≥85 PASS） |

### review_policy/replay_ledger.md
`entries: [{iteration, policy_before, candidates:[{id,change,replay_score}], decision:promote|keep, policy_after, reason}]`；promote 时 `policy_after` 必须是新 `vN` 且 `review_policy/vN.md` 已写好。

### final_report.md
`run, tier, iterations, trajectory:[{iteration,total,verdict}], outcome`

### iteration_summary.md（工作流约定，供下一轮规划读）
`iteration, actions:[], scores:{total,verdict}, next_actions:[]`；正文写本轮做对/做错/下轮改什么（1–2 屏）。

## state.json 字段（只读，不要手改）

`schema_version, run_id, command, task, created_at, updated_at, n_mode, explicit_n, n, tier, tier_reason, current_iter, phase, finished, aborted, workers{planned, ids, registry:{wNN:首次出现轮次}, agents:{wNN:物理 teammate 名}, reused:[], new_ids:[]}, review{policy_version,reviewers,dual_review_approved}, rework_count, scores[{iteration,total,verdict,reviewers,policy_version}], history[{at,event,detail}]`

## 校验与排错

- `advance` / `check` 校验失败 → exit 2，stderr 给出缺哪个文件/字段；补齐后重跑同一命令即可。
- 不要手改 `state.json` 来跳过阶段；阶段推进只由 `advance` 写。
- `make-packet` 生成 packet 后，审核前不要改 final_result/artifacts，否则 packet 里的 sha256 会不一致。
