---
schema_version: 1
iteration: 1
tier: Large
verdict_in: FAIL            # 必须等于本轮 review_scores.merged_verdict
score_in: 74                # 必须等于本轮 review_scores.merged_total
error_taxonomy:             # 信用分配：哪类错误、几条、归给谁
  - {class: evidence_gap, count: 4, attributed_to: [w02, "plan.step-3"]}
  - {class: incomplete_coverage, count: 2, attributed_to: [w05]}
items:                      # ≤8 条，must_fix ≤3；每条必须可执行、可核对
  - id: C1
    from_error: [A:E1, B:E4]   # 必须命中本轮真实 error id；多评审写 A:E1 消歧
    root_cause: "拆分把'查数据源'和'写结论'放同一个 worker，取证被写作挤掉"
    action: "w02 只做检索与取证，先产出 sources.yaml；结论写作交给 w05"
    applies_to: [w02]          # 只能是本轮 worker id 或 all
    verification: "w02_artifacts/sources.yaml 存在，且每条含 url+locator+quote"
    priority: must_fix         # must_fix | should_fix | nice_to_have
    expected_effect: "evidence 维度 +6"
  - id: C2
    from_error: [A:E5]
    root_cause: "并行派发时没有约定产出格式，Final 汇总时字段对不上"
    action: "所有 worker 的产物统一 frontmatter：claim/evidence/confidence"
    applies_to: [all]
    verification: "下轮所有 result.md 的 frontmatter 字段一致"
    priority: should_fix
escalations: []             # 连续两轮复发的类别必须在这里升级给 PLAN（否则 advance 会被拒）
dream_hints:                # 只能写建议；环内不改尺子
  - "本轮 4/6 个错误属 evidence_gap，建议离线评估是否提高 evidence 权重"
advisory_input:             # 仅末轮（iteration == n）必填
  estimated_gain_next_round: 6
  remaining_gaps: ["§3 四处无源结论", "§4 缺回滚步骤"]
  diminishing: false
  rationale: "证据维度 68 为唯一短板；本轮 +4 仍在改善，gap 3 分，历史单轮最大提升 6 分。"
---

# RSI 教练报告（第 1 轮）

> 教练 = 全新实例，不继承评审上下文。只读本轮 `review_report_*`、`review_scores.md`、
> `final_result.md`、plan/dispatch 与 artifacts；禁读 `run_report.md`、`state.json`、历史轮评审。
> 不评分、不改产物、不派活；不引入评审包之外的 URL / 引用。

## 错误归类

| 类别 | 条数 | 归属 |
|---|---|---|
| evidence_gap | 4 | w02、plan.step-3 |

## 下一轮动作

1. **C1（must_fix）** w02 先取证再写结论 —— 核对方式：`sources.yaml` 每条含 url+locator+quote
2. **C2（should_fix）** 统一产物 frontmatter —— 核对方式：下轮 5 份 result.md 字段一致

## 末轮建议输入（仅末轮）

- 预计下一轮增益：6 分
- 剩余缺口：§3 四处无源结论；§4 缺回滚步骤
- 是否收益递减：否
- 理由：<≥10 字，最终建议的数字由脚本计算，这里的理由会被引用>
