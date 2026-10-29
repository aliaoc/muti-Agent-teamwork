---
schema_version: 1
tier: Small
tier_reason: "示例：单文件、可本地验证、低风险；按实际 signals 改写"
signals:
  files: 1
  external: false
  verifiable: true
  parallel: false
  risk: low
  user_demand: false
workers_planned: 1
n_adjust: 0
n_reason: ""
user_confirmed: false
---

# 分级说明

- 为什么是 Small：<引用 signals 里的具体项，如 files=1、无外部依赖>
- 预期 Worker：<w01 负责什么>
- 轮数：<用户给了 N=几 就写数字；N=? 时写默认轮数 + n_adjust 理由>
- 是否需要用户确认：<yes/no>
