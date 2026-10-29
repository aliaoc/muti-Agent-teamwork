# teamwork 协议细则

## 总则

1. **文件即接口**：Agent 之间只通过 run 目录里的文件传递产物；每次回复只给摘要（≤15 行）+ 产物相对路径 + 未决问题，不把全文塞回主上下文。
2. **主 Agent 是唯一调度者**：子 Agent 不互相直接通信；没有 dispatch 明确声明的依赖时，Worker 不读其他 Worker 的目录。
3. **写作用域**（同一文件同一时刻只允许一个 Agent 写）：
   - Worker：`iterations/iter-NN/workers/<wid>_artifacts/` 与 `<wid>_result.md`
   - Final：L 级写 `iterations/iter-NN/final_result.md`、`run_report.md`；S/M 级由主 Agent 直接写这两个文件
   - 主 Agent：`00_intake/`、`01_plans/`、`gate.md`、`final_report.md`、命令产生的文件
   - Reviewer：`review_report_<X>.md`（X=A…k，k 位评审各自一份，互不可见）
   - Coach：`iterations/iter-NN/rsi_report.md`（只写这一个文件；advisory 由脚本生成）
   - 环外：`$TEAMWORK_EXPERIENCE_HOME/` 下的经验库、教训、提案（不在 run 目录内）
4. **路径**：frontmatter 里的交付物/证据路径写 run 目录相对路径；校验会拒绝越界或不存在（`sha256` 只认文本内容，不算路径）。
5. **失败不伪造**：Worker 失败写 `status: failed|blocked` + `open_questions`，由主 Agent 决定重派/降级；禁止把未完成写成 completed。

## 阶段细则

### INIT（主 Agent）

- `orchestrator.py init` 已生成 `00_intake/task.md`、`review_policy/v0.md`、`.teamwork/state.json`，并渲染首张 `framework.png` / `PROGRESS.md`。
- 直接 `advance` 进入 CLASSIFY，不需要额外产物。

### CLASSIFY（主 Agent）

- 按 `references/tiers.md` 判断 Small/Medium/Large，写 `00_intake/classification.md`。
- `N=?` 时用 `n_adjust`（-1/0/+1）从 `TIER_DEFAULT_N` 调整轮数，并在 `n_reason` 写理由；必须当场告诉用户最终轮数。
- `workers_planned` 必须落在该等级范围（Small 1–2 / Medium 3–4 / Large 5–7，L 级 Worker+Final 合计 ≤8），本次 run 由主 Agent 决定。**人数上限按单个任务（单个 run）计数**；同一对话中的其它任务各自计数、互不占用。
- 第 2 轮起优先复用已有 Worker（同 id 沿用），S/M 级原则上不新建；确需新增时校验会给出 warning，请在 plan/正文说明理由。
- 审核人数默认 1；按任务要求可增至 k（框架支持 1–26），k>1 时先向用户说明成本并确认。
- **L 级引用核验**：tier=Large 且 `citation_audit != off` 时，脚本自动把评审设为 2 位并写
  `roles = {A: general, B: citation_audit}`。若用户事先显式只设 1 位评审，则尊重用户、等价于关闭核验。
  成本要一次性播报（不阻塞询问）："L 级默认双评审，B 专责引用核验；如需关闭请说'关闭引用核验'"。
- 可选 `user_confirmed: true`（Large 且规划后要用户确认时）。
- `advance` 后 state 落库 `tier`、`n`、`workers.planned`、`review.roles`。

### PLAN（主 Agent）

- 第 2 轮起先读上一轮 `iteration_summary.md` / `review_report_A.md` / 当前 `review_policy/vN.md`。
- 写 `01_plans/plan-iter-NN.md`：`objective`、`breakdown`（assignee 用 `wNN` 或 `main`）、`accepted_criteria`（可验证）、`risks`（Medium/Large 至少 1 条）、`worker_count`。
- Large 追加 `alternatives`：≥2 个方案对比 + 选择理由（写 frontmatter 列表或正文均可）。
- 第 2 轮起必须读上一轮 `rsi_report.md` 的 `error_taxonomy`（谁该为错误负责）；
  归到 `plan.step-N` 的，要改拆分，不是让 worker "注意一下"。
