# 命令参考（v2.0）

所有命令都通过同一个入口：

```bash
python3 "$SKILL_DIR/scripts/orchestrator.py" <子命令> [run_dir] [选项]
```

- `$SKILL_DIR` = 技能目录（Claude Code 插件为 `<CLAUDE_PLUGIN_ROOT>/skills/teamwork`；仓库内为 `./skills/teamwork`）。
- `run_dir` 可省略：默认取 `--root`（或 `$TEAMWORK_RUNS_ROOT`，或 `./teamwork-runs`）下**最新的 run**。
- `--json`：输出机器可读 JSON（适合脚本/CI）。
- 校验失败/参数错误：**exit 2**，并打印逐条原因；成功 exit 0。

> Windows 用 `python`；控制台中文乱码先 `PYTHONIOENCODING=utf-8`。

---

## 1. init —— 创建 run

```bash
python3 "$SKILL_DIR/scripts/orchestrator.py" init \
    --cmd "teamwork, N=2 整理一份可行方案并给出证据" \
    [--task "自定义任务描述"] [--root ./teamwork-runs] [--json]
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--cmd` | 是 | 启动命令，必须匹配 `teamwork, N=<数字\|?> <任务>`（也接受中文逗号 `，`） |
| `--task` | 否 | 任务描述；缺省取命令之后的部分 |
| `--root` | 否 | run 根目录；默认 `$TEAMWORK_RUNS_ROOT` 或 `./teamwork-runs` |
| `--json` | 否 | 输出 `{run_dir, ...}` |

`init` 创建目录骨架、写 `00_intake/task.md`、`review_policy/v0.md`、`.teamwork/state.json`，并尝试渲染初始框架图（PNG 可选）。

---

## 2. next —— 问"下一步做什么"

```bash
python3 "$SKILL_DIR/scripts/orchestrator.py" next <run_dir> [--json]
```

返回当前阶段**唯一合法**的下一步：要读什么、要写哪个文件、模板路径、子 Agent 角色、`agent_name`（带 run 指纹）。
`--json` 字段：`phase / label / role / instruction / outputs / templates / subagents / worker_range`。

---

## 3. status —— 查看进度

```bash
python3 "$SKILL_DIR/scripts/orchestrator.py" status <run_dir> [--json]
```

```text
Iteration 2/3 · Phase 教练复盘 · Tier Large · Workers 6/6 · Reviewers 2 · Audit A:general/B:citation_audit · Score 74 FAIL · 策略 v0 · 建议 +1 轮
```

JSON 包含 `run_id / phase / phase_label / tier / n / current_iter / scores / policy_version / workers / reviewers / roles / citation_audit / status_line / advisory`。

---

## 4. check —— 校验产物（门禁）

```bash
python3 "$SKILL_DIR/scripts/orchestrator.py" check <run_dir> [--phase REVIEW] [--json]
```

- 默认校验 run 当前阶段的全部必需产物；
- `--phase` 仅用于调试；
- 失败 exit 2，逐条列出：缺字段、路径不存在、sha256 不符、权重/算术不一致、人数超限、审核读了禁止文件、教练条目越权、切片缺失等。

---

## 5. advance —— 推进阶段

```bash
python3 "$SKILL_DIR/scripts/orchestrator.py" advance <run_dir> [--json]
```

先隐式 `check`，通过后推进并落库（写 state、渲染框架图）。**不要绕过 advance 手改 state.json。**

---

## 6. make-packet —— 生成审核证据包（FINAL 阶段）

```bash
python3 "$SKILL_DIR/scripts/orchestrator.py" make-packet <run_dir>
```

在 `final_result.md` + `run_report.md` 写完后执行；生成 `iterations/iter-NN/review_packet.md`（artifacts + sha256 + `citations[]` + `roles` + `forbidden`）。
顺序：**final_result/run_report → make-packet → check → advance**。

---

## 7. merge-review —— 合成多评审（调试/恢复）

```bash
python3 "$SKILL_DIR/scripts/orchestrator.py" merge-review <run_dir>
```

REVIEW 阶段通常由 `advance` 自动合成 `review_scores.md`；本命令用于手工重算（补/改评审报告后）。

---

## 8. render —— 重渲染框架图/看板

```bash
python3 "$SKILL_DIR/scripts/orchestrator.py" render <run_dir> [--trend]
```

产物：`framework.mmd`、`PROGRESS.md`（总是），`framework.png`（需 matplotlib）；`--trend` 额外生成 `score_trend.png`。

---

## 9. finish —— 收尾（DONE 阶段）

```bash
python3 "$SKILL_DIR/scripts/orchestrator.py" finish <run_dir> [--json]
```

要求 `final_report.md` 校验通过（含 `advisory_response: accept|decline`）；置 `finished=true`，渲染最终框架图与分数轨迹图，并把 run 落库到经验库。

---

## 10. set-n / set-tier —— 中途调参

```bash
python3 "$SKILL_DIR/scripts/orchestrator.py" set-n <run_dir> --n 4
python3 "$SKILL_DIR/scripts/orchestrator.py" set-tier <run_dir> --tier Large --reason "任务扩展到多系统"
```

- `set-n` 下一轮生效；若当前已是最后一轮会自动延长（或改用 `extend`）。
- `set-tier` 仅限 INIT / CLASSIFY / PLAN；影响人数上限与默认 N，写入 history。

