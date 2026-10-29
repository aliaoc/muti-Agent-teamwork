# RSI 设计说明：teamwork 的三个时间尺度

> 本文是设计说明，不是论文复现。我们借用 Dream-RSI（arXiv:2609.14858）与 RRSI（arXiv:2609.24972）的"历史即世界 + 离线改进策略 + 只改策略"思想做工程实现；论文分数与本仓库无关。

---

## 1. 为什么要引入 RSI

多 Agent 任务里最脆弱的环节通常不是"干活"，而是**审核标准**：

- rubric 写得太松 → 错误一路放行；
- rubric 写得太紧 → 每轮都在改格式，不解决实质问题；
- rubric 只对某一轮有效 → 换任务就失效。

固定 rubric 的根问题是：**没有人根据"实际审出来的错误"改进评审与执行本身**。但"让系统改自己的评价标准"又极易退化成"改到能过为止"。

v2.0 的解法是把自改进拆成**三个时间尺度**，并给每个尺度划定**唯一允许改动的对象**：

| 尺度 | 频率 | 允许改 | 谁负责 | 落盘 |
|------|------|--------|--------|------|
| **环内** | 每轮 | 做法（拆分、取证、格式、验证顺序） | COACH + Worker | `iterations/iter-NN/rsi_report.md`、dispatch `coach_items` |
| **环间** | 每 run 一次 | 继续还是收尾 | 脚本算数字 + 用户决定 | `iteration_advisory.md` → `advisory_response` / `extend` |
| **环外** | 天/周级 | 教训、规划参数、评分标准 | `sleep.py` / `dream --offline` | `$TEAMWORK_EXPERIENCE_HOME` |

**环内不改评分标准。** rubric 是裁判，裁判不能自己改判罚尺度。这条边界不是靠提示词嘱咐，而是代码强制的：

- `validate_policy()` 拒绝删除 `CORE_GATES`（4 个核心门禁），其余门禁只允许 ±10 内变动；
- rubric 权重只认 `review_policy/vN.md` 这一处真源（C1），评审报告的 `weight` 必须与之相等；
- 环内阶段（PLAN…COACH）没有任何写 `review_policy/` 的接口；唯一能升版的是环外 `dream --approve`。

---

## 2. 环内：COACH（每轮，改做法）

### 2.1 位置与输入

COACH 在 REVIEW 之后、下一轮 PLAN 之前运行，**全新实例**（不继承评审上下文）。

| 输入 | 用途 |
|------|------|
| 本轮 `review_report_*.md` | 全部评审的 `errors` / `optimizations` |
| `review_scores.md` | 合并分、维度分、分歧、`downgrade_reason` |
| 上轮 `rsi_report.md` | 命中率与 stuck 判定 |
| 上轮 `dispatch-iter-NN.md` | 上轮已下发的 `coach_items` |
| `review_packet.md` | 可引用的唯一事实边界 |

**不读** `run_report.md`、`state.json`、主 Agent 的解释——与评审同等的独立性要求。

### 2.2 输出结构（`rsi_report.md`）

```yaml
schema_version: 1
iteration: 2
tier: Large
verdict_in: REVISE
score_in: 74
error_taxonomy:
  - {class: evidence_gap, count: 4, attributed_to: [w03, plan.step-2]}
items:                       # ≤8；must_fix ≤3
  - id: C1
    from_error: [E2, B:E5]   # 本轮真实 error id（多评审写 "A:E3"）
    applies_to: [w03]
    priority: must_fix
    root_cause: "…"
    action: "…"
    verification: "…"
escalations: [{class: evidence_gap, reason: "连续两轮复发"}]
rsi_skipped: ""
advisory_input:              # 仅最后一轮
  estimated_gain_next_round: 8
  remaining_gaps: ["…"]
  diminishing: true
  rationale: "至少 10 字的理由"
```

### 2.3 八把锁（全部代码校验）

| 锁 | 规则 |
|----|------|
| 结构锁 | 每条 items 必须有 `from_error / root_cause / action / verification / priority / applies_to` |
| 事实锁 | 正文与条目里不得出现 packet 之外的 URL（教练不得引入新事实） |
| 引用锁 | `from_error` 必须指向本轮真实存在的 error id |
| 归属锁 | `attributed_to / applies_to` 只能是 `wNN / plan.step-N / final / main / all` |
| 预算锁 | `items ≤ 8`、`must_fix ≤ 3` |
| 升级锁 | `stuck_classes` 里每个类别必须出现在 `escalations` |
| 跳过锁 | FAIL/REVISE 轮必须给 items 或写明 `rsi_skipped`；PASS 轮可跳过但要给理由 |
| 越权锁 | 不得改 `final_result.md`、不得写 `gate.md`、不得指定 worker 以外的人干活 |

