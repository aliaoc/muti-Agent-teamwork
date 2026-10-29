---
schema_version: 1
entries:
  - iteration: 1
    policy_before: v0
    candidates:
      - id: c1
        change: "证据维度要求逐条给文件+行号"
        replay_score: 78
      - id: c2
        change: "降低主观维度权重（可维护性 10→5，成本效率 10→15）"
        replay_score: 71
    decision: keep
    policy_after: v0
    reason: "c1 有提升但低于噪声下限 5 分；c2 在历史迭代上无区分度，keep v0"
---

# 重放账本

## 第 1 轮

- 当前策略：v0
- 候选：c1（证据要文件+行号，replay 78）、c2（调权重，replay 71）
- 决策：keep（未达 ≥2 条历史不回归 + 噪声下限 5 分）
- 下轮观察点：证据维度是否仍是最低分项

## 说明

- 重放 = 用候选 rubric 重新给**历史迭代产物**打分，不重新执行任务。
- `decision: promote` 时必须先创建 `review_policy/v(N+1).md`，且 `policy_after` 写新版本号。
- 每次最多 3 个候选、最多改 3 处；`current_iter ≥ ceil(n/2)` 后只允许改 1 处。
