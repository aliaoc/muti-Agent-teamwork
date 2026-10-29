---
schema_version: 1
iteration: 1
verdict: PASS
checklist:
  - item: "需求覆盖（对照 accepted_criteria 逐条）"
    pass: true
  - item: "证据齐全（claims 都有 evidence 路径且存在）"
    pass: true
  - item: "产物文件存在且可打开"
    pass: true
  - item: "计划一致性（结果对得上 plan/breakdown）"
    pass: true
  - item: "无阻塞项 / 无未解释的 open_questions"
    pass: true
rework_targets: []
note: "主 Agent 自检通过；不含评审意见（评审由独立审核 Agent 负责）"
---

# 验收（第 1 轮）

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 需求覆盖 | PASS | <对照哪些文件> |
| 证据齐全 | PASS | <claims 与 evidence 数量> |
| 产物存在 | PASS | <路径> |
| 计划一致性 | PASS | — |
| 无阻塞项 | PASS | — |

## 结论

PASS。进入审核阶段。

## 若 REWORK

- `verdict: REWORK`
- `rework_targets: [w01, ...]`：写明哪个 Worker 的哪个产物不达标、要补什么。
- 注意每轮最多重做 2 次，第 3 次必须改 PASS 或 `stop`。
