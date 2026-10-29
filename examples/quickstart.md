# 快速上手示例（v2.0）

下面用几个小例子展示 teamwork 的实际用法。所有示例都假设你已经安装好技能（见 [INSTALL-DSH](../docs/INSTALL-DSH.md) / [INSTALL-CLAUDE-CODE](../docs/INSTALL-CLAUDE-CODE.md)），或在仓库根目录直接使用 `skills/teamwork/scripts/orchestrator.py`。

---

## 示例 1：Small 任务（1 轮，2 个 Worker）

对话输入（三种写法等价）：

```text
teamwork, N=1 读取 README.md 与 docs/COMMANDS.md，写一份一页的中文速查表到 docs/QUICKREF.md
用 teamwork 跑：N=1 读取 README.md 与 docs/COMMANDS.md，写一份一页的中文速查表到 docs/QUICKREF.md
/teamwork:run N=1 读取 README.md 与 docs/COMMANDS.md，写一份一页的中文速查表到 docs/QUICKREF.md
```

主 Agent 会：

1. `init` 建 run（Small，自动 N=1）；
2. `classify`：`signals: files 2 / external false / verifiable true / parallel true / risk low`；
3. `plan` + `dispatch`：2 个 Worker（w01 读 README、w02 读 COMMANDS）；
4. `workers`：两个子 Agent 各写 `wNN_artifacts/` + `wNN_result.md`；
5. `final`：Small 级由主 Agent 直接汇总（不新开 Final Agent）；
6. `gate` → `review`（全新独立审核）→ **`coach`**（把本轮 errors 转成改进条目）→ `done`。

产物：

```text
teamwork-runs/20261029-101500-写一份中文速查表/
├── 00_intake/{task.md,classification.md}
├── 01_plans/{plan-iter-01.md,dispatch-iter-01.md}
├── iterations/iter-01/
│   ├── workers/{w01_result.md,w01_artifacts/,w02_result.md,w02_artifacts/}
│   ├── final_result.md
│   ├── run_report.md
│   ├── review_packet.md
│   ├── gate.md
│   ├── review_report_A.md
│   ├── review_scores.md
│   ├── rsi_report.md              # COACH 改进条目
│   └── iteration_advisory.md      # 末轮建议（脚本生成）
├── review_policy/v0.md
├── final_report.md
├── PROGRESS.md
└── framework.mmd（有 matplotlib 时还有 framework.png / score_trend.png）
```

> 每轮 COACH 都会写 `rsi_report.md`；`iteration_advisory.md` 在最后一轮生成，`final_report.md` 必须写 `advisory_response: accept|decline` 才能 `finish`。

---

## 示例 2：Medium 任务（2 轮，3 个 Worker 复用）

```text
/teamwork:run N=2 对比 docs/ 下三份设计文档的接口差异，输出差异表与修改建议
```

要点：

- 第 1 轮：3 个 Worker 并行读三份文档；审核给出 REVISE；
- COACH：把 REVISE 的 errors 归成 3–5 条改进条目（如"差异表缺 API 签名""未标注文档版本"），按 `applies_to` 分给 w01/w02；
- 第 2 轮：**复用** w01–w03（不新建逻辑 id），dispatch 里带 `coach_items` 定点修订；
- 若第 2 轮仍未达 PASS，主 Agent 看 `iteration_advisory.md` 的建议轮数，或 `set-n 3` 再给一轮（需用户同意或按 N 上限）。

---

## 示例 3：Large 任务（L 级 Final Agent + 双评审 + 多轮）

```text
teamwork, N=3 读 <项目目录>，基于代码与文档写一份 20 页技术方案，要求每章有证据引用
```

- 6 个 Worker 分域取证（代码结构、测试、接口、依赖、风险、外部资料）；
- `FINAL` 阶段由**全新 Final Agent** 汇总（L 级规则），产出 `final_result.md` + `run_report.md`；
- `make-packet` 会从 `sources` 提取 `citations`（≤40 条），L 级默认自动设 **A 通用 + B 引用核验** 两位评审；
- GATE 验收 PASS 后进独立审核；B 报告逐条给 `verified / unverifiable / misattributed / fabricated / stale`，`fabricated` 直接一票否决；
- COACH 把两位评审的 errors 合并成改进条目（引用写 `A:E3` / `B:E7`），下轮切片下发；
- 每轮结束在 `PROGRESS.md` 看分数轨迹（例如 72 FAIL → 74 FAIL → 88 PASS）。

---

## 示例 4：纯 CLI（不用对话，脚本化）

```bash
cd muti-Agent-teamwork
export TEAMWORK_RUNS_ROOT=$PWD/teamwork-runs

# 1) 初始化
python3 skills/teamwork/scripts/orchestrator.py init \
  --cmd "teamwork, N=1 生成一个 hello world 的 README" --json

# 2) 查看下一步（返回唯一合法动作 + 模板 + 子 Agent 角色/agent_name）
python3 skills/teamwork/scripts/orchestrator.py next

# 3) 按 next 的提示写 classification / plan / dispatch / worker 产物……

# 4) 每写完一个阶段
python3 skills/teamwork/scripts/orchestrator.py check
python3 skills/teamwork/scripts/orchestrator.py advance --json
```

> CLI 模式适合演示"产物契约"或做 CI 冒烟测试；真实使用建议交给 Agent 执行，因为需要生成大量符合契约的 Markdown。

---

## 示例 5：查看一次运行的全貌

```bash
RUN=teamwork-runs/20261029-101500-写一份中文速查表

cat $RUN/PROGRESS.md                 # 轮次/阶段/分数轨迹
cat $RUN/final_report.md             # 最终报告（轮次、分数、交付物、复现命令）
cat $RUN/iterations/iter-01/rsi_report.md        # 教练条目
cat $RUN/iterations/iter-01/iteration_advisory.md # 末轮建议
python3 skills/teamwork/scripts/orchestrator.py status $RUN
python3 skills/teamwork/scripts/orchestrator.py coach-show $RUN
python3 skills/teamwork/scripts/orchestrator.py render $RUN --trend
```

---

## 示例 6：环外（跨 run）沉淀

跑过几次以后，把 run 落库并蒸馏教训：

```bash
export TEAMWORK_EXPERIENCE_HOME=$HOME/.teamwork/experience

python3 skills/teamwork/scripts/sleep.py all teamwork-runs/<run1> teamwork-runs/<run2>
python3 skills/teamwork/scripts/sleep.py metrics      # 首轮通过率 / 达 PASS 中位轮数 / 命中率
python3 skills/teamwork/scripts/sleep.py calibrate    # 什么规模配几个人（只读）
```

样本不足（<2 个 run 或 <2 个不同 task_hash）时，`dream --propose` 会直接拒绝提晋级——这是设计上的保护。

---

## 小提示

- 任务太简单（单文件、10 分钟能完成）不要用 teamwork，直接做更快；
- 任务描述里写清"输入在哪、输出到哪、验收标准"，能显著降低轮次；
- 需要更严审核时用 `reviewers --count 3`（需用户确认成本）；
- 引用密集的任务不要关 `citation-audit`，它是防编造的主要手段；
- 运行中想停：`orchestrator.py stop`，产物与现场都会保留；之后可继续同一 run。
