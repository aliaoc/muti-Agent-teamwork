---
schema_version: 1
iteration: 1
mode: parallel
coach_applied: [C1, C2]     # 上一轮 rsi_report.items 里本轮决定执行的条目
coach_deferred: []          # 不能执行的必须写 reason；不能直接删除条目
lessons_applied: []         # 从经验库检索注入的教训 id（可选）
workers:
  - id: w01
    scope: "只做检索与取证：先产出 sources.yaml，不写结论"
    deliverables:
      - "iterations/iter-01/workers/w01_artifacts/sources.yaml"
    acceptance: "每条来源含 url+locator+quote；不出现无源结论"
    coach_items:            # 由主 Agent 按 applies_to 切片，脚本会核对覆盖与越权
      - {id: C1, action: "先产出 sources.yaml，再写任何结论"}
      - {id: C2, action: "产物 frontmatter 含 claim/evidence/confidence"}
  - id: w02
    dependencies: [w01]
    scope: "基于 sources.yaml 写结论"
    deliverables:
      - "iterations/iter-01/workers/w02_artifacts/out.md"
    acceptance: "结论逐条引用 S01… 编号"
    coach_items:
      - {id: C2, action: "产物 frontmatter 含 claim/evidence/confidence"}
---

# 派发（第 1 轮）

| worker | scope | 交付物 | 验收 |
| --- | --- | --- | --- |
| w01 | 检索与取证 | `workers/w01_artifacts/sources.yaml` | 每条含 url+locator+quote |
| w02 | 基于证据写结论 | `workers/w02_artifacts/out.md` | 结论逐条引用来源编号 |

## 并行 / 分阶段

- 无依赖：保持 `mode: parallel`。
- 有依赖：改 `mode: staged`，并在对应 worker 下补 `dependencies: [w01]`。

## 教练条目切片（v2.0）

- 上一轮 `rsi_report.items` 的每一条，要么出现在某个 worker 的 `coach_items`，
  要么出现在 `coach_deferred` 并写 `reason`；**不能删除**（脚本会逐条核对）。
- `applies_to: [w02]` 只能下发给 w02；`all` 才能广播。
- 给 w01 的条目里不得出现 w02 的产物路径（隔离）；违反直接 exit 2。

## 写作用域提醒

- 每个 Worker 只写 `iterations/iter-01/workers/wNN_artifacts/` 与自己那份 `wNN_result.md`。
- 不读写别人的目录、`run_report.md`、`review_packet.md`、`.teamwork/state.json`。
