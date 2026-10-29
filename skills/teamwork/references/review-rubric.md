# 审核 rubric、引用核验与教练复盘

本文是「审核」与「教练」的全部硬约定。**所有规则都由 `scripts/teamwork_lib.py` 校验**，写错字段或算术不一致一律 `exit 2`。

---

## 1. rubric v0（`review_policy/v0.md`）

| 维度 | 权重 | 关注点 |
| --- | --- | --- |
| 正确性 correctness | 30 | 结论是否正确，有无事实/推理错误 |
| 完整性 completeness | 20 | 是否覆盖任务与验收标准，有无遗漏 |
| 证据与可验证性 evidence | 20 | 每个断言能否按证据路径复核；有无空口结论 |
| 鲁棒性 robustness | 10 | 边界、失败路径、异常输入是否考虑 |
| 可维护与可回滚 maintainability | 10 | 结构清晰、可复现、可回滚 |
| 成本效率 cost | 10 | 时间/调用/复杂度是否与收益匹配 |

- 总分 = Σ(维度分 × 权重 / 100)，四舍五入到整数；脚本复核 `total` 与加权一致性。
- 阈值：`<60` → FAIL，`<85` → REVISE，`≥85` → PASS（`REVISE_THRESHOLD` / `PASS_THRESHOLD`）。
- **C1：权重唯一事实来源是当轮 rubric**。评审报告的 `weight` 必须等于 `review_policy/vN.md` 的 `weights`，不是硬编码常量——策略升版后权重变了，报告不改就会被拒。

### 一票否决（`gates_triggered` 命中即 FAIL）

| 门禁 | 含义 | 是否可被策略删除 |
| --- | --- | --- |
| `unsupported_claims` | 无证据断言 | ❌ 核心门禁 |
| `fabricated_evidence` | 虚构证据（路径/文件不存在） | ❌ 核心门禁 |
| `off_topic` | 答非所问 | ❌ 核心门禁 |
| `claimed_pass_without_run` | 未运行却声称通过 | ❌ 核心门禁 |
| `fabricated_citation` | 查无此文（来源不存在） | ✅ 可开关，默认开 |

`validate_policy` 的规则：**核心门禁不可删**，其余门禁只允许 ±10 内的权重/开关变动；`gates` 里出现 `CORE_GATES` 之外的新门禁需要说明。

---

## 2. 评审角色（A / B）

| 角色 | `role` | 职责 |
| --- | --- | --- |
| A（通用） | `general` | 六维评分 + 一票否决 + errors/optimizations |
| B（引用核验） | `citation_audit` | 逐条核验 `sources[]` 真实性，额外产出 `citation_audit` 段 |

规则：

- 默认 1 位评审（`general`）。
- **L 级 + `citation_audit != off` 时脚本自动把评审设为 2 位并写 `roles = {A: general, B: citation_audit}`**，不需要人工 `reviewers --count 2`。
- 若用户显式设过评审人数（`reviewers_set_by_user`），脚本不覆盖，只按用户给的人数分配角色。
- `role: citation_audit` 的报告**必须**有 `citation_audit` 段；`role: general` 的报告**不得**出现该段（互相越权都会被拒）。

---

## 3. 评审输入与独立性

`make-packet` 只放：任务、验收标准、artifacts（路径 + sha256）、`citations[]`、`citation_policy`、`roles`、rubric_version、forbidden。

**不放入**：`run_report.md`、`state.json`、`iteration_summary.md`、历史评审、主 Agent 的观点。

校验项：

- `inputs_read` 中出现 `run_report` / `state.json` / `iteration_summary` / `review_report` 任一关键词 → 判独立性失效。
- `independence_attestation` 必须为 `true`。
- `evidence` 若是 run 内相对路径，必须真实存在；`http(s)://` URL 放行（不校验可达性，交由 B 核验）。

---

## 4. PASS 的证据密度（C4）

防止「六维全 85 + errors 空」糊过去：

1. PASS 报告**不允许有 errors**（有错就改判 REVISE）；
2. 每个维度 **≥2 条** `evidence`；
3. 全部 evidence 中 **≥3 条**必须指向实质产物，不能全部指向 `review_packet.md` 自身（自指漏洞）。

---

## 5. 多评审合并（`compute_merged_review`）

- 总分 = 各评审总分的**算术平均**（四舍五入）。
- **任一评审 FAIL → 合并 FAIL**（平均分不能吞掉否决）。
- **C3：同一维度最大分差 > 10 → 禁止 PASS**，合并降级为 REVISE，并把分歧写进 `review_scores.md` 的 `disagreements` 与 `downgrade_reason`。
- **引用核验口径**：B 报告的 `unverifiable / total > 20%` → 禁止 PASS。
- 合并同时输出 `merged_dimensions`（逐维平均）供 `iteration_advisory.md` 找短板。

