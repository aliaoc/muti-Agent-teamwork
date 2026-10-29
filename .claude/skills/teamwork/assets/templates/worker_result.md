---
schema_version: 1
worker_id: w01
iteration: 1
scope: "子任务 1：<与 dispatch 一致>"
status: completed
deliverables:
  - path: "iterations/iter-01/workers/w01_artifacts/out.md"
    sha256: "<用 python/sha256sum 算出的 64 位小写十六进制>"
claims:
  - text: "一句话结论（可被证据支持）"
    evidence:
      - "iterations/iter-01/workers/w01_artifacts/out.md"
open_questions: []
confidence: high
---

# w01 结果

## 做了什么

<3–5 行，写清产出与路径>

## 关键结论

1. <结论 1，对应 claims[0]>
2. <结论 2>

## 证据

- `workers/w01_artifacts/out.md`：<哪一节支持哪条结论>

## 未决问题

- <没有就写“无”>

## 说明

- `sha256` 必须是文件真实摘要；文件改写后必须重算。
- 失败时把 `status` 改成 `failed` 或 `blocked`，并在 `open_questions` 写清卡在哪。
