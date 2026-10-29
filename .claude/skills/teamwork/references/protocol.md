# teamwork 协议细则

## 总则

1. **文件即接口**：Agent 之间只通过 run 目录里的文件传递产物；每次回复只给摘要（≤15 行）+ 产物相对路径 + 未决问题，不把全文塞回主上下文。
2. **主 Agent 是唯一调度者**：子 Agent 不互相直接通信；没有 dispatch 明确声明的依赖时，Worker 不读其他 Worker 的目录。
3. **写作用域**（同一文件同一时刻只允许一个 Agent 写）：
   - Worker：`iterations/iter-NN/workers/<wid>_artifacts/` 与 `<wid>_result.md`
   - Final：L 级写 `iterations/iter-NN/final_result.md`、`run_report.md`；S/M 级由主 Agent 直接写这两个文件
   - 主 Agent：`00_intake/`、`01_plans/`、`gate.md`、`final_report.md`、命令产生的文件
   - Reviewer：`review_report_<X>.md`（X=A…k，k 位评审各自一份，互不可见）
   - Dream：`review_policy/replay_ledger.md`、promote 时的 `review_policy/vN.md`
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
- 可选 `user_confirmed: true`（Large 且规划后要用户确认时）。
- `advance` 后 state 落库 `tier`、`n`、`workers.planned`。

### PLAN（主 Agent）

- 第 2 轮起先读上一轮 `iteration_summary.md` / `review_report_A.md` / 当前 `review_policy/vN.md`。
- 写 `01_plans/plan-iter-NN.md`：`objective`、`breakdown`（assignee 用 `wNN` 或 `main`）、`accepted_criteria`（可验证）、`risks`（Medium/Large 至少 1 条）、`worker_count`。
- Large 追加 `alternatives`：≥2 个方案对比 + 选择理由（写 frontmatter 列表或正文均可）。
- 给用户 3–8 行计划摘要；Large 默认在派发前请用户确认（用户已授权自动执行时除外）。

### DISPATCH（主 Agent）

- 把 `plan.breakdown` 映射成 worker 任务卡：`id`、`scope`（只做这些）、`deliverables`（相对路径清单）、`acceptance`。
- 复用策略：优先沿用 `state.workers.registry` 里已有的 Worker id（同 scope/上下文）；S/M 第 2 轮起原则上不新建 id，确需新建时在 dispatch 正文写理由。
- **累计硬上限**：本任务（run）累计不同 worker id 数不得超过该等级上限（S 2 / M 4 / L 7，L 级 +Final=8）；跨轮复用同一 id 不重复计数。校验会在超限时报错；同一对话的多个任务各自独立计数。
- 无依赖 → `mode: parallel`；有依赖 → `mode: staged`，并在对应 worker 写 `dependencies: [wNN, ...]`。
- `deliverables` 路径必须在 `iterations/iter-NN/workers/wNN_artifacts/` 下。
- `advance` 后 `state.workers.ids` 更新，同时维护 `registry`（首次出现轮次）、`agents`（逻辑 id → 物理 teammate 名）、`reused`、`new_ids`；下一阶段按 ids 起子 Agent。

### WORKERS（并行子 Agent）

- 按 `state.workers.ids` 起 Worker：**优先复用**已有 Worker（同 id、保留其上轮上下文），S/M 级第 2 轮起原则上不新建；只有确需新 id 时才新开 subagent（dispatch 里应说明理由）。
- 运行时差异：Claude Code 的 Task 子 Agent 是一次性的，“复用”指沿用同一逻辑 id、把上轮 result 与 artifacts 路径交给新 subagent（文件交接），不是恢复会话；只有 DSH 的 durable teammate 才用 `send_message`。
- **命名隔离**：新开 teammate 一律使用 `next` 输出里的 `agent_name`（形如 `tw-<任务指纹>-w01`），不要直接用 `w01` 当物理名；逻辑 id 仍是 `wNN`。复用轮次用 `send_message` 发给同一 `agent_name`。其它任务的 agent 名不可挪用。
- 新 Worker 才需要给全新 prompt（下方模板）；复用 Worker 直接派本轮的 scope/acceptance，并提醒它读自己上轮产物与评审意见。
- 每个 Worker 写 `<wid>_result.md`：deliverables（path+sha256）、claims（每条证据路径）、open_questions、confidence。
- 全部完成后 `advance`；校验会检查状态、deliverable 存在、claims 证据存在。
- 有依赖的 worker 按 staged 顺序起；后一批 worker 可读前一批产物。

