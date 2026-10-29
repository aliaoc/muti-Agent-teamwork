---
schema_version: 1
iteration: 3
n_mode: explicit
score: 82
verdict: REVISE
prev_score: 78
delta: 4
trend: improving            # improving | flat | declining
weakest_dimension: {name: evidence, score: 68}
gap_to_pass: 3
recommendation: continue    # continue | stop
recommended_rounds: 1
expected_gain: 6
rationale: "证据维度 68 为唯一短板；本轮 +4 仍在改善，gap 3 分，历史单轮最大提升 6 分，预计 1 轮可达 85。"
generated_at: "2026-10-29T21:10:00+08:00"
---

# 末轮建议（脚本生成，不要手改）

> 本文件由 `orchestrator.py advance` 在 `iteration == n` 的 COACH 阶段自动写入。
> `score / verdict / delta / trend / weakest_dimension / gap_to_pass /
> recommendation / recommended_rounds` 全部由代码计算；`rationale` 来自
> `rsi_report.advisory_input.rationale`。手改任何数值都会被 `validate_advisory` 拒绝。

## 判定规则（`lib.compute_advisory`）

| 场景 | score / verdict | delta | 输出 |
|---|---|---|---|
| 首轮达标 | 88 PASS | null | stop / 0 |
| 达标但提升微弱 | 86 PASS | 2 | stop / 0 |
| 达标但证据薄弱 | 87 PASS | 6 | continue / 1 |
| 差一点点 | 82 REVISE | 4 | continue / 1 |
| 差得远 | 68 REVISE | 5 | continue / 2 |
| 触底 | 61 FAIL | 1 | continue / 2 |
| 连续停滞 | 76 REVISE | 0（上轮亦 0） | stop / 0 |

上限：≤3 轮、且 `n + rounds ≤ 10`。

## 告知用户（主 Agent 必做）

> 本轮 **82 分 / REVISE**（较上轮 +4，短板：证据 68）。**建议再迭代 1 轮**：
> 差距 3 分，历史单轮最大提升 6 分。如需继续，运行
> `orchestrator.py extend --rounds 1`；若就此收尾，遗留项会写入最终报告。

用户决定必须记进 `final_report.advisory_response`（accept/decline），否则 `finish` 拒绝收尾。
