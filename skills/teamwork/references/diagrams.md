# 框架图、状态行与进度

## 什么时候渲染

- `init` 建完 run 后自动渲染第一张。
- 每次 `advance` 成功后自动重渲染。
- 手动刷新：`python3 $SKILL_DIR/scripts/orchestrator.py render <run>`。
- `finish` 时额外生成 `score_trend.png`。

## 产物

| 文件 | 内容 |
| --- | --- |
| `framework.png` | 1920×1140 的运行框架图（matplotlib 渲染） |
| `framework.mmd` | 同一框架的 Mermaid 源码（给支持 Mermaid 的工具用；DSH 聊天里不保证渲染） |
| `PROGRESS.md` | 轮次表 + 分数轨迹 + 产物索引，人读 |
| `score_trend.png` | 收尾时的分数轨迹折线图 |

`framework.png` 包含：主 Agent 框、8 个阶段框（蛇形箭头）、当前阶段高亮、Worker 池状态 chip、Artifact Store、右侧 `第 i/N 轮` 角标与分数面板、底部状态行。

## 状态行

脚本 `status` / `next` 返回 `status_line`，格式固定：

```
Iteration i/N · Phase 阶段 · Tier 等级 · Workers k · Score s VERDICT · 策略 vX
```

- `Score` 取最近一轮审核合成总分；尚未审核时显示 `-`。
- 每阶段推进后在聊天里输出这一行，并贴框架图。

## 聊天里怎么展示

```markdown
![teamwork 框架图](<run>/framework.png)
```

- 图片路径用 run 目录绝对路径；路径含空格时用 `<...>` 包住。
- 需要持续看时用 `sidebar_open` 打开 run 目录或 `PROGRESS.md`。
- 聊天渲染不保证 Mermaid，故**不要只贴 Mermaid 源码**；PNG 是主呈现，`.mmd` 只作可移植备份。

## 环境要求

- Python：3.10+（`python3` / Windows `python`）；matplotlib 可选，缺失时只跳过 PNG，文本看板照常生成。
- 渲染前脚本内已 `matplotlib.use("Agg")`，无需图形界面。
- 中文字体：脚本按 Windows（微软雅黑/黑体）→ macOS（PingFang）→ Linux（Noto CJK / 文泉驿）顺序查找；都没有时用系统字体栈兜底。
- 控制台中文：命令前 `set PYTHONIOENCODING=utf-8`。
- 沙箱：run 目录必须位于可写工作区（默认 `./teamwork-runs` 或 `$TEAMWORK_RUNS_ROOT`）。

## PROGRESS.md

由渲染器维护，包含：

1. run 基本信息（run_id、任务、等级、轮数、当前阶段）。
2. 迭代记录表：轮次 / 阶段 / Worker 数 / 总分 / verdict / 策略版本 / 时间。
3. 产物索引：任务、计划、每轮结果、审核、复盘、最终报告。
4. 分数轨迹（与 `score_trend.png` 对应）。

## 降级方案（图渲染失败时）

1. 确认 matplotlib 可用：`python3 -c "import matplotlib; print(matplotlib.__version__)"`（未安装则 `pip install matplotlib`）。
2. 若字体报错：检查 `msyh.ttc`/`simhei.ttf` 是否存在，临时改用 ASCII 图中的文字。
3. 仍失败：在聊天里贴 ASCII 框架：

```text
主 Agent
  ├─ CLASSIFY → PLAN → DISPATCH → WORKERS（w01…wNN）
  └─ FINAL → GATE ──PASS──→ REVIEW → DREAM → 下一轮 PLAN
        └─REWORK（≤2 次）→ WORKERS
```

4. 任何情况下状态行和 `PROGRESS.md` 都要照常更新，保证用户能看到 i/N 进度。