---

## 11. reviewers / dual-review —— 评审人数

```bash
# 推荐：1–26 位（k>1 需向用户说明成本并确认）
python3 "$SKILL_DIR/scripts/orchestrator.py" reviewers <run_dir> --count 3

# 兼容入口（1/2 位）
python3 "$SKILL_DIR/scripts/orchestrator.py" dual-review <run_dir> --on
python3 "$SKILL_DIR/scripts/orchestrator.py" dual-review <run_dir> --off
```

L 级 + `citation_audit != off` 时脚本**自动**设 2 位评审（`roles = {A: general, B: citation_audit}`）；用户显式 `reviewers --count` 过则尊重用户。
多评审各写 `review_report_A.md`、`review_report_B.md`…；`advance` 合成 `review_scores.md`（平均分、任一 FAIL 即 FAIL、维度分歧 >10 强制降级 REVISE）。

---

## 12. citation-audit —— 开关引用核验

```bash
python3 "$SKILL_DIR/scripts/orchestrator.py" citation-audit <run_dir> --off --reason "内部资料无可核来源"
python3 "$SKILL_DIR/scripts/orchestrator.py" citation-audit <run_dir> --on
```

默认 `auto`（L 级开）。关闭会写进 history，需给理由。

---

## 13. coach-show —— 查看教练复盘

```bash
python3 "$SKILL_DIR/scripts/orchestrator.py" coach-show <run_dir> [--json]
```

输出每轮 `items`、覆盖错误数、`hit_rate`、`stuck_classes`、`escalations`、`ineffective` 标记。

---

## 14. extend —— DONE 后追加轮次（续跑）

```bash
python3 "$SKILL_DIR/scripts/orchestrator.py" extend <run_dir> --rounds 1 [--reason "…"] [--force]
```

- 只允许在 DONE 之后用；`--rounds` 取 1–3（受上限 `min(3, 10-n)` 约束）；
- 旧 `final_report.md` 归档为 `final_report.iter-NN.md`（append-only；`--force` 才允许覆盖已有归档）；
- 追加后 `n` 变大，流程回到 PLAN 继续。

---

## 15. dream —— 环外尺子演进（不写 run 目录）

```bash
# 生成提案（读经验库，跨 run 的 holdout 校验；不足样本会直接拒绝）
python3 "$SKILL_DIR/scripts/orchestrator.py" dream --propose

# 人工批准 / 回滚
python3 "$SKILL_DIR/scripts/orchestrator.py" dream --approve v1
python3 "$SKILL_DIR/scripts/orchestrator.py" dream --rollback        # 回上一版
python3 "$SKILL_DIR/scripts/orchestrator.py" dream --rollback v1     # 回指定版本
```

`--offline` 只是可读标注（默认即离线）。

---

## 16. adopt-policy —— 把已批准策略采纳进 run

```bash
python3 "$SKILL_DIR/scripts/orchestrator.py" adopt-policy <run_dir> --version v1
```

把经验库 `policies/evaluator/v1.md` 写入该 run 的 `review_policy/`，后续轮次按新权重评分（评审报告必须跟随新权重，否则 C1 报错）。

---

## 17. stop —— 优雅停止

```bash
python3 "$SKILL_DIR/scripts/orchestrator.py" stop <run_dir> --reason "用户要求暂停"
```

写 `.teamwork/STOP`；主循环下一步检测到即停止并保留现场。之后可继续对同一 run 执行 `next/advance`。

---

## 18. 环外睡眠任务（sleep.py）

```bash
python3 "$SKILL_DIR/scripts/sleep.py" record <run_dir>...
python3 "$SKILL_DIR/scripts/sleep.py" distill --min-support 2
python3 "$SKILL_DIR/scripts/sleep.py" retire
python3 "$SKILL_DIR/scripts/sleep.py" metrics
python3 "$SKILL_DIR/scripts/sleep.py" calibrate
python3 "$SKILL_DIR/scripts/sleep.py" all <run_dir>...
```

经验库默认 `~/.teamwork/experience`，用 `TEAMWORK_EXPERIENCE_HOME` 覆盖。

---

## 19. 退出码与脚本化

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 2 | 校验失败 / 参数或命令格式错误（可直接作为 CI 门禁） |
| 1 | 未捕获异常（bug；请附 run 目录与命令反馈） |

```bash
set -e
python3 "$SKILL_DIR/scripts/orchestrator.py" check "$RUN_DIR" --json
```

---

## 20. 常用环境变量

| 变量 | 说明 |
|------|------|
| `SKILL_DIR` | 技能目录（示例命令用） |
| `TEAMWORK_RUNS_ROOT` | 默认 run 根目录 |
| `TEAMWORK_EXPERIENCE_HOME` | 环外经验库根目录（默认 `~/.teamwork/experience`） |
| `PYTHONIOENCODING=utf-8` | Windows 控制台中文输出 |
| `PYTHON` | 安装脚本选择解释器 |

阶段级细节见 [`references/protocol.md`](../skills/teamwork/references/protocol.md)、[`references/artifacts.md`](../skills/teamwork/references/artifacts.md)、[`references/review-rubric.md`](../skills/teamwork/references/review-rubric.md)。