### FINAL（S/M：主 Agent 直接汇总；L：全新 Final Agent）

- S/M 级：主 Agent 直接写 `final_result.md` 与 `run_report.md`（不再开子 Agent，也无需 keep-alive 的 Final 上下文）；不得自评。
- L 级：启动 1 个全新 Final Agent，输入 dispatch、全部 `worker_result.md`、worker artifacts 清单。
- 两种模式产物相同：`final_result.md`（summary、deliverables+sha256、coverage[需求→位置→状态]、unresolved，可选 delivery[path,sha256]）与 `run_report.md`（highlights、issues、next_suggestions）。
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
- `advance` 时脚本自动合成 `review_scores.md`（各评审加权总分平均、合并 verdict、维度最大分歧）。

### DREAM（审核 Agent 做梦模式）

- 只在 `current_iter < n` 时进入；读取历史迭代桶（此前各轮的 final_result / review_report / iteration_summary）。
- 产出 ≤3 个 rubric 变体 → 在历史迭代上重放打分 → 按 `review-rubric.md` 门槛 keep/promote。
- 写 `review_policy/replay_ledger.md`（append 本轮 entry）；promote 时写 `review_policy/v(N+1).md`。
- 完成后 `advance` 自动进入下一轮 PLAN（current_iter+1）。

### DONE（主 Agent）

- 写 `final_report.md`（run、tier、iterations、trajectory、outcome）→ `finish` 生成 `score_trend.png`。
- 给用户的收尾报告：run_dir、各轮分数轨迹、最终 verdict、产物清单、unresolved。

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

## Dream

```text
你是审核 Agent 的做梦模式（全新上下文；只做策略复盘，不重跑任务）。
读：历史迭代的 final_result.md / review_report_A.md / iteration_summary.md、
当前 review_policy/vN.md、replay_ledger.md。
做法：
1) 针对本轮 review_report 暴露的问题，提出 ≤3 个 rubric 变体（权重/检查项/评分说明），
   每个变体给预期效果与可能副作用；
2) 在历史迭代桶上重放：用变体重新给历史产物打分，记录 replay_score 与区分度；
3) 按 references/review-rubric.md 的晋级门槛 keep/promote；promote 时写 review_policy/v(N+1).md；
4) 写 review_policy/replay_ledger.md（append 本轮 entry：policy_before/candidates/decision/
   policy_after/reason）。
禁止：执行任务、改 worker/final 产物、改任务描述、改 .teamwork/state.json。
```

## 常见故障

| 现象 | 处理 |
| --- | --- |
| `advance` exit 2「缺少产物」 | 看 stderr 的字段/文件提示补齐，不手改 state.json |
| 多评审被拒或未生效 | 先征求用户同意，再 `orchestrator.py reviewers --count k`（默认 1） |
| GATE REWORK 超过 2 次 | 把 gate.md 改 PASS 并说明理由，或 `stop "原因"` 收尾 |
| Reviewer 误读 run_report | 重开全新 subagent 重写报告，旧文件改名 `.bak` 保留证据 |
| `N=?` 想改轮数 | `set-n <新值>`（下一轮生效） |
| 想提前结束 | `stop "原因"` 置 DONE，补 `final_report.md` 后 `finish` 仍可收尾 |
| 沙箱拒绝写入 | run 根目录必须在可写工作区（默认 `./teamwork-runs` 或 `$TEAMWORK_RUNS_ROOT`），必要时让用户放开 workspace-write |
