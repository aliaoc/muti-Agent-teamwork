---
description: 以 teamwork 多子 Agent 流程执行任务（分级 → 规划 → 派发 → 汇总 → 独立审核（含引用核验）→ COACH 改进 → 按 N 轮迭代 → 末轮建议）
argument-hint: N=<数字|?> <任务描述>
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task, TodoWrite
---

# /teamwork:run —— teamwork 快速入口

用户参数：`$ARGUMENTS`（形如 `N=3 帮我写一份……`，`N=?` 表示轮数由主 Agent 按分级自动决定）

## 执行要求（必须遵守）

1. **先加载技能**：读取本仓库 `skills/teamwork/SKILL.md`（插件安装后为 `<CLAUDE_PLUGIN_ROOT>/skills/teamwork/SKILL.md`），按其「主循环」严格执行；不要凭记忆复述流程。
2. **解析命令**：把参数规范成启动命令 `teamwork, N=<数字|?> <任务描述>`；缺省写 `N=?`。
3. **初始化 run**（Windows 用 `python`，其余用 `python3`）：

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT:-.}/skills/teamwork/scripts/orchestrator.py" init \
       --cmd "teamwork, $ARGUMENTS" --json
   ```

   记录返回的 `run_dir`；之后所有相对路径都相对 run 目录。
4. **只通过状态机推进**：每步先 `next` 看指令与模板，产出文件后 `check` 校验，再 `advance` 进入下一阶段。**不要手工跳阶段**；`check` 失败时按报错修文件，不要绕过。
5. **每个阶段推进后**输出状态行与图路径：

   ```text
   Iteration 2/3 · Phase 教练复盘 · Tier Large · Workers 6/6 · Reviewers 2 · Audit A:general/B:citation_audit · Score 74 FAIL · 策略 v0 · 建议 +1 轮
   ```

   并把 `framework.png`（若安装 matplotlib）或 `framework.mmd`、`PROGRESS.md` 路径贴给用户。
6. **子 Agent**：Claude Code 用 `Task` 工具；每个 worker 的 prompt 必须包含任务、写作用域（只写自己的 `wNN_artifacts/`）、交付物格式、`result.md` 模板位置。Claude Code 的 subagent 会话不可跨轮保持，因此「复用」= 沿用 `wNN` 逻辑 id、把上轮产物交给新 Task 子 Agent（详见 `references/protocol.md#worker`）。
7. **审核要独立**：审核 Agent 只读 `review_packet.md` 与其列出的 artifacts，禁读 `run_report.md`、`state.json`、`iteration_summary.md` 和其他评审报告；L 级默认两位评审（A 通用、B 引用核验），B 必须给出 `verified / unverifiable / misattributed / fabricated / stale` 判定与核验方法。
8. **COACH 要可执行**：把评审的 errors 转成 ≤8 条改进条目（`must_fix ≤3`），每条写 `root_cause / action / verification / applies_to`；下轮 `dispatch` 用 `coach_items` 按 `applies_to` 切片下发给对应 worker，不发要写 `coach_deferred`。
9. **末轮播报建议**：`iteration_advisory.md` 由脚本生成，向用户报告分数、距离 PASS 的差距、建议续跑轮数与理由，并按用户选择写 `final_report.advisory_response: accept|decline`（accept 用 `extend --rounds k` 续跑）。
10. **收尾**：审核完成后写 `final_report.md` → `finish` → 向用户报告：分数轨迹（如 72 FAIL → 74 FAIL → 88 PASS）、报告路径、未决事项；不要把过程性草稿当最终交付。

## 注意

- 任务足够简单（单文件、低风险、<30 分钟）时，直接在对话里完成即可，不必启动 teamwork；只有需要多子 Agent 拆分/多轮审核时才使用本命令。
- 所有人数上限按「单个 run」计数：Small 2 / Medium 4 / Large 7（+Final ≤ 8），审核 Agent 1–26 位。
- 运行产物默认写入 `./teamwork-runs/`，可用环境变量 `TEAMWORK_RUNS_ROOT` 改根目录；环外经验库默认 `~/.teamwork/experience`（`TEAMWORK_EXPERIENCE_HOME`）。
