---
schema_version: 1
reviewer: A
role: general            # general | citation_audit（由 state.review.roles 决定，不能自选）
iteration: 1
rubric_version: v0
inputs_read:
  - "iterations/iter-01/review_packet.md"
  - "iterations/iter-01/workers/w01_artifacts/out.md"
  - "iterations/iter-01/workers/w02_artifacts/out.md"
independence_attestation: true
dimensions:
  # 权重必须与当前 rubric 一致（C1 已修：跟随 review_policy/vN.md，不是常量）
  - name: correctness
    weight: 30
    score: 85
    evidence:
      - "iterations/iter-01/workers/w01_artifacts/out.md"
      - "iterations/iter-01/workers/w02_artifacts/out.md"
  - name: completeness
    weight: 20
    score: 80
    evidence:
      - "iterations/iter-01/workers/w01_artifacts/out.md"
      - "iterations/iter-01/final_result.md"
  - name: evidence
    weight: 20
    score: 75
    evidence:
      - "iterations/iter-01/workers/w02_artifacts/out.md"
      - "iterations/iter-01/final_result.md"
  - name: robustness
    weight: 10
    score: 70
    evidence:
      - "iterations/iter-01/workers/w01_artifacts/out.md"
      - "iterations/iter-01/workers/w03_artifacts/out.md"
  - name: maintainability
    weight: 10
    score: 80
    evidence:
      - "iterations/iter-01/workers/w01_artifacts/out.md"
      - "iterations/iter-01/final_result.md"
  - name: cost
    weight: 10
    score: 85
    evidence:
      - "iterations/iter-01/workers/w01_artifacts/out.md"
      - "iterations/iter-01/run_report.md"
gates_triggered: []
errors:
  # 对象格式：id / class / located / recurred_from
  # recurred_from 指向上一轮 error id（多评审时写 A:E1 消歧），用来算教练命中率
  - id: E1
    class: evidence_gap
    located: "final_result.md#L18"
    recurred_from: null
optimizations:
  - suggestion: "每条结论补一行原文引用或命令输出"
    expected_gain: "+3"
total: 80
verdict: REVISE
---

# 审核报告 A（第 1 轮）

## 评分

| 维度 | 权重 | 分数 | 依据 |
| --- | --- | --- | --- |
| 正确性 | 30 | 85 | ... |
| 完整性 | 20 | 80 | ... |
| 证据与可验证性 | 20 | 75 | ... |
| 鲁棒性 | 10 | 70 | ... |
| 可维护/可回滚 | 10 | 80 | ... |
| 成本效率 | 10 | 85 | ... |
| **总分** | 100 | **80** | REVISE |

## 错误（必须具体，且带类别）

1. `final_result.md:18`：<问题描述>（class: evidence_gap）

## 优化建议（按收益排序）

1. <动作> → 预期 +N 分

## 独立性声明

本人只读了 `review_packet.md` 及其列出的 artifacts；未读 run_report、state.json、历史评审或主 Agent 解释。

## 说明

- 总分必须等于加权和（脚本会复核）；verdict 按阈值：<60 FAIL，<85 REVISE，≥85 PASS。
- **PASS 的证据密度下限**：errors 必须为空；每个维度至少 2 条 evidence；至少 3 条 evidence
  指向实质产物（不能全指向 `review_packet.md` 自身）。
- 多人评审时本文件由 A 写；B…k 各写 `review_report_B.md` …，互不可见。
- 维度分歧 >10 分时，脚本会把合并结论强制降级为 REVISE（C3），不要靠平均分盖过去。