- 若 `state.coach.stuck_classes` 非空（某类错误连续两轮复发），必须写 `addresses_errors`：
  `[{class, mitigation}]`，逐条说明计划层怎么改；漏一条 `advance` 直接 exit 2。
- 给用户 3–8 行计划摘要；Large 默认在派发前请用户确认（用户已授权自动执行时除外）。

### DISPATCH（主 Agent）

- 把 `plan.breakdown` 映射成 worker 任务卡：`id`、`scope`（只做这些）、`deliverables`（相对路径清单）、`acceptance`。
- 复用策略：优先沿用 `state.workers.registry` 里已有的 Worker id（同 scope/上下文）；S/M 第 2 轮起原则上不新建 id，确需新建时在 dispatch 正文写理由。
- **累计硬上限**：本任务（run）累计不同 worker id 数不得超过该等级上限（S 2 / M 4 / L 7，L 级 +Final=8）；跨轮复用同一 id 不重复计数。校验会在超限时报错；同一对话的多个任务各自独立计数。
- 无依赖 → `mode: parallel`；有依赖 → `mode: staged`，并在对应 worker 写 `dependencies: [wNN, ...]`。
- `deliverables` 路径必须在 `iterations/iter-NN/workers/wNN_artifacts/` 下。
- **教练切片**（第 2 轮起）：上一轮 `rsi_report.items` 的每一条，要么出现在某个 worker 的
  `coach_items`（按 `applies_to` 命中），要么出现在 `coach_deferred` 并写 `reason`；
  不能删除。给 wNN 的条目里不得出现其他 worker 的 id/产物路径（隔离）。
  脚本逐条核对覆盖、越权、串号，任一违反 exit 2。
- `advance` 后 `state.workers.ids` 更新，同时维护 `registry`（首次出现轮次）、`agents`（逻辑 id → 物理 teammate 名）、`reused`、`new_ids`；下一阶段按 ids 起子 Agent。

### WORKERS（并行子 Agent）

- 按 `state.workers.ids` 起 Worker：**优先复用**已有 Worker（同 id、保留其上轮上下文），S/M 级第 2 轮起原则上不新建；只有确需新 id 时才新开 subagent（dispatch 里应说明理由）。
- 运行时差异：Claude Code 的 Task 子 Agent 是一次性的，“复用”指沿用同一逻辑 id、把上轮 result 与 artifacts 路径交给新 subagent（文件交接），不是恢复会话；只有 DSH 的 durable teammate 才用 `send_message`。
- **命名隔离**：新开 teammate 一律使用 `next` 输出里的 `agent_name`（形如 `tw-<任务指纹>-w01`），不要直接用 `w01` 当物理名；逻辑 id 仍是 `wNN`。复用轮次用 `send_message` 发给同一 `agent_name`。其它任务的 agent 名不可挪用。
- 新 Worker 才需要给全新 prompt（下方模板）；复用 Worker 直接派本轮的 scope/acceptance，并提醒它读自己上轮产物与评审意见。
- 每个 Worker 写 `<wid>_result.md`：deliverables（path+sha256）、claims（每条证据路径，
  外部来源放进 `sources[]`：url/title/publisher/published_at/quote/locator）、open_questions、confidence。
- Worker 只看到属于自己的 `coach_items`；不要向它转述别人的错误或主 Agent 的判断。
- 全部完成后 `advance`；校验会检查状态、deliverable 存在、claims 证据存在。
- 有依赖的 worker 按 staged 顺序起；后一批 worker 可读前一批产物。

### FINAL（S/M：主 Agent 直接汇总；L：全新 Final Agent）

- S/M 级：主 Agent 直接写 `final_result.md` 与 `run_report.md`（不再开子 Agent，也无需 keep-alive 的 Final 上下文）；不得自评。
- L 级：启动 1 个全新 Final Agent，输入 dispatch、全部 `worker_result.md`、worker artifacts 清单。
- 两种模式产物相同：`final_result.md`（summary、deliverables+sha256、coverage[需求→位置→状态]、
  `sources[]`、unresolved，可选 delivery[path,sha256]）与 `run_report.md`（highlights、issues、next_suggestions）。
