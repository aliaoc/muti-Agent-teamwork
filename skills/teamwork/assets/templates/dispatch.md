---
schema_version: 1
iteration: 1
mode: parallel
workers:
  - id: w01
    scope: "子任务 1：<只做这些，越具体越好>"
    deliverables:
      - "iterations/iter-01/workers/w01_artifacts/out.md"
    acceptance: "产物存在、有实质内容、结论可核对"
---

# 派发（第 1 轮）

| worker | scope | 交付物 | 验收 |
| --- | --- | --- | --- |
| w01 | 子任务 1 | `workers/w01_artifacts/out.md` | 产物存在且有正文 |

## 并行 / 分阶段

- 无依赖：保持 `mode: parallel`。
- 有依赖：改 `mode: staged`，并在对应 worker 下补：
  ```yaml
  dependencies: [w01]
  ```
  后一批 worker 只能读前一批已完成的产物。

## 写作用域提醒

- 每个 Worker 只写 `iterations/iter-01/workers/wNN_artifacts/` 与自己那份 `wNN_result.md`。
- 不读写别人的目录、`run_report.md`、`review_packet.md`、`.teamwork/state.json`。
