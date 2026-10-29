# 安装到 DeepSeek Harness（DSH）

teamwork 是标准 Agent Skill（`SKILL.md` + `scripts/` + `references/` + `assets/`），DSH 通过技能目录发现并加载。

## 1. 最短路径

```bash
# 仓库根目录执行
./install/install.sh --dsh
```

默认安装到 `D:/apps/deepseek-harness/data/skills/teamwork`；可用环境变量覆盖：

```bash
DSH_SKILLS_DIR=/your/dsh/data/skills ./install/install.sh --dsh
```

Windows PowerShell：

```powershell
.\install\install.ps1 -Mode dsh
# 或 .\install\install.ps1 -Mode dsh -Dest "D:\apps\deepseek-harness\data\skills"
```

## 2. 手工安装（等价）

```bash
cp -R skills/teamwork "D:/apps/deepseek-harness/data/skills/teamwork"
# 删除可能存在的缓存
find "D:/apps/deepseek-harness/data/skills/teamwork" -name __pycache__ -type d -prune -exec rm -rf {} +
```

安装后确认技能目录存在 `SKILL.md`，且其 frontmatter 为：

```yaml
---
name: teamwork
description: 用户要求用 teamwork 跑任务时使用（三种写法等价）：…
---
```

## 3. 验证

1. 新开一个 DSH 会话；
2. 会话技能清单里应出现 `teamwork`（若没出现，检查目录层级是否多套了一层：必须是 `.../skills/teamwork/SKILL.md`）；
3. 输入：

   ```text
   teamwork, N=1 把 README 里“快速开始”一节翻译成英文，给出文件路径
   ```

4. 预期：主 Agent 先判级（Small）、初始化 run 目录，然后按状态机推进；每阶段输出状态行，如
   `Iteration 1/1 · Phase 分级 · Tier Small · Workers 2/2 · Reviewers 1 · Score - · 策略 v0`。

## 4. 依赖

| 依赖 | 必需 | 说明 |
|------|------|------|
| Python 3.10+ | 是 | `teamwork_lib.py` 使用 `from __future__ import annotations`、match 语法等 |
| PyYAML | 是 | 解析/生成 frontmatter；缺了会直接报错 |
| matplotlib | 否 | 仅 PNG 框架图/趋势图；缺省自动降级为 Mermaid + PROGRESS.md |

```bash
python3 -m pip install pyyaml
# 可选：python3 -m pip install matplotlib
```

## 5. 运行位置与权限

- 默认 run 产物在**当前工作目录**的 `./teamwork-runs/`；可在 `init` 里用 `--root` 或环境变量 `TEAMWORK_RUNS_ROOT` 指定。
- worker 需要写入 run 目录；审核 Agent 只需要读 packet 与 artifacts。
- 若宿主对子 Agent 写文件有限制，请保证 run 目录在可写范围内（通常就是会话工作区）。

## 6. 升级 / 卸载

```bash
# 升级（覆盖安装，自动备份旧版）
./install/install.sh --dsh --force

# 卸载
rm -rf "D:/apps/deepseek-harness/data/skills/teamwork"
```

升级后建议跑一次自检：

```bash
TEAMWORK_RUNS_ROOT=/tmp/tw-selftest python3 "D:/apps/deepseek-harness/data/skills/teamwork/scripts/selftest.py"
rm -rf /tmp/tw-selftest
```

## 7. 疑难

| 现象 | 处理 |
|------|------|
| 技能清单里没有 `teamwork` | 检查路径是否 `.../skills/teamwork/SKILL.md`；重启/新开会话；确认 frontmatter 未被破坏 |
| 启动命令报"格式错误" | 必须 `teamwork, N=3 …`（英文或中文逗号均可）；`N=?` 合法 |
| 中文乱码 | 设置 `PYTHONIOENCODING=utf-8` |
| `check` 总是不通过 | 按报错逐条修；`--json` 便于定位；也可 `validate.py <run> --phase <阶段>` 单独校验 |
| PNG 方框 | 系统缺中文字体：安装 Noto Sans CJK 或微软雅黑；文字产物不受影响 |