- **L 级必须登记 `sources[]`**：`id`（S01 起）、`claim_ref`、`url`、`title`、`publisher`、
  `published_at`、`quote`、`locator`、`contributed_by`（必须是本轮 worker）。空 sources 会让引用核验空转，
  脚本会给 warning。来源超过 40 条时 `make-packet` 截断并标 `citations_truncated: true`。
- **不评价质量、不打分**（那是 Reviewer 的事），不改 worker 产物。
- 写完运行 `make-packet` 生成 `review_packet.md`，再 `advance`。

### GATE（主 Agent）

- 主 Agent 自检（不写评审意见）：需求覆盖、证据齐全、计划一致性、产物存在可运行、无阻塞项、无敏感泄漏。
- 写 `gate.md`：`verdict: PASS|REWORK`、`checklist[{item,pass}]`、`rework_targets`、`note`。
- REWORK → 回 WORKERS 重做（脚本限制每轮最多 2 次）；超限就说明原因并决定 PASS 或 `stop`。

### REVIEW（全新独立审核 Agent，默认 1 位，可 k 位）

- 只给每个 Reviewer 一个入口：`review_packet.md`（含任务、验收标准、artifacts 清单、rubric_version、forbidden 列表）。
- 每位 Reviewer 各开一个全新 subagent（互不可见、不继承主 Agent 上下文），用 `review_policy/vN.md` 评分，分别写 `review_report_A.md`、`review_report_B.md`…`_<k>.md`。
- k 由任务要求与迭代次数决定（默认 1；需要多个时先问用户确认成本），`orchestrator.py reviewers --count k` 设定。
- **角色**：`general`（六维通用）与 `citation_audit`（专责引用核验）。角色由 `state.review.roles` 决定，
  报告里的 `role` 必须与之一致，否则 exit 2。B 的模板见 `assets/templates/review_report_citation.md`。
- B 只做引用核验：逐条核验 `packet.citations`，100% 覆盖，写 `citation_audit`（mode/coverage/items）；
  `verified` 必须带 `method + checked_at + locator`；离线模式禁止判 verified。
- `advance` 时脚本自动合成 `review_scores.md`（各评审加权总分平均、合并 verdict、合并维度均分、维度最大分歧）。
  分歧 >10 分时禁止 PASS，强制降级 REVISE 并写 `downgrade_reason`。

### COACH（全新 RSI 教练，不继承评审上下文）

- 位置：`REVIEW` 之后。`iter < n` 时 advance 回 `PLAN` 并 `current_iter += 1`；`iter == n` 时进 `DONE`。
- 读：本轮 `review_report_*.md`、`review_scores.md`、`final_result.md`、`plan-iter-NN.md`、
  `dispatch-iter-NN.md`、artifacts。
- 禁读：`run_report.md`、`.teamwork/state.json`、历史轮评审、主 Agent 的解释。
- 写：只写 `iterations/iter-NN/rsi_report.md`；末轮追加 `advisory_input`（advisory 文件由脚本生成）。
- 结构：`error_taxonomy`（class × count × attributed_to）+ ≤8 条 `items`（must_fix ≤3），
  每条 `from_error / root_cause / action / applies_to / verification`。
- 三条硬约束（代码校验）：不评分/不改产物/不派活；不引入 packet 之外的 URL；不提及他人产物路径。
- 命中率：本轮 review 的 `errors[].recurred_from` 指向上一轮 error id，脚本算"上一轮教练条目覆盖的错误里
  有几条复发"。某类连续两轮复发 → `stuck`，下一轮 PLAN 必须 `addresses_errors`、COACH 必须 `escalations`。
- PASS 轮可跳过（写 `rsi_skipped: 理由`），但文件必须存在；`iter == n` 时不能跳过 advisory_input。

### DONE（主 Agent）

- **先播报末轮建议**（`state.advisory` 或 `iterations/iter-NN/iteration_advisory.md`），三句话：
  分数/结论/短板 → 建议继续还是收尾、几轮 → 理由与下一步命令。