### 2.4 切片锁（DISPATCH）

`coach_items` 按 `applies_to` 逐 worker 下发：声明下发的条目必须出现在目标 worker 的 `coach_items` 里；不想下发必须写 `coach_deferred: [{id, reason}]`，**不允许静默删除**。

### 2.5 命中率与升级

```text
hit_rate = 上一轮条目覆盖的错误中，本轮不再出现的比例
```

- 第 1 轮没有"上一轮"，`hit_rate = None`（不参与统计）；
- 某类错误**连续两轮**复发 → 进 `state.coach.stuck_classes`：下一轮 `plan.addresses_errors` 必须正面写处理办法，`rsi_report.escalations` 必须升级，否则 `advance` 被拒；
- 命中率持续走低 → 说明教练在写无效条目，进 `state.coach.ineffective`，环外 `sleep.py` 会把它蒸馏成教训。

这把"反复犯同一个错"从提示词劝告变成**状态机无法绕过的检查**。

---

## 3. 环间：末轮建议（每 run 一次，决定收尾）

最后一轮 COACH 阶段，脚本生成 `iteration_advisory.md`。**数字由代码算，理由由教练写**——防止"自评 90 分、顺便建议再来三轮"。

| 字段 | 来源 |
|------|------|
| `score / verdict / prev_score / delta / trend` | 代码读 `state.scores` |
| `weakest_dimension / gap_to_pass` | 代码读合并维度分 |
| `recommendation / recommended_rounds` | 代码按规则表算 |
| `rationale` | 教练 `advisory_input.rationale`（≥10 字） |

规则表（`compute_advisory`）：

| 情形 | 建议 |
|------|------|
| FAIL 且 gap > 20 | continue，2 轮 |
| FAIL 且 gap ≤ 20 | continue，1 轮 |
| REVISE 且本轮无提升、历史最大增益 ≤2 | stop |
| REVISE 且 gap ≤ 单轮预期增益 | continue，1 轮 |
| REVISE 且 gap > 单轮预期增益 | continue，2 轮 |
| PASS 且本轮提升 < 噪声下限 5 | stop |
| PASS 且最弱维度 < 80 | continue，1 轮 |
| PASS 且最弱维度 ≥ 80 | stop |

轮数上限 `min(3, 10 - n)`；算出 0 轮即 `recommendation: stop`。`iteration_advisory.md` 手改会被 `check` 逐字段与 `state.advisory` 比对后拒绝。

用户决定落进 `final_report.advisory_response: accept|decline`（decline 需 `advisory_reason` ≥10 字），否则 `finish` 拒绝收尾；接受续跑用 `extend --rounds k`（旧 `final_report.md` 归档为 `final_report.iter-NN.md`）。

---

## 4. 环外：经验库与尺子演进

### 4.1 经验库结构

默认 `~/.teamwork/experience`，可用 `TEAMWORK_EXPERIENCE_HOME` 覆盖：

```text
<experience>/
├─ runs/<run_id>.json          # 每个 run 一条结构化记录（分数/错误/教练/引用覆盖率）
├─ lessons/L-YYYYMMDD-NN.md    # 跨 run 蒸馏出的教训
├─ metrics.md                  # 指标看板（首轮通过率/达 PASS 中位轮数/命中率/校准误差）
├─ proposals/vN.md             # 尺子演进提案
├─ golden/index.json           # golden 集指纹（防漂移）
└─ policies/evaluator/vN.md    # 已批准的评估器版本 + CURRENT 指针
```

### 4.2 睡眠任务（`sleep.py`）

| 命令 | 作用 |
|------|------|
| `record <run_dir>...` | 把 run 落库（幂等） |
| `distill --min-support k` | 跨 run 反复出现的错误压成教训 |
| `retire` | 淘汰命中率低于基线的教训 |
| `metrics` | 刷新指标看板 |
| `calibrate` | 规划校准报告（什么规模配几个人，只读不改） |
| `all <run_dir>...` | record + distill + retire + metrics |

### 4.3 replay world 的严格定义

环外 replay 不是"重新跑任务"，而是对已冻结的 world 用候选 rubric **重新打分**：

```yaml
world_i:
  task: <task.md>
  acceptance: <plan 的验收标准>
  final_result: <final_result.md + sha256>
  artifacts: [{path, sha256}, ...]
  review: {dimensions, errors, total, verdict}
  split: train | validation     # 按 task_hash % HOLDOUT_MODULUS 划分
```

- 不调用 worker / Final / 外部工具；
- replay_score 的计算与正式审核一致（六维加权 + 一票否决）；
- 因此可复现、可审计、零额外任务成本。

