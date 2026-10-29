# teamwork · 多子 Agent 迭代协作插件

<p align="center">
  <a href="https://github.com/aliaoc/muti-Agent-teamwork/actions/workflows/selftest.yml"><img alt="selftest" src="https://github.com/aliaoc/muti-Agent-teamwork/actions/workflows/selftest.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="license" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <a href="https://www.python.org/downloads/"><img alt="python" src="https://img.shields.io/badge/python-3.10%2B-blue.svg"></a>
</p>

<p align="center">
  <b>把复杂任务交给「主 Agent + 多个 Worker + 独立审核 Agent + RSI 教练」，分级、N 轮迭代、每阶段落盘、可审计。</b><br/>
  Claude Code / DeepSeek Harness / WorkBuddy / 任意 Agent 运行时通用 · Python 3.10+ · MIT
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
- [9. RSI 方法：三个时间尺度](#9-rsi-方法三个时间尺度)
- [10. 引用核验（L 级 Reviewer B）](#10-引用核验l-级-reviewer-b)
- [11. 校验与安全](#11-校验与安全)
- [12. 实时框架图与进度](#12-实时框架图与进度)
- [13. 配置](#13-配置)
- [14. 开发与测试](#14-开发与测试)
- [15. 常见问题](#15-常见问题)
- [16. 参考与致谢](#16-参考与致谢)
- [17. 贡献](#17-贡献)

---

## 1. 这是什么

`teamwork` 是一个**多子 Agent 协作技能（Agent Skill）**。它把一次复杂任务变成一个有状态、可审计、还能自我改进的流水线：

```text
主 Agent 理解任务 → 判级(S/M/L) → 规划拆分 → 派发 Worker → 汇总 → 验收门禁
      → 全新独立审核 Agent 评分（L 级含引用核验）→ RSI 教练产出改进条目
      → 下一轮（改进条目按 worker 切片下发）/ 收尾
```

与"随手多开几个 agent"的四个实际差别：

1. **流程是代码，不是提示词**。阶段机、门禁、评分合成、引用核验、教练条目切片、轮次建议全部写在 `scripts/teamwork_lib.py` 里；`check` 不通过就 `exit 2` 拒绝推进，AI 无法"自我感觉良好地跳过审核"。
2. **审核独立且输入被物理裁剪**。审核 Agent 全新启动，只读 `review_packet.md` 与其中列出的 artifacts，看不到运行报告、内部账本和主 Agent 的观点；`inputs_read` 里出现禁止路径直接判独立性失效。
3. **审核标准会进化，但不在环内改**。环内（每轮）只改"做法"；改"尺子"必须跨 run、带 holdout、过噪声下限（详见 [第 9 章](#9-rsi-方法三个时间尺度)）。
4. **结论可复算**。每条 claim 带 run 内存在的证据路径，每个交付物带 sha256，评分表算术由脚本复核，多评审分歧超阈值强制降级。

一句话：**给"多智能体干活"加上状态机、证据链和独立的裁判**。

---

## 2. 核心特性

| # | 特性 | 说明 |
|---|------|------|
| 1 | **S/M/L 分级** | 按文件数、外部检索、可验证性、并行度、风险打信号；等级决定规划深度、人数、默认轮数、审核档 |
| 2 | **代码即流程** | 10 阶段状态机 + 逐阶段字段校验；跳阶段、缺产物、算术不一致一律 `exit 2` |
| 3 | **按 run 计数的人数上限** | Small 2 / Medium 4 / Large 7（+Final ≤ 8），**同一对话多个任务各自独立计数** |
| 4 | **Worker 跨轮复用** | 同一 run 第 2 轮起沿用 `wNN` 逻辑 id；物理 agent 名带 run 指纹（`tw-<hash>-w01`）防串号 |
| 5 | **独立审核 + 多评审** | 1–26 位评审（A–Z）；平均分、任一 FAIL 即 FAIL、维度分歧 >10 强制降级 REVISE |
| 6 | **引用核验（L 级默认）** | Reviewer B 逐条核验 `sources[]` 真伪；三把锁 + GATE 后抽样复核 + 虚构来源一票否决 |
| 7 | **RSI 教练（COACH）** | 每轮读评审产出**可执行改进条目**（≤8 条、must_fix ≤3），按 `applies_to` 切片下发给 Worker，遗漏必须显式记录 |
| 8 | **末轮建议由代码算** | `iteration_advisory.md` 给出"是否续跑/续几轮 + 理由要求"，手改会被逐字段拒绝；续跑用 `extend` |
| 9 | **环外经验库** | 跨 run 落库、教训蒸馏、指标看板、规划校准、尺子提案（holdout + 噪声下限 + 反漂移） |
| 10 | **中间产物全 Markdown** | 人可读、可 diff、可审计；唯一例外是内部账本 `.teamwork/state.json` |
| 11 | **实时框架图** | 每阶段推进渲染框架图 + 状态行；无 matplotlib 自动降级为 Mermaid + PROGRESS.md |
| 12 | **多运行时** | Claude Code（插件/项目技能/个人技能）、DeepSeek Harness、WorkBuddy、纯 CLI |

---

## 3. 仓库结构

```text
muti-Agent-teamwork/
├── skills/teamwork/                 # ★ 技能包（唯一事实来源，改这里）
│   ├── SKILL.md                     # 技能入口：何时启用、启动、主循环、纪律
│   ├── scripts/
│   │   ├── teamwork_lib.py          # 状态机/校验/评分合成/引用核验/教练切片/路径映射
│   │   ├── orchestrator.py          # CLI：init/next/status/check/advance/…/extend/dream
│   │   ├── rsi_store.py             # 环外经验库：落库、教训蒸馏、指标、尺子提案与批准
│   │   ├── sleep.py                 # 环外"睡眠"任务：record/distill/retire/metrics/calibrate
│   │   ├── render_text.py           # 文字产物：framework.mmd + PROGRESS.md（零第三方依赖）
│   │   ├── render_diagram.py        # PNG 渲染（matplotlib 可选，中文字体自动探测）
│   │   ├── validate.py              # 独立校验 CLI（exit 2 = 不通过）
│   │   └── selftest.py              # 23 阶段端到端自检
│   ├── references/                  # 渐进披露：protocol / tiers / review-rubric / artifacts / diagrams
│   └── assets/templates/            # 13 个产物模板（Markdown + YAML frontmatter）
├── .claude/skills/teamwork/         # 同步副本（由 tools/sync_claude.py 生成，禁止手改）
├── .claude-plugin/
│   ├── plugin.json                  # Claude Code 插件清单
│   └── marketplace.json             # 单插件市场清单（/plugin marketplace add owner/repo）
├── commands/run.md                  # /teamwork:run 快捷命令
├── install/                         # install.sh / install.ps1（claude / dsh 两种模式）
├── tools/sync_claude.py             # 同步 skills → .claude/skills，--check 供 CI 用
├── tools/check.py                   # 本地一条命令等价 CI
├── docs/                            # ARCHITECTURE / RSI-DESIGN / COMMANDS / INSTALL-*
├── examples/quickstart.md           # 六个上手示例
├── CONTRIBUTING.md                  # 贡献指南（含 GitHub 网页直接编辑流程）
├── CHANGELOG.md
└── .github/                         # CI（selftest）、PR 模板、Issue 模板、CODEOWNERS
```

---

## 4. 快速开始

### 4.1 Claude Code

**方式 A：插件安装（推荐，带 `/teamwork:run`）**

```text
# 1) 添加插件市场（仓库根目录带 .claude-plugin/marketplace.json）
/plugin marketplace add aliaoc/muti-Agent-teamwork

# 2) 安装插件
/plugin install teamwork@muti-agent-teamwork

# 3) 新会话（或 /reload-plugins）里使用
/teamwork:run N=3 帮我调研并写一份技术方案
```

**方式 B：项目技能（无需安装）**

```bash
git clone https://github.com/aliaoc/muti-Agent-teamwork.git
cp -R muti-Agent-teamwork/.claude/skills/teamwork <你的项目>/.claude/skills/teamwork
```

在该项目里直接说"用 teamwork 跑这个任务：N=2 …"即可。

**方式 C：个人技能（所有项目可用）**

```bash
./install/install.sh --claude          # macOS / Linux / WSL / Git Bash
.\install\install.ps1 -Mode claude     # Windows PowerShell
```

装到 `~/.claude/skills/teamwork`（可用 `CLAUDE_SKILLS_DIR` 覆盖）；加 `--test` / `-Test` 会顺带跑 23 阶段自检。

### 4.2 DeepSeek Harness

```bash
./install/install.sh --dsh            # 默认 D:/apps/deepseek-harness/data/skills
.\install\install.ps1 -Mode dsh       # Windows
```

或手工：

```bash
cp -R skills/teamwork "D:/apps/deepseek-harness/data/skills/teamwork"
```

新开会话后技能清单出现 `teamwork`（必要时给旧版改名以禁用），然后：

```text
teamwork, N=3 读取 <文件/目录>，产出 <结果>，放到 <位置>
```

### 4.3 WorkBuddy / 其它运行时

把 `skills/teamwork` 整个目录放到该运行时的技能根目录（例如 `~/.workbuddy/skills/teamwork`），
运行时能加载 `SKILL.md` 即可；子 Agent 用该运行时自己的机制（没有就由主 Agent 顺序执行，产物契约不变）。

### 4.4 纯命令行（任何语言/脚本可调用）

```bash
export SKILL_DIR=./skills/teamwork
python3 "$SKILL_DIR/scripts/orchestrator.py" init --cmd "teamwork, N=1 整理一份可行方案并给出证据" --json
python3 "$SKILL_DIR/scripts/orchestrator.py" next      # 打印唯一合法下一步
python3 "$SKILL_DIR/scripts/orchestrator.py" check     # 校验产物（失败 exit 2）
python3 "$SKILL_DIR/scripts/orchestrator.py" advance --json
```

> Windows：`python3` 换成 `python`；控制台中文乱码先 `set PYTHONIOENCODING=utf-8`（PowerShell：`$env:PYTHONIOENCODING="utf-8"`）。

---

## 5. 调用方式与命令

### 5.1 对话内触发

| 运行时 | 触发写法 | 说明 |
|--------|----------|------|
| 通用（含 DSH） | `teamwork, N=3 <任务>` / `teamwork，N=? <任务>` | 必须显式写，**不主动启动**；`N=?` 表示轮数由主 Agent 判决并当场播报 |
| Claude Code | `/teamwork:run N=3 <任务>`、或"用 teamwork 跑：N=3 …" | 技能描述含触发词，匹配时自动加载 |
| 任意运行时 | 读 `skills/teamwork/SKILL.md` 按主循环执行 | 能读写文件 + 跑 shell 即可 |

- `N` 是 1–10 的整数；`N=?` 时 `n = clamp(等级默认值 + n_adjust, 1, 10)`（S=1 / M=2 / L=3，`n_adjust ∈ {-1,0,+1}`），必须写 `n_reason` 并向用户播报。
- 同一对话可以先后开多个 run；**所有人数上限按单个 run 计**，互不占用。

### 5.2 CLI 命令清单

统一入口：`python3 "$SKILL_DIR/scripts/orchestrator.py" <子命令> [run_dir] [选项]`。
`run_dir` 省略时取 `--root`（或 `$TEAMWORK_RUNS_ROOT`，或 `./teamwork-runs`）下最新的 run；`--json` 输出机器可读结果。

| 子命令 | 作用 | 关键参数 |
|--------|------|----------|
| `init` | 创建 run（task.md / 策略 v0 / state.json） | `--cmd "teamwork, N=2 …"`、`--task`、`--root` |
| `next` | 返回**唯一合法下一步**：指令、必需产物、模板、子 Agent 角色与 `agent_name` | `--json` |
| `status` | 阶段 / 轮次 / 分数 / 策略版本 / 人数使用 + 状态行 | `--json` |
| `check` | 校验当前阶段产物；失败 exit 2 并逐条报因 | `--phase`（调试用） |
| `advance` | 校验通过后推进并落库（含渲染框架图） | `--json` |
| `make-packet` | FINAL 阶段生成审核证据包 `review_packet.md` | （须在 final_result/run_report 之后） |
| `merge-review` | 手工重算多评审合成（调试/恢复） | |
| `render` | 重渲染 `framework.*` / `PROGRESS.md` | `--trend` 同时出 `score_trend.png` |
| `finish` | DONE 收尾：校验 final_report、出分数轨迹图、run 落库经验库 | `--json` |
| `set-n` | 中途改总轮数 | `--n 4` |
| `set-tier` | 中途升降级（写理由进 history） | `--tier Large --reason "…"` |
| `reviewers` | 设置评审人数（1–26，A–Z） | `--count 3`（k>1 需用户确认成本） |
| `dual-review` | 兼容入口：1/2 位评审 | `--on` / `--off` |
| `citation-audit` | 开关 L 级引用核验（默认 auto） | `--on` / `--off --reason "…"` |
| `coach-show` | 查看教练条目、命中率、卡住类别 | |
| `extend` | **DONE 后追加轮次**（续跑），旧 final_report 归档 | `--rounds 1..3`、`--force` |
| `dream` | **环外**尺子演进：提案 / 批准 / 回滚（不写 run 目录） | `--propose`、`--approve v1`、`--rollback`、`--offline` |
| `adopt-policy` | 把经验库已批准的策略采纳进当前 run | `--version v1` |
| `stop` | 优雅停止（写 `.teamwork/STOP`，保留现场） | `--reason "…"` |

退出码：`0` 成功；`2` 校验失败 / 参数或命令错误（可直接作 CI 门禁）；`1` 未捕获异常（bug）。

### 5.3 一次典型 L 级会话（3 轮）

```text
用户: teamwork, N=3 读 <语料>，写一份 2 万字规划报告到 D:\Workspace

主 Agent:
 · init        → run 目录 …\teamwork-runs\20261030-…\
 · classify    → Large（files 30 / external true / risk medium）→ 播报 N=3、7 人额度、L 级默认 A+B 双评审
 · plan/dispatch → 6 个 Worker（w01–w06），staged：w01–w05 并行 → w06 依赖前五者
 · workers     → 6 个子 Agent 各写 artifacts + result.md（含 sha256 与证据路径）
 · final       → 全新 Final Agent 汇总 v1，登记 sources[]，写 final_result + run_report
 · make-packet → 生成 review_packet.md（14 个 artifacts + citations）
 · gate        → 主 Agent 验收 PASS（+ 引用抽样复核 ≥2 条）
 · review      → 全新 A（通用）+ B（引用核验）→ 81 REVISE，9 条 errors
 · coach       → rsi_report.md：≤8 条改进条目，must_fix 3 条，按 applies_to 切到 w02/w03/w05
 · iter 2      → dispatch 带 coach_items 切片 → 审核 74 FAIL（E1–E15，2 条 blocker）
 · coach       → 诊断"执行层漏改 + 验收漏项"，命中率与 stuck 类别上报
 · iter 3      → 定点修复 + 交叉引用校正 → 审核 88 PASS
 · advisory    → 脚本算："建议收尾（PASS 且最弱维 ≥80）"
 · done        → final_report.md（advisory_response: accept）→ finish
 · 汇报        → 72 FAIL → 74 FAIL → 88 PASS；报告路径 + sha256 + 6 项遗留
```

---

## 6. 分级与人数上限

主 Agent 在 `00_intake/classification.md` 写 signals，脚本按阈值校验：

| 等级 | 判定信号（≥2 条取较高一级） | Worker 数（每 run 累计） | 默认 N | 汇总方式 | 审核档 |
|------|------------------------------|--------------------------|--------|----------|--------|
| **Small** | 单文件/单问答；无外部检索；30 分钟内；可逆低风险 | 1–2 | 1 | 主 Agent 直接汇总 | 1 位（quick） |
| **Medium** | 2–5 个文件/模块；需检索/对比/小实验；有可验证命令 | 3–4 | 2 | 主 Agent 直接汇总 | 1 位（standard） |
| **Large** | 跨模块/系统；需外部资料或实验；验收多义；>2h；中高风险 | 5–7（+Final ≤ 8） | 3 | 全新 Final Agent | **默认 2 位：A 通用 + B 引用核验** |

规则细节：

- **人数按 run 计**：`registry ∪ 本次派发` 不得超等级上限；同一对话的第 2 个 run 从零计数。L 级 Worker + Final 合计 ≤ 8。
- **物理 agent 名带 run 指纹**：`tw-<sha1(run_id)[:6]>-w01 / -final / -rev-A / -coach`，多任务并行不串号。
- **审核不占 Worker 额度**：1–26 位（A–Z）按任务需要增减，但 k>1 要先向用户说明成本并确认。
- **跨轮复用**：S/M 第 2 轮起原则上不新建 Worker（新建触发 warning）；复用同一 id 只算一个。
- **自动 N**：`n = clamp(TIER_DEFAULT_N[tier] + n_adjust, 1, 10)`，必须写 `n_reason`。
- **中途可调**：`set-n` / `set-tier` 写入 state 与 history；`set-tier` 仅限 INIT/CLASSIFY/PLAN。

---

## 7. 工作流与角色

### 7.1 阶段状态机（10 阶段）

```text
INIT → CLASSIFY → PLAN → DISPATCH → WORKERS → FINAL → GATE ─PASS→ REVIEW → COACH ─┐
                      ▲          ↑                          │                     │
                      │          └──────── REWORK(≤2) ──────┘                     │
                      └──────────────────── iter < n ──────────────────────────────┘
                                                            └─ iter == n → DONE → final_report
```

| 阶段 | 负责人 | 核心产物 | 门禁要点 |
|------|--------|----------|----------|
| INIT | 主 Agent | `00_intake/task.md`、`review_policy/v0.md`、`state.json` | — |
| CLASSIFY | 主 Agent | `00_intake/classification.md` | tier / signals / n_adjust / workers_planned 合法 |
| PLAN | 主 Agent | `01_plans/plan-iter-NN.md` | Large 需 ≥2 备选；`addresses_errors` 正面回应卡住类别 |
| DISPATCH | 主 Agent | `01_plans/dispatch-iter-NN.md` | 人数上限；并行不得有依赖；`coach_items` 切片完整 |
| WORKERS | Worker 子 Agent | `workers/wNN_result.md` + `wNN_artifacts/` | 每条 claim 有存在证据；交付物带 sha256 |
| FINAL | S/M 主 Agent；L 新 Final Agent | `final_result.md`（L 级登记 `sources[]`）+ `run_report.md` | coverage 对照验收标准 |
| GATE | 主 Agent | `gate.md`（PASS/REWORK + `citation_spotcheck`） | 需求覆盖/证据/产物/一致/无阻塞；REWORK ≤2 |
| REVIEW | 全新独立审核 Agent ×k | `review_report_A.md`…、`review_scores.md` | 只读 packet；六维加权 + 一票否决 + C4 证据密度 |
| COACH | **全新 RSI 教练** | `rsi_report.md`；末轮另加脚本生成的 `iteration_advisory.md` | 结构锁/事实锁/引用锁/归属锁/预算锁/升级锁/跳过锁/越权锁 |
| DONE | 主 Agent | `final_report.md`（`advisory_response` 必填） | 分数轨迹 + 交付物 sha + 遗留事项 |

`check` 与 `advance` 是唯一推进入口；`DREAM` 是旧版阶段名，读旧 state 时自动迁移为 `COACH`。

### 7.2 角色契约

- **主 Agent（控制层）**：判级、规划、派发、验收、合成最终报告、播报状态行。不直接产出任务结果（避免自评）；所有决策写进文件。
- **Worker（执行层）**：只做 dispatch 里自己的 scope，只写 `iterations/iter-NN/workers/wNN_*`；claims 必带证据；返回 ≤15 行摘要 + 产物路径；跨轮优先复用。
- **Final Agent（仅 L 级）**：只汇总不新增事实；冲突/缺口要标记而非编造；L 级必须把外部来源登记成 `sources[]`。
- **Reviewer A（general）**：全新、只读 `review_packet.md` 及其 artifacts；六维打分 + 一票否决；errors 用对象格式 `{id, class, located, recurred_from}`。
- **Reviewer B（citation_audit）**：只做引用核验，逐条给 `verified/unverifiable/misattributed/fabricated/stale`，100% 覆盖 `packet.citations`。
- **Coach（RSI 教练）**：全新实例、不继承评审上下文；**不评分、不改产物、不派活**；产出 ≤8 条结构化改进条目，按 `applies_to` 切片下发；不得引入 packet 之外的 URL。

---

## 8. 产物契约

一次任务 = 一个 run 目录（默认 `./teamwork-runs/<run-id>/`）：

```text
<run>/
├── .teamwork/state.json              # 唯一非 Markdown 内部账本（只由 orchestrator 写）
├── 00_intake/{task.md, classification.md}
├── 01_plans/{plan-iter-NN.md, dispatch-iter-NN.md}
├── iterations/iter-NN/
│   ├── workers/{wNN_result.md, wNN_artifacts/…}
│   ├── final_result.md               # L 级含 sources[]
│   ├── run_report.md
│   ├── review_packet.md              # make-packet 生成，禁止手改
│   ├── gate.md                       # 含 citation_spotcheck
│   ├── review_report_A.md … _<k>.md  # 每位独立审核各一份
│   ├── review_scores.md              # advance 自动合成，禁止手改
│   ├── rsi_report.md                 # COACH 产出（教练条目）
│   ├── iteration_advisory.md         # 末轮，脚本生成，禁止手改
│   └── iteration_summary.md
├── review_policy/v0.md
├── final_report.md                   # extend 时旧文件归档为 final_report.iter-NN.md
├── PROGRESS.md
├── framework.mmd / framework.png
└── score_trend.png                   # finish 时生成
```

契约要点：

- **除 `state.json` 与图片外，全部 Markdown + YAML frontmatter**：机器字段在 frontmatter，正文给人读；每个文件带 `schema_version`。
- **append-only**：历史轮次不覆盖，新轮次写新 `iter-NN/`；修正用新文件 + 说明，不删旧证据。
- **证据链**：claim 的 `evidence` 必须是 run 内存在路径（不接受"行号/散文"）；deliverable 必带 sha256；校验器重算比对。
- **审核隔离**：packet 的 `forbidden` 明确列出 `run_report.md`、`state.json`、`iteration_summary.md`、其他评审记录、主 Agent 的规划评价。
- **路径纪律**：run 内一律写相对路径；要交付到 run 外的文件写进 `final_result.delivery`（绝对路径 + sha256），不要混进 `deliverables`。

字段级说明见 [`references/artifacts.md`](skills/teamwork/references/artifacts.md)。

---

## 9. RSI 方法：三个时间尺度

> 这一章解释"为什么它会越做越准"。设计细节见 [`docs/RSI-DESIGN.md`](docs/RSI-DESIGN.md)。

**RSI（Recursive Self-Improvement，递归自我改进）** 指系统用自己产生的经验改进自己。本插件把 Dream-RSI（`google-research/dream-rsi`，arXiv:2609.14858）的"历史即世界 + 离线改进策略 + 只改策略"拆成**三个时间尺度**，并规定**每个尺度只能改什么**：

| 尺度 | 频率 | 允许改 | 谁负责 | 落盘位置 |
|------|------|--------|--------|----------|
| **环内** | 每轮 | **做法**（拆分、取证、格式、验证顺序） | COACH + Worker | `iterations/iter-NN/rsi_report.md`、`rsi_report` 切片进 dispatch |
| **环间** | 每 run 一次 | **继续还是收尾** | 脚本算数字 + 用户决定 | `iteration_advisory.md` → `final_report.advisory_response` / `extend` |
| **环外** | 天/周级 | **教训、规划参数、评分标准** | `sleep.py` / `dream --offline` | `$TEAMWORK_EXPERIENCE_HOME`（默认 `~/.teamwork/experience`） |

**环内不改评分标准。** rubric 是裁判，裁判不能自己改判罚尺度；尺子演进只在环外、跨 run、带 holdout 发生。这条边界是硬编码的：`validate_policy` 拒绝删除 4 个核心门禁，权重变动限 ±10，且只认 `review_policy/vN.md` 这一处真源。

### 9.1 环内：COACH 把评审变成可执行条目

COACH 是每轮 REVIEW 之后的全新角色，读本轮全部评审报告 + 上轮 `rsi_report` + 上轮 dispatch，产出结构化条目：

```yaml
items:                           # ≤8 条，must_fix ≤3
  - id: C1
    from_error: [E2, B:E5]       # 必须指向本轮真实 error id
    applies_to: [w03]            # 只下发给该 worker
    priority: must_fix
    root_cause: "…"
    action: "…"
    verification: "…"
error_taxonomy: [{class: evidence_gap, count: 4, attributed_to: [w03, plan.step-2]}]
escalations: [{class: evidence_gap, reason: "连续两轮复发"}]
```

八把锁（全部代码校验）：结构锁、事实锁（不得引入 packet 外 URL）、引用锁、归属锁、预算锁、升级锁、跳过锁、越权锁。
DISPATCH 阶段还有**切片锁**：`applies_to: [w03]` 的条目必须出现在 w03 的 `coach_items` 里，不下发必须写 `coach_deferred: [{id, reason}]`。

**命中率**：`state.coach.history[]` 记录每轮条目覆盖的错误，下一轮不再出现的比例即命中率；某类错误连续两轮复发 → 标 `stuck_classes`，下一轮 PLAN 必须写 `addresses_errors`，COACH 必须写 `escalations`，否则 `advance` 被拒。这把"反复犯同一个错"从提示词劝告变成状态机无法绕过的检查。

### 9.2 环间：末轮建议由代码算，人只写理由

最后一轮 COACH 阶段，脚本生成 `iteration_advisory.md`（分数、delta、趋势、最弱维、gap 全部取自 state）：

| 情形 | 建议 |
|------|------|
| FAIL 且 gap > 20 | 继续，2 轮 |
| FAIL 且 gap ≤ 20 | 继续，1 轮 |
| REVISE 且本轮无提升、历史最大增益 ≤2 | 收尾 |
| REVISE 且 gap ≤ 单轮预期 | 继续，1 轮 |
| REVISE 且 gap > 单轮预期 | 继续，2 轮 |
| PASS 且本轮提升 < 噪声下限 5 | 收尾 |
| PASS 且最弱维度 < 80 | 继续，1 轮 |
| PASS 且最弱维度 ≥ 80 | 收尾 |

轮数上限 `min(3, 10 - n)`。主 Agent 必须原样播报该建议；用户决定写进 `final_report.advisory_response: accept|decline`（decline 需 ≥10 字理由），否则 `finish` 拒绝收尾。要续跑用 `extend --rounds k`。

### 9.3 环外：经验库与尺子演进

```bash
# 落库 + 蒸馏教训 + 淘汰低效教训 + 刷新看板
python3 "$SKILL_DIR/scripts/sleep.py" all <run_dir>...
python3 "$SKILL_DIR/scripts/sleep.py" metrics      # 首轮通过率/达 PASS 中位轮数/教练命中率/校准误差
python3 "$SKILL_DIR/scripts/sleep.py" calibrate    # 什么规模配几个人（只报告，不改）

# 尺子（评估器）演进：提案 → 人工批准 → 采纳 / 回滚
python3 "$SKILL_DIR/scripts/orchestrator.py" dream --propose
python3 "$SKILL_DIR/scripts/orchestrator.py" dream --approve v1
python3 "$SKILL_DIR/scripts/orchestrator.py" adopt-policy --version v1
python3 "$SKILL_DIR/scripts/orchestrator.py" dream --rollback v1
```

**晋级门槛（`rsi_store.build_proposal` 强制）**——全部满足才允许 promote：

1. **样本量**：≥2 个 run 且 ≥2 个不同 `task_hash`；
2. **必须有 holdout**：按 `task_hash % HOLDOUT_MODULUS` 切出 validation 集，没有就直接拒绝提晋级；
3. **replay 最优**：候选在训练集（历史桶）上重新打分须为最优；
4. **噪声下限**：holdout 上的增益必须 > `noise_floor`（默认 5 分），否则视为波动；
5. **编辑预算**：候选改动数 ≤ `max_edits_per_iteration`（默认 3）；
6. **反漂移**：golden set 上漂移 ≤ ±3 分。

「replay world」不是"重跑任务"，而是对已冻结的 `(task, acceptance, final_result, artifacts+sha256, review_scores)` 用候选 rubric **重新打分**——不调 worker、不产生新证据，因此可复现、可审计、成本极低。这也是产物契约要求"证据落在 run 内 + 交付物带 sha256"的根本原因。

### 9.4 为什么不会跑偏

| 风险 | 兜底 |
|------|------|
| 审核被主 Agent 影响 | packet 物理剔除 run_report/state/iteration_summary；审核 prompt 禁读；`inputs_read` 校验 |
| 改标准放水 | 环内不许改尺子；`validate_policy` 禁删核心门禁、权重限 ±10 |
| 单轮过拟合 | 跨 run + holdout + 噪声下限 + 编辑预算 + golden 反漂移 |
| 用"重跑任务"刷分 | 环外提案只读历史产物，无 worker 预算 |
| 分数不可追溯 | 每版 policy 带 sha256；ledger append-only；历史版本不删 |
| 门禁与评分混同 | REWORK（验收）归主 Agent，评分归独立审核，二者互不可替代 |

---

## 10. 引用核验（L 级 Reviewer B）

只要交付物依赖外部资料，就需要有人真的去核。L 级 + `citation_audit != off` 时，脚本自动把评审设为 2 位（`roles = {A: general, B: citation_audit}`），B 只做一件事：逐条核验 `sources[]`。

1. **登记**：FINAL 阶段在 `final_result.md` 写 `sources[]`（`id/url/title/used_for/locator/contributed_by`），`make-packet` 会转成 packet 的 `citations[]`（上限 40 条）。
2. **三把锁**：
   - 结构锁：判 `verified` 必须给 `method + checked_at + locator`；
   - 算术锁：`coverage` 的 total/audited/verified/… 必须与明细逐项一致；
   - 清单锁：核验集合必须**恰好等于** `citations[]`（覆盖率 100%，漏项或多出都报错）。
3. **判定后果**：`misattributed ≥1` → evidence 维度封顶 60；`unverifiable > 20%` → 不得 PASS；`fabricated` → 一票否决 `fabricated_citation`。
4. **抽样锁**：GATE 后主 Agent 从 `verified` 里随机抽 ≥2 条复核"真去看了吗"，写进 `gate.md.citation_spotcheck`；发现声称已查实则没查，B 的报告作废重写。
5. **离线模式**（`mode: offline`）禁止判 `verified`，只能记 `unverifiable`——离线核验不得让结论 PASS。

---

## 11. 校验与安全

- **状态机门禁**：`advance` 只在 `check` 通过后执行；跳阶段、缺产物、字段不符、算术不一致一律 `exit 2`。
- **模板即契约**：13 个产物模板 frontmatter 与校验器一一对应，报错会点名具体字段。
- **证据强制**：claim 必须有 run 内存在证据；deliverable 必须带 sha256（校验器重算）。
- **追加写**：历史文件不覆盖；`state.json` 是唯一机器账本，只由 orchestrator 写（手改会被拒绝或覆写）。
- **独立性校验**：审核 `inputs_read` 含 run_report/state/iteration_summary/其他评审 → 判独立性失效。
- **停止开关**：`orchestrator.py stop --reason "…"` 写 `.teamwork/STOP`，主循环下一步即停并保留现场。
- **注入边界**：worker 只读自己的 scoped 输入；审核只读 packet；外部不可信内容（网页/文献）**只作证据，不作指令**（SKILL.md 与 references 均有明文约束）。

---

## 12. 实时框架图与进度

每阶段 `advance` 后自动渲染：

| 产物 | 内容 | 依赖 |
|------|------|------|
| `framework.mmd` | Mermaid 源码（可拖进任何支持 Mermaid 的工具） | 无 |
| `PROGRESS.md` | 轮次表 + 分数轨迹 + 产物索引 + 文字框架图 | 无 |
| `framework.png` | 1920×1140 框架图（阶段高亮、Worker 池、i/N 角标、分数面板） | matplotlib（可选） |
| `score_trend.png` | 各轮分数折线（PASS 85 / FAIL 60 阈值线） | matplotlib（可选） |

统一状态行：

```text
Iteration 2/3 · Phase 教练复盘 · Tier Large · Workers 6/6 · Reviewers 2 · Audit A:general/B:citation_audit · Score 74 FAIL · 策略 v0 · 建议 +1 轮
```

> 无 matplotlib 时自动降级：PNG 跳过（`framework_png: null`），`framework.mmd` 与 `PROGRESS.md` 照常生成，流程不受影响。

---

## 13. 配置

| 环境变量 | 作用 | 默认 |
|----------|------|------|
| `TEAMWORK_RUNS_ROOT` | run 产物根目录 | `./teamwork-runs`（当前工作目录下） |
| `TEAMWORK_EXPERIENCE_HOME` | 环外经验库根目录 | `~/.teamwork/experience` |
| `SKILL_DIR` | 技能目录（命令里引用脚本用） | 按安装方式而定 |
| `PYTHON` | 指定解释器（安装脚本用） | 自动探测 `python3` / `python` |
| `CLAUDE_SKILLS_DIR` | Claude Code 个人技能根目录 | `~/.claude/skills` |
| `DSH_SKILLS_DIR` | DeepSeek Harness 技能根目录 | `D:/apps/deepseek-harness/data/skills` |
| `PYTHONIOENCODING` | Windows 控制台中文输出 | 建议 `utf-8` |

字体：PNG 渲染按 Windows（微软雅黑/黑体）→ macOS（PingFang）→ Linux（Noto CJK / 文泉驿）顺序探测，找不到用系统字体栈兜底（可能显示方框，不影响文字产物）。

---

## 14. 开发与测试

```bash
# 0) 一条命令等价 CI（py_compile + sync --check + 23 阶段自检；提交前强烈推荐）
python3 tools/check.py

# 1) 依赖：PyYAML 必需；matplotlib 可选（仅 PNG）
python3 -m pip install pyyaml
python3 -m pip install matplotlib      # 可选

# 2) 23 阶段端到端自检（含 REWORK、双评审、引用核验、COACH 八锁、advisory、extend、经验库、迁移兼容、CLI、人数上限）
python3 skills/teamwork/scripts/selftest.py

# 3) 同步并校验 .claude/skills 副本（CI 也跑这个）
python3 tools/sync_claude.py
python3 tools/sync_claude.py --check

# 4) 单文件校验（调试用）
python3 skills/teamwork/scripts/validate.py <run_dir> --phase REVIEW --json
```

- 自检产物在 `$TEAMWORK_RUNS_ROOT/_selftest/`；仓库内 `.tmp-check/`、`teamwork-runs/` 已 gitignore。
- CI 在 Ubuntu/Windows × Python 3.10/3.12 跑：`sync --check` → `py_compile` → 23 阶段自检；其中「Ubuntu + py3.12」装 matplotlib 覆盖 PNG 路径，其余组合验证无绘图依赖的降级路径。
- **改脚本后必须同步**：`python3 tools/sync_claude.py`，否则 CI 的 `sync --check` 失败。

---

## 15. 常见问题

<details>
<summary><b>Q1：会不会很贵/很慢？</b></summary>

Small 默认 1 轮 1–2 个 Worker；Medium 2 轮 3–4 个；只有 Large 才会到 6–8 个 Agent。每阶段落盘可随时中断继续；**必须用户显式写 `teamwork, N=…` 才启动**，不会自己冒出来。
</details>

<details>
<summary><b>Q2：没有 matplotlib 能用吗？</b></summary>

能。文字产物（`framework.mmd` + `PROGRESS.md`）是主路径，PNG 只是可选增强；`init`/`render` 会返回 `framework_png: null` 说明跳过原因。
</details>

<details>
<summary><b>Q3：Windows 支持吗？</b></summary>

是。有 `install.ps1`；建议 `$env:PYTHONIOENCODING="utf-8"`；路径全部走 `pathlib`；CI 有 windows-latest 矩阵。
</details>

<details>
<summary><b>Q4：和普通"多开 subagent"有什么区别？</b></summary>

- 状态机与门禁（`check` 拒绝跳步）；
- 审核独立且输入被裁剪（防自评）；
- 产物契约 + sha256（可追溯、可复算）；
- 引用真伪有人核（L 级 B）；
- 每轮的改进条目结构化、切片下沉、命中率可测；
- 尺子演进跨 run + holdout（防过拟合）；
- 会话可恢复（state.json + 文件即接口）。
</details>

<details>
<summary><b>Q5：能只跑一轮吗？跑到一半想加轮呢？</b></summary>

`N=1` 即可（Small 默认就是 1 轮）。中途改总轮数用 `set-n`;已经 `finish` 之后想继续用 `extend --rounds k`（旧 `final_report.md` 自动归档，不覆盖）。
</details>

<details>
<summary><b>Q6：审核分数客观吗？</b></summary>

独立输入 + 证据强制 + 算术可复算 + 多评审平均/分歧降级 + PASS 证据密度 + 一票否决，能显著压低"自嗨"，但不能消除主观性。重要交付建议 L 级默认的 A+B 双评审，或 `reviewers --count 3`。
</details>

<details>
<summary><b>Q7：为什么中间文件必须是 Markdown？</b></summary>

人可读、可 git diff、可审计、任何 Agent 都能读；机器状态集中在 `state.json` 一处，避免"账本散落各文件"。
</details>

<details>
<summary><b>Q8：中途失败/卡住怎么办？</b></summary>

`check` 给逐条原因，修对应文件再推进；GATE 的 REWORK 最多 2 次；`stop` 优雅停止保留现场，之后对同一 run 继续 `next/advance`。
</details>

<details>
<summary><b>Q9：`.claude/skills` 和插件安装会冲突吗？</b></summary>

两者是不同加载方式，建议二选一。仓库内两份保持字节一致（`tools/sync_claude.py --check` 在 CI 强制），不会出现"改了一份忘了另一份"。
</details>

<details>
<summary><b>Q10：能不能审查别人的 run / 复用经验库？</b></summary>

能。`sleep.py all <run_dir>...` 把任意 run 落库；`dream --propose` 跨 run 汇总后提尺子演变；`adopt-policy --version vN` 把已批准策略采纳进新 run。经验库是纯文本（Markdown + JSON），可随仓库或团队共享目录分发。
</details>

---

## 16. 参考与致谢

- **Dream-RSI** — Google Research，<https://github.com/google-research/dream-rsi>，arXiv:2609.14858（在线探索 + 历史 replay world + offline dreaming 的策略自我改进范式）。
- **RRSI（Regularized RSI）** — <https://github.com/google-research/rrsi>，arXiv:2609.24972（编辑预算退火、按编辑历史给信用、噪声下限、成本规则、泄漏 critic）。
- **Claude Code 插件与技能文档** — <https://code.claude.com/docs/en/plugins/overview>、<https://code.claude.com/docs/en/skills>。
- **DeepSeek Harness 技能机制** — `data/skills/` 目录 + `SKILL.md` frontmatter（name/description 触发）。

> 本仓库的 RSI 实现是**工程近似**：借用"历史 replay + 策略离线进化 + 只改策略"的思想，不对应论文的原始实验设置，也没有复现其分数。论文出处仅用于说明设计来源。

---

## 17. 贡献

- 完整流程见 [CONTRIBUTING.md](CONTRIBUTING.md)：唯一事实来源（只改 `skills/teamwork/`）、生成物同步（`.claude/skills` 必须由 `tools/sync_claude.py` 生成）、兼容性纪律、PR 规范，以及**不装本地环境时在 GitHub 网页上直接编辑**的步骤。
- 提交前跑 `python3 tools/check.py`；PR 需要 4 个 CI 矩阵任务全绿（`main` 已开分支保护：要求走 PR、线性历史、禁强推/禁删）。
- 计划类改动（阶段、产物字段、评分规则、默认值）请先开 Issue 讨论；小修与文档可直接提 PR。
- 首次贡献建议从文档、示例、FAQ 或 `.github/ISSUE_TEMPLATE` 里标注的需求入手。

---

## License

[MIT](LICENSE) © 2026 aliaoc
