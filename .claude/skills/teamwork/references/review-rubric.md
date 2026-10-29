# 审核 rubric 与 Dream-RSI 式复盘

## rubric v0（`review_policy/v0.md`）

| 维度 | 权重 | 关注点 |
| --- | --- | --- |
| 正确性 correctness | 30 | 结论是否正确，有无事实/推理错误 |
| 完整性 completeness | 20 | 是否覆盖任务与验收标准，有无遗漏 |
| 证据与可验证性 evidence | 20 | 每个断言能否按证据路径复核；有无空口结论 |
| 鲁棒性 robustness | 10 | 边界、失败路径、异常输入是否考虑 |
| 可维护与可回滚 maintainability | 10 | 结构清晰、可复现、可回滚 |
| 成本效率 cost | 10 | 时间/调用/复杂度是否与收益匹配 |

- **一票否决**（`gates_triggered` 命中即 FAIL）：`unsupported_claims` 无证据断言、`fabricated_evidence` 虚构证据、`off_topic` 答非所问、`claimed_pass_without_run` 未运行却声称通过。
- 阈值：总分 `<60` → FAIL，`<85` → REVISE，`≥85` → PASS。
- 总分 = Σ(维度分 × 权重 / 100)，四舍五入到整数；脚本会复核 `total` 与加权一致性。
- 单个维度分差不是重点，重点是 `errors` 是否能落到具体文件/行。

## 审核输入（review_packet.md）

`make-packet` 只放：任务、验收标准、artifacts（路径 + sha256）、rubric_version、reviewers、forbidden。**不放** run_report、主 Agent 观点、历史评审、iteration_summary —— 保证审核独立。

Reviewer 只准读 packet 与 packet 里列出的 artifacts；`inputs_read` 里出现禁止项会被校验拒绝。

## 多评审（默认 1 位，可 k 位）

- 默认 1 人；需要 k>1 时先向用户说明成本并确认，再 `orchestrator.py reviewers --count k`（框架支持 1–26）。
- 每位评审各自独立开全新 subagent、互不可见；只读同一 packet；分别写 `review_report_A.md`…`review_report_<k>.md`。
- 合并规则（脚本实现）：总分 = 各评审总分的平均；任一 FAIL → 合并 FAIL；同维度最大分差 >10 记入 `review_scores.md` 的 disagreements，由主 Agent 决定是否重审。
- 多评审成本约 k 倍，仅在 Large / 高风险 / 争议 / 迭代次数较多时使用；审核人数不受 8 人上限约束（该上限只约束单任务内的 Worker+Final），由迭代次数与任务要求决定（当前实现 1–26 位，按单个任务计数）。

## 复盘：Dream-RSI 式「做梦」（DREAM 阶段）

历史迭代桶 = **replay world**：把此前各轮的 `final_result.md`、`review_report_A.md`、`iteration_summary.md` 当作“世界”，用来重放候选 rubric，而不是重新执行任务。

每次 DREAM：

1. 读本轮 review_report 的 `errors` / `optimizations`（以及历史轮的同类记录）。
2. 提 ≤3 个 **rubric 变体**：只改 `review_policy/vN.md` 的权重、检查项、评分说明；不改任务、不改 Worker/Final、不改 rubric 的六维口径（除非有明确证据）。
3. **重放**：用每个变体重新给历史迭代产物打分，记录 `replay_score`、区分度（历史轮之间分数是否拉开）、误报率。
4. 按门槛决定 keep / promote：

| 门槛 | 规则 |
| --- | --- |
| 历史覆盖 | 至少在 2 条历史迭代上不差于当前版本 |
| 噪声下限 | 提升 ≤ 5 分视为噪声，不晋级 |
| 成本规则 | 新增检查项必须提升区分度，否则删掉 |
| 退火预算 | 每次最多改 3 处；当 `current_iter ≥ ceil(n/2)` 后只允许改 1 处 |
| 泄漏 critic | rubric 不得出现具体任务名/答案/样例路径（防止只对单轮定制） |

5. 写 `replay_ledger.md` 追加本轮 entry：

```yaml
entries:
  - iteration: 1
    policy_before: v0
    candidates:
      - {id: c1, change: "证据维度要求逐条给文件+行号", replay_score: 78}
    decision: keep          # 或 promote
    policy_after: v0        # promote 时写 v1，并先创建 review_policy/v1.md
    reason: "提升未超过噪声下限"
```

## 反模式（校验会拒或人工判 FAIL）

- 审核报告只写“整体不错/建议优化”而不给证据 → 视为 unsupported_claims。
- 给历史轮打统一的 90+ 分而不引用具体 artifact → 视为 fabricated_evidence。
- 每轮都 promote 新 rubric 只为“看起来在进化” → 触犯成本规则/退火预算。
- Reviewer 读了 run_report 或主 Agent 解释后再打分 → 独立性失效，报告作废重写。