---

## 6. 引用核验（L 级，Reviewer B）

### 6.1 sources[] 的登记（FINAL 阶段）

`final_result.md` 必须登记 `sources[]`，每项：

```yaml
sources:
  - id: S01                      # S01 形式，全局唯一
    url: https://example.org/a   # 或 doi:/isbn:/path（内部资料）
    title: "..."
    used_for: "支撑 §2.1 的市场规模结论"
    locator: "Table 3"           # 页码/章节/表格号，可空
```

`make-packet` 会把 `sources[]` 写进 packet 的 `citations[]`（上限 `CITATION_MAX_ITEMS = 40`），B 只能核验这个清单。

### 6.2 三把锁

| 锁 | 规则 | 违反后果 |
| --- | --- | --- |
| **结构锁** | 判 `verified` 的条目必须给 `method` / `checked_at` / `locator` | 报错 |
| **算术锁** | `coverage` 的 `total/audited/verified/unverifiable/misattributed/fabricated` 必须与 `items` 明细逐项一致 | 报错 |
| **清单锁** | 核验集合必须**恰好等于** packet 的 `citations[]`：漏项、多出清单外 id 都报错（覆盖率 100%） | 报错 |

### 6.3 抽样锁（GATE 之后，主 Agent 执行）

主 Agent 从 `verified` 里**随机抽 ≥2 条**复核 `method` 所述动作是否真的做过（打开来源、比对数字），把结果写进 `gate.md` 的 `citation_spotcheck`。若抽查发现「声称 verified 但实际没查」，B 的报告作废重写。

### 6.4 判定与后果

| verdict | 含义 | 后果 |
| --- | --- | --- |
| `verified` | 来源存在且结论一致 | — |
| `unverifiable` | 打不开/无权限/需付费，无法确认 | 计入比例；>20% 禁 PASS |
| `misattributed` | 来源存在但结论被写反/夸大 | **evidence 维度封顶 60** |
| `fabricated` | 查无此文 | **一票否决 `fabricated_citation`** |
| `stale` | 来源过期（政策/价格/版本已变） | 记录，不单独否决 |

- **离线模式（`mode: offline`）禁止判 `verified`**：没有网络只能记 `unverifiable`，并给出警告——离线核验不得让合并结论 PASS。
- `fabricated` 一旦出现但 `gates_triggered` 没写 `fabricated_citation` → 直接报错。

---

## 7. 教练（COACH，环内 RSI）

COACH 是**环内**角色：每轮评审结束后运行，读评审报告产出可执行的改进条目。它**不评分、不改产物、不派活**。

### 7.1 输入

| 输入 | 说明 |
| --- | --- |
| 本轮 `review_report_*.md` | 全部评审的 `errors` / `optimizations` |
| `review_scores.md` | 合并分、维度分、分歧 |
| 上轮 `rsi_report.md` | 用于命中率与 stuck 判定 |
| 上轮 `dispatch.md` | 已下发的教练条目（`coach_items`） |

**不读** run_report 与主 Agent 的解释（与评审同等的独立性要求）。

### 7.2 输出结构（`iterations/iter-NN/rsi_report.md`）

```yaml
schema_version: 1
iteration: 2
tier: Large
verdict_in: REVISE            # 必须等于本轮合并结论
score_in: 74                  # 必须等于本轮合并总分
error_taxonomy:               # 错误分类 + 信用分配
  - class: evidence_gap
    count: 4
    attributed_to: [w03, plan.step-2]
items:                        # ≤8 条，must_fix ≤3 条
  - id: C1
    from_error: [E2, B:E5]    # 必须是本轮真实 error id
    applies_to: [w03]         # 只下发给这些 worker
    priority: must_fix        # must_fix / should_fix / nice_to_have
    root_cause: "..."
    action: "..."
    verification: "..."       # 如何验证这条被做到
escalations:                  # 连续两轮复发的类别必须升级
  - class: evidence_gap
    reason: "..."
rsi_skipped: ""               # 本轮不教练时的理由（PASS 轮可跳过）
advisory_input:               # 仅最后一轮
  estimated_gain_next_round: 8
  remaining_gaps: ["..."]
  diminishing: true
  rationale: "至少 10 字的理由，由教练写"
```

### 7.3 硬约束（全部代码校验）