- 写 `final_report.md`（run、tier、iterations、trajectory、outcome、`advisory_response: accept|decline`，
  decline 必须写 `advisory_reason` ≥10 字）→ `finish` 生成 `score_trend.png` 并把 run 落库到经验库。
- 建议续跑但没记录用户决定 → `finish` 直接 exit 2。
- 用户选择继续 → `orchestrator.py extend <run> --rounds k [--force]`（旧 final_report 归档为
  `final_report.iter-NN.md`，`current_iter += 1`，`n = 当前轮 + k`，回到 PLAN）。
- 给用户的收尾报告：run_dir、各轮分数轨迹、最终 verdict、产物清单、unresolved、建议与用户决定。

## Worker

角色 prompt 模板（替换 `{...}`）：

```text
你是第 {iter}/{n} 轮的 Worker {wid}。
任务背景：{task}
你的 scope（只做这些）：{scope}
验收标准：{acceptance}
写作用域：只允许写 <run>/iterations/iter-NN/workers/{wid}_artifacts/ 与 {wid}_result.md；
其他文件（包括别人的 worker 目录、run_report、state.json）一律不读不写。
步骤：
1) 读 <run>/00_intake/task.md、<run>/01_plans/dispatch-iter-NN.md（只看自己条目）。
2) 产出放 wNN_artifacts/；结果 frontmatter 按 assets/templates/worker_result.md，sha256 用
   python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" 文件路径
3) claims 每条必须带真实存在的 evidence 路径。
4) 只回复 ≤15 行摘要：status、产物相对路径、关键结论、未决问题、confidence。
```

## Final

```text
你是本轮 Final Agent（全新上下文，不继承历史；仅 L 级需要，S/M 级由主 Agent 直接汇总）。
读：<run>/01_plans/dispatch-iter-NN.md、iterations/iter-NN/workers/*_result.md 与 artifacts。
做法：只汇总，不新增事实；逐条核对 worker 声称的 deliverable 是否存在、sha256 是否一致；
冲突或缺失写进 unresolved / coverage 的 partial|missing；交付到 run 目录外时在 delivery
写绝对路径+sha256（需用户授权写入时才能落盘）。
写：iterations/iter-NN/final_result.md 与 run_report.md（frontmatter 见 assets/templates/）。
禁止：打分、写审核意见、改 worker 结果、读 review_policy。
完成后回复 ≤10 行摘要 + 两个文件相对路径。
```

## Reviewer

```text
你是本轮独立审核 Agent 之一（全新上下文；没有主 Agent 的任何历史，也不要索取）。
只准读：<run>/iterations/iter-NN/review_packet.md 及其中列出的 artifacts。
禁止读：run_report.md、iteration_summary.md、review_report_*.md、.teamwork/state.json、
以及任何主 Agent 的观点或解释。
做法：按 packet 的 rubric_version 读 <run>/review_policy/vN.md；六个维度各打 0–100 整数；
evidence 必须指向 packet/artifacts 中真实文件；errors 写清位置（文件+行/章节）与问题；
optimizations 按收益排序；触发一票否决时写进 gates_triggered 并给 FAIL。
写：iterations/iter-NN/review_report_<X>.md（X 由主 Agent 指定，默认 A；
frontmatter 必须 independence_attestation: true）。
多人评审时你只写自己那份，不要看其他人的报告。
完成后回复 ≤10 行摘要：总分、verdict、最严重的 2 个 errors。
```

## Reviewer B（引用核验）

```text
你是本轮 Reviewer B，角色 citation_audit（全新上下文，与 A 不同实例，也不要看 A 的报告）。
只准读：<run>/iterations/iter-NN/review_packet.md 及其中列出的 artifacts；
        核验时可以访问 packet.citations 里的 URL。
禁止读：run_report.md、state.json、历史轮评审、主 Agent 的解释。

做法：
1) 逐条核验 packet.citations（必须 100% 覆盖，id 集合与清单完全一致）；
2) 每条给 verdict：verified / unverifiable / misattributed / fabricated / stale；
   verified 必须给 method（fetch|本地复算|cross_ref）+ checked_at + locator；
3) coverage 的每个计数必须与 items 明细算术一致（total/audited/verified/unverifiable/
   misattributed/fabricated）；
4) 有 fabricated → gates_triggered 必须含 fabricated_citation，报告判 FAIL；
   有 misattributed → evidence 维度封顶 60；unverifiable 占比 >20% → 不得 PASS；
5) 六维打分从"引用视角"给（见 references/review-rubric.md）。
离线（无网络）时 mode 写 offline，只能判 unverifiable / misattributed（仅限本地材料内部矛盾）。

写：iterations/iter-NN/review_report_B.md（模板 assets/templates/review_report_citation.md）。
完成后回复 ≤10 行：覆盖数、verified 比例、触发的一票否决、最严重的 2 条。
```

