---
schema_version: 1
reviewer: B
role: citation_audit          # 由 state.review.roles 决定；L 级默认 B=citation_audit
iteration: 1
rubric_version: v0
inputs_read:
  - "iterations/iter-01/review_packet.md"
  - "https://arxiv.org/abs/2309.06180"
  - "https://example.org/report-2024"
independence_attestation: true
dimensions:
  # 六维权重与 A 相同；判定口径换成"引用视角"（见 references/review-rubric.md）
  - {name: correctness, weight: 30, score: 62, evidence: ["iterations/iter-01/review_packet.md", "https://arxiv.org/abs/2309.06180"]}
  - {name: completeness, weight: 20, score: 70, evidence: ["iterations/iter-01/final_result.md", "iterations/iter-01/workers/w01_artifacts/out.md"]}
  - {name: evidence, weight: 20, score: 58, evidence: ["iterations/iter-01/workers/w01_artifacts/sources.yaml", "iterations/iter-01/final_result.md"]}
  - {name: robustness, weight: 10, score: 65, evidence: ["iterations/iter-01/final_result.md", "iterations/iter-01/workers/w02_artifacts/out.md"]}
  - {name: maintainability, weight: 10, score: 70, evidence: ["iterations/iter-01/workers/w01_artifacts/sources.yaml", "iterations/iter-01/final_result.md"]}
  - {name: cost, weight: 10, score: 75, evidence: ["iterations/iter-01/run_report.md", "iterations/iter-01/final_result.md"]}
citation_audit:
  mode: online               # offline 时禁止判 verified，只能 unverifiable/misattributed
  coverage:
    total: 12                # 必须等于 packet.citations 条数 = items 条数
    audited: 12
    verified: 10
    unverifiable: 1
    misattributed: 1
    fabricated: 0
  items:                     # 必须与 packet.citations 的 id 集合完全一致（100% 覆盖）
    - id: S01
      verdict: verified      # verified|unverifiable|misattributed|fabricated|stale
      method: fetch          # fetch|本地复算|cross_ref
      locator: "Abstract"
      checked_at: "2026-10-29T21:10:00+08:00"
      note: "原文摘要确有该表述"
    - id: S07
      verdict: misattributed
      method: fetch
      locator: "论文 §4.1 实为反例"
      checked_at: "2026-10-29T21:12:00+08:00"
      note: "结论方向写反，原文讨论失败案例"
gates_triggered: []          # 出现 fabricated 必须含 fabricated_citation；出现 misattributed 必须含 misattributed_citation
errors:
  - {id: E1, class: citation_unverified, located: "final_result.md#L18", recurred_from: null}
  - {id: E2, class: citation_unverified, located: "final_result.md#L26", recurred_from: null}
optimizations:
  - suggestion: "把 §4 的反例改为'该方案在长上下文下退化'，并补 S07 的失败条件"
    expected_gain: "+8"
total: 62
verdict: FAIL
---

# 审核报告 B（引用核验，第 1 轮）

## 核验结论

- 覆盖：12/12（100%）
- verified 10 / unverifiable 1 / misattributed 1 / fabricated 0
- **一票否决**：无
- **维度封顶**：misattributed ≥1 → evidence 维度封顶 60（本报告 58）

## 逐条核验

| id | 结论 | 方法 | 定位 | 说明 |
| --- | --- | --- | --- | --- |
| S01 | verified | fetch | Abstract | 原文摘要确有该表述 |
| S07 | misattributed | fetch | §4.1 | 结论方向写反 |

## 能力边界（必须诚实）

代码只能校验：结构完整（verified 必带 method/checked_at/locator）、
算术自洽（coverage 与明细一致）、清单完整（100% 覆盖）、链接存活（抽样）。
**"这条来源的内容是否真的支持该结论"仍由本评审判断**，不要对外宣称"引用零错误"。