| 约束 | 规则 |
| --- | --- |
| 结构锁 | 每条 `items` 必须有 `root_cause` / `action` / `verification` / `priority` / `applies_to` / `from_error` |
| 事实锁 | 报告正文与条目里**不得出现 packet 之外的 URL**（教练不得引入新事实） |
| 引用锁 | `from_error` 必须指向**本轮真实存在**的 error id；多评审下有歧义要写 `A:E3` 形式 |
| 归属锁 | `attributed_to` / `applies_to` 只能是 `wNN` / `plan.step-N` / `final` / `main` / `all` |
| 预算锁 | `items ≤ 8`，`must_fix ≤ 3` |
| 升级锁 | `state.coach.stuck_classes`（连续两轮复发）里的每个类别，必须出现在 `escalations` |
| 跳过锁 | FAIL/REVISE 轮必须给 `items` 或写明 `rsi_skipped`；PASS 轮可跳过但要写理由 |
| 越权锁 | 教练不得改 `final_result.md` / 不得写 `gate.md` / 不得指定 worker 以外的人干活 |

### 7.4 切片锁（DISPATCH 阶段强制）

`coach_items` 按 `applies_to` 逐 worker 下发：

- `applies_to: [w03]` 的条目**只能**出现在 `w03` 的 `coach_items` 里；
- 声称「已下发」但目标 worker 的 `coach_items` 里没有 → 报错「该 worker 的 coach_items 里没有」；
- 不想下发必须显式写 `coach_deferred: [{id, reason}]`，**不允许静默删除**。

### 7.5 教练命中率

`state.coach.history[]` 记录每轮条目与其覆盖的错误：

```
hit_rate = 上一轮条目覆盖的错误中，本轮不再出现的比例
```

- 第 1 轮没有「上一轮」，`hit_rate = None`（不参与统计）。
- 命中率持续走低 → 说明教练在写无效条目，应在 `dream_hints` 里提出（但**环内不改尺子**）。

---

## 8. 末轮建议（`iteration_advisory.md`）

数字由代码算，理由由教练写——防止「自评 90 分、顺便建议再来三轮」。

| 字段 | 来源 |
| --- | --- |
| `score` / `verdict` / `prev_score` / `delta` / `trend` | 代码读 `state.scores` |
| `weakest_dimension` / `gap_to_pass` | 代码读合并维度分 |
| `recommendation` / `recommended_rounds` | 代码按规则表算 |
| `rationale` | 教练 `advisory_input.rationale`（≥10 字） |

推荐规则（`compute_advisory`）：

| 情形 | 建议 |
| --- | --- |
| FAIL 且 gap > 20 | continue，2 轮 |
| FAIL 且 gap ≤ 20 | continue，1 轮 |
| REVISE 且本轮无提升、历史最大增益 ≤2 | stop，0 轮 |
| REVISE 且 gap ≤ 单轮预期增益 | continue，1 轮 |
| REVISE 且 gap > 单轮预期增益 | continue，2 轮 |
| PASS 且本轮提升 < 噪声下限(5) | stop |
| PASS 且最弱维度 < 80 | continue，1 轮 |
| PASS 且最弱维度 ≥ 80 | stop |

轮数上限 `min(3, 10 - n)`；算出 0 轮即 `recommendation: stop`。

`iteration_advisory.md` 由脚本生成，**手改会被 `check` 逐字段比对拒绝**。

---

## 9. 错误类别（`error_taxonomy.class`）

`unsupported_claim` / `evidence_gap` / `citation_unverified` / `citation_fabricated` / `off_topic` / `incomplete_coverage` / `arithmetic_error` / `format_violation` / `plan_gap` / `tool_failure` / `cost_overrun`；旧格式字符串 errors 合成时用 `unclassified`（统计复发率时忽略）。

同一类别**连续两轮**出现 → 记入 `state.coach.stuck_classes`：

- 下一轮 `plan.md` 必须写 `addresses_errors: [<class>...]`；
- 本轮 `rsi_report.md` 必须写 `escalations`。

这条把「反复犯同一个错」从提示词劝告变成**状态机无法绕过的检查**。

---

## 10. 反模式（校验会拒或人工判 FAIL）

- 评审只写「整体不错/建议优化」而不给证据 → `unsupported_claims`。
- 六维全 85、errors 空、evidence 全指 packet → C4 证据密度拒绝。
- 两位评审分数差 30 分但平均仍 PASS → C3 分歧门禁降级。
- 教练条目 `from_error` 指向不存在的 error，或把 `applies_to` 写成不存在的 worker → 引用锁/归属锁拒绝。
- 教练条目里塞新链接当作「补充资料」 → 事实锁拒绝。
- 反复 promote 策略只为「看起来在进化」 → 环外 `dream` 的门槛（holdout / golden / noise_floor）拒绝。
