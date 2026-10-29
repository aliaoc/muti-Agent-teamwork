---
schema_version: 1
iteration: 1
summary: "一句话汇总：本轮交付了什么、是否满足验收"
deliverables:
  - path: "iterations/iter-01/workers/w01_artifacts/out.md"
    sha256: "<该文件真实 sha256>"
coverage:
  - requirement: "验收标准 1"
    where: "iterations/iter-01/workers/w01_artifacts/out.md"
    status: covered
  - requirement: "验收标准 2"
    where: "iterations/iter-01/final_result.md"
    status: partial
unresolved:
  - "<未解决的问题；没有就写 []>"
---

# 最终结果（第 1 轮）

## 交付物

| 文件 | 说明 |
| --- | --- |
| `workers/w01_artifacts/out.md` | <是什么> |

## 结论

<只汇总已有事实，不新增结论、不编造证据>

## 需求覆盖

| 需求 | 位置 | 状态 |
| --- | --- | --- |
| 验收标准 1 | ... | covered |
| 验收标准 2 | ... | partial |

## 未决问题

- <无则写“无”>
