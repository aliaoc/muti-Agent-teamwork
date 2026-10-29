# RSI 设计说明：teamwork 如何借用 Dream-RSI

> 本文是设计说明，不是论文复现。我们借用 Dream-RSI 的「历史 replay + 策略离线进化 + 只改策略」思想做工程近似；论文分数与本仓库无关。

---

## 1. 为什么要引入 RSI

多 Agent 任务里，最脆弱的环节通常不是"干活"，而是**审核标准**：

- rubric 写得太松 → 错误一路放行；
- rubric 写得太紧 → 每轮都在改格式，不解决实质问题；
- rubric 只对某一轮有效 → 换任务就失效。

固定 rubric 的问题在于：**没有人根据"实际审出来的错误"改进评审方法本身**。

Dream-RSI（Google Research，arXiv:2609.14858）给出的思路是：

1. **在线探索**产生历史尝试（discovery tree）；
2. 把历史尝试当作 **replay simulator**（"睡梦中回放的世界"）；
3. 让 agent 在 replay world 上**离线改进自己的探索策略**；
4. 只改策略代码，agent / evaluator / task 保持不变；
5. M 个候选版本中评测出最优，上线继续在线探索。

teamwork 把「探索策略」替换成「**审核策略（rubric + 检查顺序 + 证据要求）**」，其余结构同构。

---

## 2. 映射总表

| Dream-RSI | teamwork | 存放位置 |
|-----------|----------|----------|
| 在线 rollout | 一轮真实执行（WORKERS→FINAL→GATE→REVIEW） | `iterations/iter-NN/` |
| discovery tree | 多轮迭代 + 每轮错误修复记录 | 同上 |
| replay world | 历史迭代桶（冻结的产物 + 分数） | `iterations/iter-NN/` + `review_scores.md` |
| policy code | 审核策略文件 | `review_policy/vN.md` |
| offline dreaming | DREAM 阶段（轮间离线） | `review_policy/replay_ledger.md` |
| M=4 版本评测 | 当前版本 + ≤3 候选 | `replay_ledger.md` 的 `candidates` |
| evaluate / promote | 晋级门槛（见 §4） | `advance_run` 落库 |
| 不改 agent/evaluator/task | 只改 rubric；任务、worker、gate、阈值不变 | 校验器强制 |

---

## 3. replay world 的严格定义

第 i 轮冻结的 world：

```yaml
world_i:
  task: <00_intake/task.md 中的任务>
  acceptance: <plan 中的 acc前定验收标准>
  final_result: <iterations/iter-i/final_result.md + sha256>
  artifacts: [<path, sha256>, ...]      # 报告、worker 产物、证据
  review: <该轮各评审的 dimensions/errors/optimizations + 总分>
```

replay 的输入 = `(world_i, candidate_policy)`，输出 = 一个分数。

**replay 不重新执行任务**：

- 不调用 worker / Final / 外部工具；
- 只读已冻结的产物与证据；
- replay_score 的计算规则与正式审核一致（六维加权 + 一票否决）；
- 因此 replay 可复现、可审计、零额外任务成本。

这也是为什么产物契约要求**证据必须落在 run 内、每个 deliverable 带 sha256**：没有可复核的冻结证据，replay 世界就不成立。

---

## 4. 候选策略与五个正则化

每次 DREAM 最多 3 个候选；每个候选只允许 1 处改动（即同一时刻验证一个变量）。候选来源：本轮 `review_report` 的 `errors`/`optimizations` + 历史轮同类问题统计。

### 4.1 噪声下限（noise floor = 5）

历史桶样本很少时，分数波动天然很大。候选策略的历史平均 replay 分比当前版本高出 **≤5 分**时视为噪声，不晋级。

### 4.2 历史覆盖门槛（≥2 条不回归）

候选必须在**至少 2 条**历史迭代上不劣于当前版本，才允许晋级。只有 1 条历史时（第 1 轮）只能 keep——这是设计，不是 bug。

### 4.3 退火编辑预算（annealed edit budget）

