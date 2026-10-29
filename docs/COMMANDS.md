# 命令参考

所有命令都通过同一个入口：

```bash
python3 skills/teamwork/scripts/orchestrator.py <子命令> [run_dir] [选项]
```

- `run_dir` 可省略：默认取 `--root`（或 `$TEAMWORK_RUNS_ROOT`，或 `./teamwork-runs`）下**最新的 run**。
- `--json`：输出机器可读 JSON（适合脚本/CI）。
- 所有校验失败/参数错误：**exit 2**，并打印逐条原因；成功 exit 0。

> Windows 使用 `python`；控制台中文乱码时先设置 `PYTHONIOENCODING=utf-8`。

---

## 1. init —— 创建 run

```bash
python3 skills/teamwork/scripts/orchestrator.py init \
    --cmd "teamwork, N=2 整理一份可行方案并给出证据" \
    [--task "自定义任务描述"] [--root ./teamwork-runs] [--json]
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--cmd` | 是 | 启动命令，必须匹配 `teamwork, N=<数字\|?> <任务>`（也接受中文逗号 `，`、`N=?`） |
| `--task` | 否 | 任务描述；缺省取命令之后的部分 |
| `--root` | 否 | run 根目录；默认 `$TEAMWORK_RUNS_ROOT` 或 `./teamwork-runs` |
| `--json` | 否 | 输出 `{run_dir, ...}` |

`init` 会创建目录骨架、写 `00_intake/task.md`、`review_policy/v0.md`、`.teamwork/state.json`，并尝试渲染初始框架图（PNG 可选）。

---

## 2. next —— 问"下一步做什么"

```bash
python3 skills/teamwork/scripts/orchestrator.py next <run_dir> [--json]
```

返回当前阶段**唯一合法**的下一步：要读什么、要写哪个文件、模板路径、子 Agent 角色与 prompt 锚点。`--json` 输出结构化字段（`phase/label/role/instructions/outputs/templates/subagents`）。

---

## 3. status —— 查看进度

```bash
python3 skills/teamwork/scripts/orchestrator.py status <run_dir> [--json]
```

人读格式：

```text
Iteration 2/3 · Phase 审核 · Tier Large · Reviewers 1 · Score 74 FAIL · 策略 v0 · 已完成
```

JSON 包含：`run_id/phase/phase_label/tier/n/current_iter/scores/policy_version/workers/reviewers`。

---

## 4. check —— 校验产物（门禁）

```bash
python3 skills/teamwork/scripts/orchestrator.py check <run_dir> [--phase REVIEW] [--json]
```

- 默认校验 run 当前阶段的全部必需产物；
- `--phase` 仅用于调试（按指定阶段的规则校验）；
- 失败 exit 2，并逐条列出：缺字段、路径不存在、sha256 不符、权重/算术不一致、人数超限、审核读了禁止文件等。

---

## 5. advance —— 推进阶段

```bash
python3 skills/teamwork/scripts/orchestrator.py advance <run_dir> [--json]
```

先隐式执行 `check`，通过后推进并落库（写 state、必要时渲染框架图）。**不要绕过 advance 手工改 state.json。**

---

## 6. make-packet —— 生成审核证据包（FINAL 阶段）

```bash
python3 skills/teamwork/scripts/orchestrator.py make-packet <run_dir>
```

在 `final_result.md` + `run_report.md` 写完后执行；生成 `iterations/iter-NN/review_packet.md`（含 artifacts/sha256/forbidden）。注意顺序：**final_result/run_report → make-packet → check → advance**。

---

## 7. merge-review —— 合成多评审（调试/恢复用）

```bash
python3 skills/teamwork/scripts/orchestrator.py merge-review <run_dir>
```

审阅阶段通常由 `advance` 自动合成 `review_scores.md`；本命令用于手工重算（例如补/改评审报告后）。

---

## 8. render —— 重渲染框架图/看板

```bash
python3 skills/teamwork/scripts/orchestrator.py render <run_dir> [--trend]
```

产物：`framework.mmd`、`PROGRESS.md`（总是）、`framework.png`（需 matplotlib）；`--trend` 额外生成 `score_trend.png`。无 matplotlib 时 PNG 跳过并提示。

---

## 9. finish —— 收尾（DONE 阶段）

```bash
python3 skills/teamwork/scripts/orchestrator.py finish <run_dir> [--json]
```

要求 `final_report.md` 校验通过；置 `finished=true`，渲染最终框架图与分数轨迹图。

---

## 10. set-n / set-tier —— 中途调参

```bash
# 修改总轮数：显式值
python3 skills/teamwork/scripts/orchestrator.py set-n <run_dir> --n 4

# 切换等级（必须给理由，写入 state/history）
python3 skills/teamwork/scripts/orchestrator.py set-tier <run_dir> --tier Large --reason "任务扩展到多系统"
```

- `set-n` 在下一轮生效；若当前已是最后一轮会自动延长。
- 等级升降级会影响人数上限与默认 N；超限时后续 dispatch 会被 `check` 拒绝。

---

## 11. dual-review / reviewers —— 评审人数

```bash
# 兼容入口（1/2 位）
python3 skills/teamwork/scripts/orchestrator.py dual-review <run_dir> --on
python3 skills/teamwork/scripts/orchestrator.py dual-review <run_dir> --off

# 推荐入口：1–26 位（k>1 需用户确认成本）
python3 skills/teamwork/scripts/orchestrator.py reviewers <run_dir> --count 3
```

多评审：各写 `review_report_A.md`、`review_report_B.md`…；`advance` 合成 `review_scores.md`（平均分、任一 FAIL 即 FAIL、维度分歧 >10 记录）。

---

## 12. stop —— 优雅停止

```bash
python3 skills/teamwork/scripts/orchestrator.py stop <run_dir> --reason "用户要求暂停"
```

写 `.teamwork/STOP`；主循环下一步检测到即停止并保留现场。之后可继续对同一 run 执行 `next/advance`（如用户明确要继续）。

---

## 13. 退出码与脚本化

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 2 | 校验失败 / 参数或命令格式错误（可直接作为 CI 门禁） |
| 1 | 未捕获异常（bug；请附 run 目录与命令反馈） |

CI 用法示例：

```bash
set -e
python3 skills/teamwork/scripts/orchestrator.py check "$RUN_DIR" --json
```

---

## 14. 常用环境变量

| 变量 | 说明 |
|------|------|
| `TEAMWORK_RUNS_ROOT` | 默认 run 根目录（`init/--root` 未指定时） |
| `PYTHONIOENCODING=utf-8` | Windows 控制台中文输出 |
| `PYTHON` | 安装脚本选择解释器 |

更多阶段级细节见 [`references/protocol.md`](../skills/teamwork/references/protocol.md) 与 [`references/artifacts.md`](../skills/teamwork/references/artifacts.md)。
