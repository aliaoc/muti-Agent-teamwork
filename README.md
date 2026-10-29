# teamwork · 多子 Agent 迭代协作插件

<p align="center">
  <a href="https://github.com/aliaoc/muti-Agent-teamwork/actions/workflows/selftest.yml"><img alt="selftest" src="https://github.com/aliaoc/muti-Agent-teamwork/actions/workflows/selftest.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="license" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <a href="https://www.python.org/downloads/"><img alt="python" src="https://img.shields.io/badge/python-3.10%2B-blue.svg"></a>
</p>

<p align="center">
  <b>把复杂任务交给「主 Agent + 多个 Worker + 独立审核 Agent」，分级、N 轮迭代、每阶段落盘、可审计。</b><br/>
  Claude Code / DeepSeek Harness / 任意 Agent 运行时通用 · Python 3.10+ · MIT
</p>

---

## 目录

- [1. 这是什么](#1-这是什么)
- [2. 核心特性](#2-核心特性)
- [3. 仓库结构](#3-仓库结构)
- [4. 快速开始](#4-快速开始)
- [5. 调用方式与命令](#5-调用方式与命令)
- [6. 分级与人数上限](#6-分级与人数上限)
- [7. 工作流与角色](#7-工作流与角色)
- [8. 产物契约](#8-产物契约)
- [9. RSI 方法：Dream-RSI 如何被用进来](#9-rsi-方法dream-rsi-如何被用进来)
- [10. 校验与安全](#10-校验与安全)
- [11. 实时框架图与进度](#11-实时框架图与进度)
- [12. 配置](#12-配置)
- [13. 开发与测试](#13-开发与测试)
- [14. 常见问题](#14-常见问题)
- [15. 参考与致谢](#15-参考与致谢)
- [16. 贡献](#16-贡献)

---

## 1. 这是什么

`teamwork` 是一个**多子 Agent 协作技能（Agent Skill）**。它把一次复杂任务变成一个有状态、可审计的流水线：

```
主 Agent 理解任务 → 判级(S/M/L) → 规划拆分 → 派发 Worker → 汇总 → 验收门禁
      → 全新独立审核 Agent 评分 → Dream 复盘（审核策略自我改进）→ 下一轮 / 收尾
```

三个最实际的区别：

1. **不是一次性"多开几个 agent"**：整个流程由 `scripts/orchestrator.py` 状态机强制执行，`check` 不通过就拒绝进入下一阶段，AI 无法"自我感觉良好地跳过审核"。
2. **审核是独立、全新、只读证据包的 Agent**：它看不到运行报告和主 Agent 的观点，只能看任务、交付物和证据，避免"自做自评"。
3. **审核标准本身会进化**：借 Dream-RSI 的 replay / offline dreaming 思路，历史迭代被当作可回放的"世界"，审核 rubric 的候选版本在历史证据上回放打分，达到门槛才晋级。

---

## 2. 核心特性

| # | 特性 | 说明 |
|---|------|------|
| 1 | **S/M/L 分级** | 按文件数、外部检索、可验证性、并行度、风险判断；等级决定规划详细度、人数、默认轮数 |
| 2 | **代码即流程** | 阶段机、门禁、评分合成、晋级判定全部写成 Python 代码，不依赖提示词自觉 |
| 3 | **按 run 计数的人数上限** | Small 2 / Medium 4 / Large 7（+Final ≤ 8），同一对话多个任务各自独立计数 |
| 4 | **Worker 跨轮复用** | 同一 run 内第 2 轮起沿用 `wNN` 逻辑 id，worker 名带 run 指纹（`tw-<hash>-w01`） |
| 5 | **独立审核** | `review_packet.md` 物理隔离证据；审核 Agent 全新启动、禁读运行报告/内部账本/其他评审 |
| 6 | **Dream-RSI 式复盘** | 历史轮次 = replay 世界；审核策略候选在历史桶上重放打分，过门槛才 promote |
| 7 | **中间产物全 Markdown** | 人可读、可 diff、可审计；唯一例外是内部账本 `.teamwork/state.json` |
| 8 | **实时框架图** | 每阶段推进渲染协作框架图 + 状态行（无 matplotlib 的环境自动降级为 Mermaid/文本） |

---

## 3. 仓库结构

```
muti-Agent-teamwork/
├── skills/teamwork/                 # ★ 技能包（唯一事实来源）
│   ├── SKILL.md                     # 技能入口：何时启用、命令、主循环、纪律
│   ├── scripts/
│   │   ├── teamwork_lib.py          # 共享库：状态机/校验/评分合成/路径映射/命令解析
│   │   ├── orchestrator.py          # CLI：init/next/status/check/advance/...
│   │   ├── render_text.py           # 文字产物：framework.mmd + PROGRESS.md（无第三方依赖）
│   │   ├── render_diagram.py        # PNG 渲染（matplotlib 可选，中文字体自动探测）
│   │   ├── validate.py              # 独立校验 CLI（exit 2 = 不通过）
│   │   └── selftest.py              # 13 阶段端到端自检（含双评审/REWORK/降级）
│   ├── references/                  # 渐进披露：协议/分级/rubric/产物契约/图示
│   └── assets/templates/            # 10 个产物模板（Markdown + YAML frontmatter）
├── .claude/                         # Claude Code 项目级技能（与 skills/ 同步）
│   ├── skills/teamwork/             #   ↳ 由 tools/sync_claude.py 生成
│   └── ...                          #   （插件清单在 .claude-plugin/）
├── .claude-plugin/
│   ├── plugin.json                  # Claude Code 插件清单
│   └── marketplace.json             # 单插件市场清单（/plugin marketplace add owner/repo）
├── CONTRIBUTING.md                  # 贡献指南：唯一事实来源 / 同步规则 / PR 流程 / 网页编辑
├── CHANGELOG.md                     # 版本记录（Keep a Changelog）
├── commands/run.md                  # /teamwork:run 快捷命令
├── install/                         # install.sh / install.ps1
├── tools/sync_claude.py             # 同步 + --check（CI 用）
├── tools/check.py                   # 本地一条命令等价 CI（py_compile + sync + selftest）
├── examples/                        # 快速上手示例
├── docs/                            # ARCHITECTURE / RSI-DESIGN / COMMANDS / INSTALL-*
└── .github/                         # CI（selftest）、PR 模板、Issue 模板、CODEOWNERS
```

---

## 4. 快速开始

### 4.1 Claude Code

**方式 A：作为插件安装（推荐，`/teamwork:run` 命令可用）**

```bash
# 1) 添加插件市场（本仓库根目录带 .claude-plugin/marketplace.json）
/plugin marketplace add aliaoc/muti-Agent-teamwork

# 2) 安装插件
/plugin install teamwork@muti-agent-teamwork

# 3) 新会话里使用
/teamwork:run N=3 帮我调研并写一份技术方案
```

**方式 B：作为项目技能使用（无需安装）**

仓库内已经带 `.claude/skills/teamwork/`，把仓库克隆到项目里，或把该目录复制到你的项目：

```bash
git clone https://github.com/aliaoc/muti-Agent-teamwork.git
cp -R muti-Agent-teamwork/.claude/skills/teamwork <你的项目>/.claude/skills/teamwork
```

Claude Code 在该项目内会自动发现并加载，直接说"用 teamwork 跑这个任务"即可。

**方式 C：安装为个人技能（所有项目可用）**

```bash
# macOS / Linux / WSL / Git Bash
./install/install.sh --claude

# Windows PowerShell
.\install\install.ps1 -Mode claude
```

安装脚本会：检查 PyYAML → 复制到 `~/.claude/skills/teamwork` → 验证 CLI 入口；加 `--test`（PowerShell `-Test`）可顺带跑 13 阶段自检。

### 4.2 DeepSeek Harness

```bash
# macOS / Linux：安装到 DSH 技能目录
./install/install.sh --dsh
# 默认 D:/apps/deepseek-harness/data/skills，可用 DSH_SKILLS_DIR 覆盖

# Windows PowerShell
.\install\install.ps1 -Mode dsh
```

或手工复制：

```bash
cp -R skills/teamwork "D:/apps/deepseek-harness/data/skills/teamwork"
```

新开会话后，技能清单出现 `teamwork`，在对话里输入启动命令：

```text
teamwork, N=3 读取 <文件/目录>，产出 <结果>，放到 <位置>
```

### 4.3 纯命令行（任何语言/脚本都可调用）

```bash
# 初始化一个 run
python3 skills/teamwork/scripts/orchestrator.py init \
    --cmd "teamwork, N=1 整理一份可行方案并给出证据" --json

# 查看当前阶段应做什么
python3 skills/teamwork/scripts/orchestrator.py next <run_dir>

# 产出文件后校验、推进
python3 skills/teamwork/scripts/orchestrator.py check <run_dir>
python3 skills/teamwork/scripts/orchestrator.py advance <run_dir> --json
```

> Windows 下把 `python3` 换成 `python`；若控制台中文乱码，先 `set PYTHONIOENCODING=utf-8`（PowerShell：`$env:PYTHONIOENCODING="utf-8"`）。

---

## 5. 调用方式与命令

### 5.1 对话内触发

| 运行时 | 触发方式 | 说明 |
|--------|----------|------|
| DeepSeek Harness | `teamwork, N=3 <任务>` / `teamwork，N=? <任务>` | 必须由用户显式输入该命令才启动；`N=?` 表示轮数由主 Agent 按分级决定 |
| Claude Code | `/teamwork:run N=3 <任务>` 或自然语言"用 teamwork 跑……" | 技能描述含触发词，Claude 会在匹配时加载 |
| 通用 | 读 `skills/teamwork/SKILL.md`，按其主循环执行 | 任何能读写文件和跑 shell 的 Agent 都可用 |

- `N` 省略或写 `?`：按分级自动取轮数（默认 S=1 / M=2 / L=3，主 Agent 可在 ±1 内调整并**必须播报理由**）。
- 同一对话可以 launch 多个 run；人数上限按**每个 run** 独立计算，互不累计。

### 5.2 CLI 命令清单

所有命令行都是 `python3 scripts/orchestrator.py <子命令> [run_dir] [参数]`；`run_dir` 省略时取 `--root` 下最新 run；`--json` 输出机器可读结果。

| 子命令 | 作用 | 关键参数 / 示例 |
|--------|------|-----------------|
| `init` | 创建 run（task.md / 策略 v0 / state） | `--cmd "teamwork, N=2 …"`、`--root <目录>` |
| `next` | 返回**唯一合法下一步**：指令、必需产物、模板、子 Agent 角色 | `--json` |
| `status` | 当前阶段 / 轮次 / 分数 / 策略版本 / 人数使用 | `--json` |
| `check` | 校验当前阶段产物；不通过 **exit 2** 并给出逐条原因 | `--phase` 可覆盖阶段（调试用） |
| `advance` | 校验通过后推进阶段并落库（含渲染框架图） | `--json` |
| `make-packet` | FINAL 阶段生成审核证据包 `review_packet.md` | 在 final_result/run_report 之后执行 |
| `merge-review` | 合成 A/B… 多份评审 → `review_scores.md` | 双评审时使用 |
| `render` | 重新渲染 `framework.png/.mmd`、`PROGRESS.md`、`score_trend.png` | `<run_dir>` |
| `set-n` | 中途修改总轮数 N（含自动模式） | `--n 4` 或 `--auto` |
| `set-tier` | 中途升降级（记录理由） | `--tier Large --reason "…"` |
| `dual-review` | 兼容入口：1/2 位评审 | `--on` / `--off`（需用户确认） |
| `reviewers` | 设置评审人数（1–26，A–Z） | `--count 3`（>1 需用户确认） |
| `stop` | 请求优雅停止（`.teamwork/STOP`） | |

退出码约定：`0` 成功；`2` 校验失败或命令/参数错误（可直接用于 CI 门禁）。

### 5.3 一次典型会话

```text
用户: /teamwork:run N=3 读 <PPT.md>，优化第 3 章，写一份 2 万字规划报告到 D:\Workspace

主 Agent:
  · init  → run 目录 D:\Workspace\teamwork-runs\20261025-024641-…
  · classify → Large（files 30 / external true / risk medium）→ 播报 N=3、6 个 Worker
  · plan/dispatch → 6 个 Worker（w01–w06），staged：w01–w05 并行 → w06 依赖前五者
  · workers → 6 个子 Agent 各写 artifacts + result.md（含 sha256 与证据）
  · final → Final Agent 融合 v1（结构/引用/评分表），写 final_result + run_report
  · gate → 主 Agent 验收 PASS（需求覆盖/证据齐全/产物存在/计划一致/无阻塞）
  · review → 全新审核 Agent 只读 packet → 81 REVISE，9 条 errors
  · dream  → 历史桶仅 1 轮，策略 keep v0
  · iter 2 → 6 个 Worker 复用（w01–w06）做定点勘误 → 审核 74 FAIL（E1–E15）
  · iter 3 → 再勘误 → 审核 88 PASS → final_report → finish
  · 汇报：72 FAIL → 74 FAIL → 88 PASS；交付 report.pdf/report.md 路径 + 6 项遗留
```

---

## 6. 分级与人数上限

主 Agent 在 `00_intake/classification.md` 写 signals，代码按阈值校验：

| 等级 | 判定信号（满足 ≥2 条） | Worker 数（每 run 累计） | 默认 N | 汇总方式 | 审核 |
|------|------------------------|--------------------------|--------|----------|------|
| **Small** | 单文件/单问答；无外部检索；无可执行验证；<30min；低风险可逆 | 1–2 | 1 | 主 Agent 直接汇总 | 1 位 |
| **Medium** | 2–5 个文件/模块；需检索/对比/小实验；有可验证命令 | 3–4 | 2 | 主 Agent 直接汇总 | 1 位（可加） |
| **Large** | 跨模块/系统；需外部资料或实验；验收多义；>2h；高风险 | 5–7（+Final ≤ 8） | 3 | 全新 Final Agent 汇总 | 1 位起，可 A–Z 最多 26 位 |

规则细节：

- **人数按 run 计**：`registry ∪ 本次派发` 不得超过等级上限；同一对话中第 2 个 run 从零计数。
- **物理 agent 名带 run 指纹**：`tw-<sha1(run_id)[:6]>-w01`、`-final`、`-rev-A`、`-dream`，避免多任务串号。
- **审核人数不占 Worker 额度**：审核是只读证据的评审角色，可按任务需要增加（例如重要交付用 3 位评审取中位数/分歧）。
- **自动 N**：`n = clamp(TIER_DEFAULT_N + n_adjust, 1, 10)`，`n_adjust ∈ {-1,0,1}`；自动模式必须在 classification 里写 `n_reason` 并向用户播报。
- **中途可调**：`set-n` / `set-tier` 会写入 state 与 history，后续轮次按新值执行。

---

## 7. 工作流与角色

### 阶段状态机

```
INIT → CLASSIFY → PLAN → DISPATCH → WORKERS → FINAL → GATE ─PASS→ REVIEW → DREAM → (下一轮 PLAN)
                                   ↑          │                      │
                                   └─REWORK───┘                      └─ 最后一轮 → DONE → final_report
```

| 阶段 | 负责人 | 核心产物 | 门禁 |
|------|--------|----------|------|
| INIT | 主 Agent | `00_intake/task.md`、`review_policy/v0.md`、`state.json` | — |
| CLASSIFY | 主 Agent | `00_intake/classification.md`（tier/signals/n_adjust/workers_planned） | 等级、人数、N、信号齐全 |
| PLAN | 主 Agent | `01_plans/plan-iter-NN.md`（objective/breakdown/criteria/risks） | Large 需 ≥2 备选方案 |
| DISPATCH | 主 Agent | `01_plans/dispatch-iter-NN.md`（mode/workers/deliverables/依赖） | 人数上限、并行不得有依赖 |
| WORKERS | 子 Agent | `iterations/iter-NN/workers/wNN_result.md` + `wNN_artifacts/` | 每个 claim 必须有存在证据、deliverable 带 sha256 |
| FINAL | S/M 主 Agent；L 全新 Final Agent | `final_result.md`、`run_report.md` | coverage 对照验收标准 |
| GATE | 主 Agent | `gate.md`（PASS/REWORK + checklist） | 需求覆盖/证据/产物/一致性/无阻塞；REWORK ≤2 次 |
| REVIEW | **全新独立审核 Agent** | `review_report_A.md`、`review_scores.md` | 只读 packet；六维加权 + 一票否决 |
| DREAM | 审核 Agent（复盘模式） | `review_policy/replay_ledger.md` | 候选策略 replay 打分、晋级门槛 |
| DONE | 主 Agent | `final_report.md` | 分数轨迹、交付物 sha、遗留事项 |

### 角色契约（摘要）

- **主 Agent**：唯一决策者。负责判级、规划、派发、验收、合成最终报告；不直接生成任务结果（避免自评）；所有决策写进文件。
- **Worker**：只做被分配的范围，只写自己的 `wNN_artifacts/` 与 `wNN_result.md`；返回 ≤12 行摘要 + 文件路径；不读其他 worker 产物（除非 dispatch 声明依赖）。
- **Final Agent（仅 L 级）**：只汇总、不新增事实；缺失/冲突要标记而不是编造；输出 `final_result.md` + `run_report.md`。
- **审核 Agent**：全新启动，只读 `review_packet.md` 与其中 artifacts；六维打分（正确性 30 / 完整性 20 / 证据 20 / 鲁棒性 10 / 可维护 10 / 成本 10）+ 一票否决项；输出 errors（带证据定位）与 optimizations（带预期收益）。
- **Dream Agent**：在轮间离线运行，读历史产物与 ledger，生成 ≤3 个策略候选并 replay 打分，写晋级决定。

---

## 8. 产物契约

每次任务一个 run 目录（默认 `./teamwork-runs/<run-id>/`）：

```
<run>/
├── 00_intake/task.md, classification.md
├── 01_plans/plan-iter-01.md, dispatch-iter-01.md, ...
├── iterations/iter-01/
│   ├── workers/w01_result.md  w01_artifacts/...
│   ├── final_result.md  run_report.md
│   ├── review_packet.md  gate.md
│   ├── review_report_A.md  review_scores.md  iteration_summary.md
├── review_policy/v0.md, replay_ledger.md
├── final_report.md
├── PROGRESS.md
├── framework.png  framework.mmd  score_trend.png
└── .teamwork/state.json
```

契约要点：

- **除 `state.json` 与图片外，全部是 Markdown + YAML frontmatter**：机器字段在 frontmatter（tier/iteration/sha256/verdict…），正文给人读。
- **append-only**：历史轮次文件不覆盖；后续轮次写入 `iter-NN/` 新目录。
- **证据链**：worker claim 的 `evidence` 必须是 run 内存在路径（不允许只写行号/散文）；deliverable 必带 sha256。
- **审核隔离**：`review_packet.md` 的 `forbidden` 字段明确列出 run_report、state.json、iteration_summary、其他评审记录——审核 Agent 被要求不读这些。
- 校验通过 `orchestrator.py check` 每次写完产物后执行；失败会给出逐条原因（字段缺失、路径不存在、权重不符、算术不一致等）。

各文件字段级说明见 [`references/artifacts.md`](skills/teamwork/references/artifacts.md)。

---

## 9. RSI 方法：Dream-RSI 如何被用进来

> 本章解释插件里"审核标准为什么能越审越准"，以及具体的实现边界。设计与论文出处见 [`docs/RSI-DESIGN.md`](docs/RSI-DESIGN.md)。

### 9.1 背景

**RSI（Recursive Self-Improvement，递归自我改进）** 指系统用自己产生的经验改进自己。Google Research 2026 年开源的 **Dream-RSI**（`google-research/dream-rsi`，arXiv:2609.14858）给出了一个可落地范式：

- **在线探索**：做任务 → 形成 discovery tree（分支 × 精炼尝试）；
- **历史即世界**：把所有历史尝试当作 replay simulator（"sleep 时回放的世界"）；
- **离线做梦**：agent 改写自己的 **探索策略代码**，在历史 replay 世界上回放评估，M 个版本中选最优上线；
- 关键约束：**只改策略代码**，agent / evaluator / task 固定——避免"改打分标准来作弊"。

### 9.2 本插件的三层映射

| Dream-RSI | teamwork 中的对应物 |
|-----------|--------------------|
| 在线 rollout / discovery tree | 每一轮真实执行：worker 产出、Final 汇总、门禁验收、独立审核 |
| replay world（历史尝试） | **历史迭代桶**：每轮冻结的 `(task, plan, final_result, artifacts+sha256, review_scores)` |
| policy code（可改） | `review_policy/vN.md`：rubric 权重、检查顺序、证据要求、必查项 |
| offline dreaming | **DREAM 阶段**：轮间生成 ≤3 个策略候选，在历史桶上重放打分 |
| M=4 版本评测 | 当前版本 + ≤3 个候选 = 4 个版本一起 replay |
| 只改 policy | 只允许改 rubric/检查方法；任务、worker、评分阈值、gate 规则不变 |

### 9.3 replay world 的严格定义

第 i 轮的 replay world 不是"重新跑一遍任务"，而是：

```text
world_i = (task, acceptance_criteria, final_result.md, artifacts 列表 + sha256, 已发生的 review_scores)
```

用候选 rubric 对 world_i **重新打分**（replay_score），不调用 worker、不产生新证据。因为证据已经冻结在产物里，所以 replay 可复现、可审计、成本极低。

### 9.4 候选策略与四个正则化

每次 DREAM 最多 3 个候选，每个候选只允许改一个维度（RRSI 式正则化）：

1. **噪声下限**：历史均值提升未超过 **5 分** 的候选不晋级（防止随机波动被当成改进）。
2. **历史覆盖门槛**：至少 **2 条**历史迭代上不劣于当前版本，才可晋级（防止为单轮过拟合）。
3. **退火编辑预算**：`current_iter ≥ ceil(n/2)` 后，每轮只允许 1 处改动（越到后面越保守）。
4. **成本规则 + 泄漏 critic**：新增检查项必须能区分历史错误类别；rubric 里不得出现具体任务答案、人名、数字（防止"把答案写进评分标准"）。

### 9.5 晋级算法（伪代码）

```python
candidates = propose_policy_edits(history, current_policy, max_edits=3)   # 每候选 1 处改动
versions = [current_policy] + candidates
for v in versions:
    v.replay_score = mean(score(world) for world in history)   # 离线重放，不跑 worker
best = max(versions, key=replay_score)
if (best is not current_policy
    and best.replay_score - current.replay_score > 5          # 噪声下限
    and all(best not regression on w for w in history[:2])    # ≥2 条历史不回归
    and cost_rule_ok(best, ledger)):
    promote(best)        # 写 review_policy/v(N+1).md
else:
    keep(current_policy) # 记 ledger，policy_after 不变
```

`replay_ledger.md` 记录每次的决定、候选、replay 分数与理由。没有足够历史时（第 1 轮）只会 `keep`——这是预期行为，不是失败。

### 9.6 为什么不会失控

- **审核独立性在代码层兜底**：packet 生成时物理剔除运行报告/账本；校验器检查 `inputs_read` 不得含违规路径。
- **replay 不能"重跑任务"**：DREAM 阶段没有 worker 预算，只读历史产物，避免"为了通过审核重新做一遍"。
- **策略改动可审计**：每版 `review_policy/vN.md` 带 sha256；ledger 记录候选与分数；历史策略不删除。
- **门禁与评分分离**：REWORK（验收）由主 Agent 做，评分（审核）由独立 Agent 做，二者互不可替代。

### 9.7 代码位置

| 能力 | 位置 |
|------|------|
| 历史桶 / replay 数据 | `iterations/iter-NN/` + `review_scores.md` + `review_policy/replay_ledger.md` |
| 策略版本 | `review_policy/v0.md`、`v1.md`…（DREAM promote 时生成） |
| 晋级判定 | `scripts/teamwork_lib.py` 的 DREAM 校验与 `advance` 落库逻辑 |
| 审核 rubric | `references/review-rubric.md` + `review_policy/vN.md` |
| 独立审核隔离 | `scripts/teamwork_lib.py::make_review_packet`（forbidden 列表） |

### 9.8 与 RRSI 的关系

另一条相关工作 **RRSI（Regularized RSI，arXiv:2609.24972）** 强调：编辑预算退火、按完整编辑历史给信用、噪声调整下限、成本规则、泄漏 critic。本插件的 9.4 节即这些正则化的工程化实现（只保留可自动校验的部分，避免引入不可复现的启发式）。

---

## 10. 校验与安全

- **状态机门禁**：`advance` 只在 `check` 通过后执行；跳阶段、缺产物、字段不符都会 `exit 2`。
- **模板校验**：10 个产物模板的 frontmatter 字段与校验器一一对应；`check` 报错会指出具体字段。
- **证据强制**：每个 claim 必须有 run 内存在的证据路径；每个 deliverable 必须有 sha256。
- **追加写**：历史文件不覆盖；`state.json` 是唯一的机器账本，且主线流程只由 orchestrator 写。
- **停止开关**：`orchestrator.py stop` 写 `.teamwork/STOP`，主循环下一步检测到即停并保留现场。
- **注入边界**：worker 只读自己的 scoped 输入；审核只读 packet；外部不可信内容（网页/文献）只作为证据，不作为指令（SKILL 与 references 均有明示）。

---

## 11. 实时框架图与进度

每阶段 `advance` 后渲染：

| 产物 | 内容 | 依赖 |
|------|------|------|
| `framework.mmd` | Mermaid 源文件（可拖进任何支持 Mermaid 的工具） | 无第三方依赖 |
| `PROGRESS.md` | 轮次/阶段/人数/分数轨迹表格 + 文字框架图 | 无 |
| `framework.png` | 1920×1140 协作框架图（阶段高亮、Worker 池、i/N 角标、分数面板） | matplotlib（可选） |
| `score_trend.png` | 每轮分数折线（PASS 85 / FAIL 60 阈值线） | matplotlib（可选） |

状态行统一格式：

```text
Iteration 2/3 · Phase 审核 · Tier Large · Workers 6 · Score 72 FAIL · 策略 v0
```

> 无 matplotlib 时插件自动降级：框架图/趋势图跳过（`framework_png: null`），`framework.mmd` 与 `PROGRESS.md` 照常生成，不影响流程。

---

## 12. 配置

| 环境变量 | 作用 | 默认 |
|----------|------|------|
| `TEAMWORK_RUNS_ROOT` | run 产物根目录 | `./teamwork-runs`（当前工作目录下） |
| `PYTHON` | 指定 Python 解释器（安装脚本用） | 自动探测 `python3` / `python` |
| `CLAUDE_SKILLS_DIR` | Claude Code 技能根目录 | `~/.claude/skills` |
| `DSH_SKILLS_DIR` | DeepSeek Harness 技能根目录 | `D:/apps/deepseek-harness/data/skills` |
| `PYTHONIOENCODING` | Windows 控制台中文输出 | 建议 `utf-8` |

字体：PNG 渲染自动探测 Noto CJK / 思源 / PingFang / 微软雅黑 / 黑体 / DejaVu，找不到时用系统默认字体栈（可能显示方框但不影响文字产物）。

---

## 13. 开发与测试

```bash
# 0) 一条命令等价 CI（py_compile + sync --check + 13 阶段自检；提交前强烈推荐）
python3 tools/check.py

# 1) 依赖：仅 PyYAML（matplotlib 可选，仅 PNG 需要）
python3 -m pip install pyyaml

# 2) 13 阶段端到端自检（两轮 run：双评审/REWORK/自动 N/命令格式/兼容性…）
python3 skills/teamwork/scripts/selftest.py

# 3) 同步并校验 .claude/skills 副本（CI 也跑这个）
python3 tools/sync_claude.py
python3 tools/sync_claude.py --check

# 4) 单文件校验（调试用）
python3 skills/teamwork/scripts/validate.py <run_dir> --phase REVIEW --json
```

- `selftest.py` 会生成临时 run 到 `$TEAMWORK_RUNS_ROOT/_selftest/`；默认在仓库内 `teamwork-runs/`（已被 .gitignore）。
- CI 在 Ubuntu/Windows × Python 3.10/3.12 上跑：`sync --check` + `py_compile` + 13 阶段自检；其中「Ubuntu + py3.12」装 matplotlib 覆盖 PNG 渲染路径，其余组合验证无 matplotlib 的降级路径（PNG 断言自动跳过）。
- 修改脚本后请同时更新 `.claude/skills/teamwork`（`python3 tools/sync_claude.py`），否则 CI 失败。

---

## 14. 常见问题

<details>
<summary><b>Q1：会不会很贵/很慢？</b></summary>

Small 默认 1 轮、1–2 个 Worker；Medium 2 轮 3–4 个；只有 Large 才会到 6–8 个 Agent。每阶段产物落盘，可随时中断、查看、继续；没必要时不会启动（必须用户显式输入 `teamwork, N=…` 才启动）。
</details>

<details>
<summary><b>Q2：没有 matplotlib 能用吗？</b></summary>

能。文字产物（Mermaid + PROGRESS.md）是主路径，PNG 只是可选增强；`init` 会返回 `framework_png: null` 并提示跳过原因。
</details>

<details>
<summary><b>Q3：Windows 支持吗？</b></summary>

是。提供 `install.ps1`；建议 `$env:PYTHONIOENCODING="utf-8"` 避免控制台中文乱码；路径全部用 `pathlib` 处理。
</details>

<details>
<summary><b>Q4：和普通"多开 subagent"有什么区别？</b></summary>

- 有状态机与门禁（`check` 拒绝跳步）；
- 审核独立且只读证据包（防自评）；
- 产物有契约与 sha256（可追溯、可复算）；
- 审核策略会基于历史 replay 进化（Dream-RSI 思路）；
- 会话可恢复（state.json + 文件即接口）。
</details>

<details>
<summary><b>Q5：能只跑一轮吗？</b></summary>

可以：`N=1`；Small 任务默认就是 1 轮。
</details>

<details>
<summary><b>Q6：审核分数客观吗？</b></summary>

独立输入 + 强制证据 + 可复算算术 + 多评审平均/分歧记录，能显著降低"自嗨"，但不能完全消除主观性；重要交付建议用 2–3 位评审（`reviewers --count 3`）。
</details>

<details>
<summary><b>Q7：如何扩展到新领域？</b></summary>

通常只需改任务描述与 worker 分派（`plan`/`dispatch`）；深度定制改 `references/`（协议/rubric）即可，状态机不需要动。
</details>

<details>
<summary><b>Q8：为什么中间文件必须是 Markdown？</b></summary>

人可读、可 git diff、可审计、可被任何 Agent 读；机器状态集中在 `state.json` 一处，避免"账本散落各文件"。
</details>

<details>
<summary><b>Q9：中途失败/卡住怎么办？</b></summary>

`check` 会给出逐条原因，修对应文件再推进；GATE 的 REWORK 最多 2 次；`stop` 可优雅停止并保留现场，之后直接对同一 run 继续。
</details>

<details>
<summary><b>Q10：`.claude/skills` 和插件安装会冲突吗？</b></summary>

两者只是两种加载方式，建议二选一。仓库内两份保持字节一致（`tools/sync_claude.py --check` 在 CI 中强制），不会出现"改了一份忘了另一份"。
</details>

---

## 15. 参考与致谢

- **Dream-RSI** — Google Research，`https://github.com/google-research/dream-rsi`，arXiv:2609.14858（在线探索 + 历史 replay world + offline dreaming 的策略自我改进范式）。
- **RRSI（Regularized RSI）** — `https://github.com/google-research/rrsi`，arXiv:2609.24972（编辑预算退火、噪声下限、成本规则、泄漏 critic 等正则化）。
- **Claude Code 插件与技能文档** — `https://code.claude.com/docs/en/plugins/overview`、`https://code.claude.com/docs/en/skills`。
- **DeepSeek Harness 技能机制** — 本地 `data/skills/` 目录 + `SKILL.md` frontmatter（name/description 触发）。

> 本仓库中的 RSI 实现是**工程近似**：我们借用其"历史 replay + 策略离线进化 + 只改策略"的思想，但不对应论文的原始实验设置，也没有复现其分数。论文出处仅用于说明设计来源。

---

## 16. 贡献

- 完整流程见 [CONTRIBUTING.md](CONTRIBUTING.md)：唯一事实来源（只改 `skills/teamwork/`）、生成物同步（`.claude/skills` 必须由 `tools/sync_claude.py` 生成）、兼容性纪律、PR 规范，以及**不装本地环境时在 GitHub 网页上直接编辑**的步骤。
- 提交前跑 `python3 tools/check.py`；PR 需要 4 个 CI 矩阵任务全绿。
- 计划类改动（阶段/产物字段/评分规则/默认值）请先开 Issue 讨论；小修与文档可直接提 PR。
- 首次贡献建议从文档、示例、FAQ 或 `.github/ISSUE_TEMPLATE` 里标注的需求入手。

---

## License

[MIT](LICENSE) © 2026 aliaoc