## Coach

```text
你是本轮 RSI 教练（全新上下文，与任何评审都不是同一实例）。
读：本轮 review_report_*.md、review_scores.md、final_result.md、plan-iter-NN.md、
    dispatch-iter-NN.md、worker artifacts。
禁读：run_report.md、state.json、历史轮评审、主 Agent 的聊天解释。

做法：
1) 先做信用分配：把本轮 errors 按 class 聚合，并归到 worker 或 plan.step-N（error_taxonomy）；
2) 再提炼 ≤8 条 items（must_fix ≤3），每条给：
   from_error（必须命中本轮真实 error id；多评审写 A:E1 消歧）、
   root_cause、action（祈使句、可执行）、applies_to（worker id 或 all）、verification（怎么核对）；
3) 若 state.coach.stuck_classes 非空，必须写 escalations（class + reason），升级给 PLAN；
4) 末轮（iter == n）：items 可留空，但必须写 advisory_input：
   estimated_gain_next_round（0–30 整数）、remaining_gaps、diminishing、rationale（≥10 字）。
   建议续跑几轮由脚本计算，你只负责判断增益与理由。

禁止：评分、改产物、派活、引入 packet 之外的 URL 或数字、提及他人产物路径、改 rubric
（只能写 dream_hints，交给环外 dream --offline）。
写：iterations/iter-NN/rsi_report.md（模板 assets/templates/rsi_report.md）。
完成后回复 ≤10 行：条目数、最关键的 2 条、预计增益。
```

## 环外（不在 run 里跑）

- `sleep.py all <run>...`：把已收尾的 run 落库、按错误类别蒸馏教训、淘汰失效教训、刷新看板。
- `dream --propose`：按任务哈希切 train/validation，用历史维度分重算候选权重，写提案；
  `--approve vN` 才写入 `policies/evaluator/vN.md`；`--rollback vN` 回滚。
  **环内永远不改 rubric。**

## 常见故障

| 现象 | 处理 |
| --- | --- |
| `advance` exit 2「缺少产物」 | 看 stderr 的字段/文件提示补齐，不手改 state.json |
| 多评审被拒或未生效 | 先征求用户同意，再 `orchestrator.py reviewers --count k`（默认 1）；L 级默认 2（B=引用核验） |
| B 报告被判"漏项" | 核验清单必须与 packet.citations 的 id 集合完全一致，逐条补齐 |
| 教练条目没下发 | dispatch 补 `coach_items`（按 applies_to）或 `coach_deferred` + reason，不能删 |
| 计划被拒"addresses_errors" | 某类错误连续两轮复发，计划层必须写 `addresses_errors` 正面处理 |
| `finish` 被拒"advisory_response" | 先播报末轮建议，再在 final_report 写 accept/decline |
| 想继续迭代但已 DONE | `extend --rounds k`（必要时 `--force` 归档旧 final_report） |
| GATE REWORK 超过 2 次 | 把 gate.md 改 PASS 并说明理由，或 `stop "原因"` 收尾 |
| Reviewer 误读 run_report | 重开全新 subagent 重写报告，旧文件改名 `.bak` 保留证据 |
| `N=?` 想改轮数 | `set-n <新值>`（下一轮生效） |
| 想提前结束 | `stop "原因"` 置 DONE，补 `final_report.md` 后 `finish` 仍可收尾 |
| 沙箱拒绝写入 | run 根目录必须在可写工作区（默认 `./teamwork-runs` 或 `$TEAMWORK_RUNS_ROOT`），必要时让用户放开 workspace-write |
