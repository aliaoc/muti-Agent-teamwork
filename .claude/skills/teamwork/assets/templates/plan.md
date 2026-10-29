---
schema_version: 1
iteration: 1
tier: Medium
objective: "第 1 轮：整理可行方案并给出证据"
breakdown:
  - desc: "检索与取证（先产出 sources.yaml）"
    assignee: w01
  - desc: "方案对比"
    assignee: w02
  - desc: "写结论与风险"
    assignee: w03
accepted_criteria:
  - "结论有证据链"
  - "风险已标注"
  - "产物文件存在"
risks:
  - "证据来源可能不足"
worker_count: 3
addresses_errors: []        # 当 state.coach.stuck_classes 非空时必填，逐条写计划层怎么改
#  - {class: evidence_gap, mitigation: "单设取证 worker，并把验收提前到取证之后"}
---

# 计划（第 1 轮）

1. w01 检索与取证（先 `sources.yaml`，不写结论）
2. w02 方案对比
3. w03 写结论与风险

## 与教练的衔接

- 上一轮 `rsi_report.error_taxonomy` 的 `attributed_to` 若指向 `plan.step-N`，
  本轮必须改拆分方式，而不是只让 worker "注意一下"。
- 某类错误连续两轮复发时，`addresses_errors` 必须正面回应（脚本会核对）。