```
allowed_edits = 3                         # 前期：允许改 3 处
if current_iter >= ceil(n / 2):
    allowed_edits = 1                     # 后半程：只允许改 1 处
```

越接近收尾，越不允许大幅改标准（防止"为了通过而改标准"）。

### 4.4 成本规则（cost rule）

新增检查项必须能提升区分度（在历史桶上把错误轮与正确轮拉开分差），否则删掉。检查项数量不是越多越好：rubric 越长，审核越难执行、越容易形式化。

### 4.5 泄漏 critic（leakage critic）

rubric 中禁止出现：

- 具体任务名/文件名/人名/数字答案；
- 只对单轮有效的检查（如"检查第 7 页第 3 行的公式"）；
- 任何"如果分数低于 X 就给 Y 分"式的结果导向条款。

只允许写**检查方法**（"每个数值断言是否能回溯到证据路径"），不允许写**期望答案**。

> RRSI（arXiv:2609.24972）中的编辑历史信用、噪声调整下限、成本规则、泄漏 critic 是上述设计的直接来源；本实现只保留可自动校验的部分。

---

## 5. 晋级算法（与代码对应）

```python
# DREAM 阶段（简化伪代码）
current = load_policy(state.review.policy_version)
history = [load_world(i) for i in 1..state.current_iter]        # 历史迭代桶
candidates = propose_edits(history, errors=this_round.errors, max_n=3, max_edits=allowed_edits)
versions = [current] + candidates

for v in versions:
    v.replay_score = mean(review_score(v, world) for world in history)

best = max(versions, key=lambda v: v.replay_score)
promotable = (
    best is not current
    and best.replay_score - current.replay_score > 5
    and all(best.replay_score >= current.replay_score for w in history[:2])
    and cost_rule_ok(best)
    and no_leakage(best)
)

if promotable:
    write_policy(version=next_version)          # review_policy/v(N+1).md
    entries.append(decision="promote", policy_after=f"v{next_version}")
else:
    entries.append(decision="keep", policy_after=current.version)
```

`review_scores.md` 与 `replay_ledger.md` 都由校验器检查结构（`entries` 字段、`decision` 合法、`policy_after` 与 promote 一致、promote 前 `review_policy/vN.md` 必须存在）。

---

## 6. 安全边界

| 风险 | 兜底 |
|------|------|
| 审核被主 Agent 影响 | packet 物理剔除 run_report/state/iteration_summary；审核 prompt 禁读；`inputs_read` 校验 |
| 用"重跑任务"刷分 | DREAM 阶段无 worker 预算，只读历史产物 |
| 改标准放水 | gate 与 review 阈值/规则不可在 policy 中改（只允许改 rubric 维度内说明与检查顺序） |
| 单轮过拟合 | ≥2 历史覆盖 + 退火预算 + 泄漏 critic |
| 分数漂移 | 噪声下限 5 + 多评审平均/分歧记录 |
| 不可追溯 | 每版 policy 带 sha256、ledger append-only、历史策略不删除 |

---

## 7. 局限与后续工作

- 历史桶太小时（n=1、2）replay 统计意义有限，前几轮基本只能 keep；这是有意保守。
- replay 复用正式 rubric 的评分函数，若正式审核本身有偏差，replay 会继承偏差；缓解手段是多评审与证据强制。
- 当前 policy 只覆盖 rubric（维度/检查项/证据要求），尚未覆盖"审核 Agent 的检查顺序/取证策略"的完整编程接口；这部分在路线图中。
- 未实现 Dream-RSI 的 discovery tree 分支管理与 M 版本并行采样；单机小任务场景下收益有限。

---

## 8. 参考

- Dream-RSI: <https://github.com/google-research/dream-rsi>，arXiv:2609.14858
- RRSI: <https://github.com/google-research/rrsi>，arXiv:2609.24972
- 本仓库实现：`skills/teamwork/scripts/teamwork_lib.py`（DREAM 校验/落库）、`skills/teamwork/references/review-rubric.md`（rubric 与复盘规则）、`iterations/iter-NN/` 与 `review_policy/`（数据）
