---
schema_version: 1
proposal: v1
generated_by: dream --offline
policy_before: v0
noise_floor: 5
max_edits_per_iteration: 3
sample:
  runs: 6
  tasks: 4
  train: 4
  validation: 2
  holdout: "task_hash % 3 == 0"
baseline: {all: 74.5, train: 73.8, validation: 76.2}
candidates:
  - id: c1
    change: "evidence +5 / cost -5（补短板）"
    weights: {correctness: 30, completeness: 20, evidence: 25, robustness: 10, maintainability: 10, cost: 5}
    edits: 2
    replay_score: 78.4            # 必须等于 world_scores 的均值（脚本复核）
    validation_score: 79.1
    validation_delta: 2.9
    world_scores:
      - {run_id: "20261020-...", iteration: 1, score: 78.0}
      - {run_id: "20261020-...", iteration: 2, score: 78.8}
decision: promote
policy_after: v1
reason: "c1 全量 +3.9、holdout +2.9，均超过噪声下限 5 的判定另需人工确认；样本 6 run / 4 任务"
---

# 环外尺子演进提案（`dream --offline` 的输出，不是环内产物）

## 为什么在环外

环内（COACH）只改做法；评分标准是 evaluator，改它就是改判罚尺度。
按 Dream-RSI 的约束，evaluator 只在跨 run、带 holdout 的条件下演进。

## 三道闸（代码强制）

| 闸 | 规则 | 校验位置 |
|---|---|---|
| 切分 | 按**任务哈希**切 train/validation（不按轮次） | `rsi_store.split_of` |
| 锚点 | `golden/index.json` 上漂移 >±3 分即拒 | `golden_drift` |
| 样本 | <2 个不同任务不许 promote | `validate_proposal` |

## 门槛（代码强制）

- `replay_score` 必须等于 `world_scores` 均值（防自报）；
- 最佳候选提升必须 > `noise_floor`；
- holdout 上必须有正增益；
- 单维权重变化 ≤±10，权重和为 100；
- `edits` 必须等于真实改动维度数，且不超过 `max_edits_per_iteration`。

## 批准

```bash
python scripts/orchestrator.py dream --propose          # 生成提案
python scripts/orchestrator.py dream --approve v1       # 批准并写入 policies/evaluator/v1.md
python scripts/orchestrator.py adopt-policy <run> --version v1
python scripts/orchestrator.py dream --rollback v0      # 回滚
```