这也是产物契约要求"证据落在 run 内 + 每个 deliverable 带 sha256"的根本原因：没有可复核的冻结证据，replay 世界就不成立。

### 4.4 晋级门槛（`rsi_store.build_proposal` + `validate_proposal`）

全部满足才允许 `promote`：

1. **样本量**：≥2 个 run 且 ≥2 个不同 `task_hash`；
2. **必须有 holdout**：按 `task_hash % HOLDOUT_MODULUS == 0` 切出 validation 集，为空则直接拒绝提晋级；
3. **replay 最优**：候选在训练集（历史桶）上重新打分须为最优；
4. **噪声下限**：holdout 增益 > `noise_floor`（默认 5 分），防止把波动当改进；
5. **编辑预算**：候选改动数 ≤ `max_edits_per_iteration`（默认 3）——每次只验证少数变量；
6. **反漂移**：golden set 上漂移 ≤ ±3 分。

```python
# 简化伪代码
runs = load_runs()
train, holdout = split_by_task_hash(runs)              # 无 holdout → 抛错
base = current_policy()
cands = _candidate_weights(base, runs)                 # 每个候选 1 处改动为主
for c in cands:
    c.replay   = mean(score(c, w) for w in train)
    c.holdout  = mean(score(c, w) for w in holdout)
    c.delta    = c.holdout - baseline_holdout
best = max(cands, key=lambda c: c.replay)
if (best.delta > noise_floor and edits_ok(best)
        and golden_drift(best) <= 3 and len(tasks) >= 2):
    write proposals/vN.md  →  人工 dream --approve vN  →  policies/evaluator/vN.md
else:
    keep(current)  # 写入 proposals 的记录与理由
```

**批准是人工动作**（`dream --approve vN`），实现与批准分离；`dream --rollback vN` 可回退。

### 4.5 与 RRSI 的关系

RRSI（arXiv:2609.24972）强调编辑预算退火、按完整编辑历史给信用、噪声调整下限、成本规则、泄漏 critic。本插件的对应实现：

| RRSI 机制 | 本仓库实现 |
|-----------|-----------|
| 退火编辑预算 | 环内 `must_fix ≤ 3` + items ≤ 8；环外 `max_edits_per_iteration` |
| 编辑历史信用 | `state.coach.history[]` + 命中率 + `attributed_to` |
| 噪声调整下限 | `noise_floor`（默认 5）在环外提案与环间建议都用 |
| 成本规则 | 候选必须有 holdout 正增益，否则视为纯成本 |
| 泄漏 critic | 事实锁（不得引入 packet 外 URL）+ 尺子不含具体答案 |

---

## 5. 安全边界

| 风险 | 兜底 |
|------|------|
| 审核被主 Agent 影响 | packet 物理剔除 run_report/state/iteration_summary；审核 prompt 禁读；`inputs_read` 校验 |
| 改标准放水 | 环内无写 policy 接口；`validate_policy` 禁删核心门禁、权重限 ±10 |
| 用"重跑任务"刷分 | 环外提案只读历史产物，无 worker 预算 |
| 单轮过拟合 | 跨 run + holdout + 噪声下限 + 编辑预算 + golden 反漂移 |
| 教练越权 | 越权锁：不改 final_result、不写 gate、不指定 worker 之外的人 |
| 教练写空话 | 结构锁（root_cause/action/verification）+ 命中率统计 + ineffective 标记 |
| 分数漂移 | 噪声下限 + 多评审平均/分歧降级 + C4 证据密度 |
| 不可追溯 | 每版 policy 带 sha256；ledger / proposals append-only；历史版本不删 |

---

## 6. 局限与后续工作

- 历史桶很小时（n=1、2）replay 统计意义有限：环外观测只会 `keep`，环间建议也偏保守。这是有意为之。
- replay 复用正式 rubric 的评分函数，若正式审核本身有偏，replay 会继承偏差；缓解是多评审 + 证据强制 + 引用核验。
- 候选权重空间目前是"单维 ±10 的离散组合"，未做连续搜索；也未实现 Dream-RSI 的 discovery tree 分支管理与 M 版本并行采样（单机小任务收益有限）。
- 教训蒸馏依赖错误分类（`error_taxonomy.class`）的质量；分类错会污染指标与校准。

---

## 7. 参考

- Dream-RSI: <https://github.com/google-research/dream-rsi>，arXiv:2609.14858
- RRSI: <https://github.com/google-research/rrsi>，arXiv:2609.24972
- 实现：`skills/teamwork/scripts/rsi_store.py`（环外）、`skills/teamwork/scripts/teamwork_lib.py`（环内 COACH 校验、评审合成、引用核验、advisory）、`skills/teamwork/references/review-rubric.md`（rubric / 引用 / 教练 / 建议规则）
