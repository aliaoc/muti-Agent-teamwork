# 在 Claude Code 中使用 teamwork

Claude Code 有两种加载方式，任选其一（不要同时装，避免同一技能出现两份）：

| 方式 | 适合 | 技能调用 | 是否带 `/teamwork:run` |
|------|------|----------|------------------------|
| **插件**（本仓库 `.claude-plugin/`） | 想用命令、方便升级 | `/teamwork:run` | 是 |
| **项目技能**（仓库内 `.claude/skills/teamwork`） | 直接克隆/拷贝进项目 | 自然语言"用 teamwork 跑……" | 否 |
| **个人技能**（安装脚本） | 所有项目共用 | 自然语言 / 手动命令 | 否 |

---

## 方式 A：作为插件安装

本仓库根目录带 `.claude-plugin/plugin.json`（插件清单）与 `.claude-plugin/marketplace.json`（单插件市场清单）。

```text
# 1) 在 Claude Code 会话里添加市场（仓库托管后可用 owner/repo 简写）
/plugin marketplace add aliaoc/muti-Agent-teamwork

# 2) 安装插件
/plugin install teamwork@muti-agent-teamwork

# 3) 新开会话（或 /reload-plugins）
/teamwork:run N=3 帮我调研并写一份技术方案
```

本地调试（未推送前）：

```bash
claude plugin validate ./muti-Agent-teamwork
claude --plugin-dir ./muti-Agent-teamwork
```

插件目录约定（Claude Code 自动发现，不需要在 plugin.json 里逐项声明）：

```
.claude-plugin/plugin.json   # manifest：name/version/description/author/license/keywords
skills/teamwork/SKILL.md     # 技能 → 会话里显示为 /teamwork:teamwork（也可自然语言触发）
commands/run.md              # 命令 → /teamwork:run（推荐入口，带参数说明）
```

> 说明：`skills/teamwork` 保留技能自身名称，因此在插件里它是 `/teamwork:teamwork`；日常建议用 `commands/run.md` 的 `/teamwork:run`。

## 方式 B：作为项目技能（最简单）

```bash
git clone https://github.com/aliaoc/muti-Agent-teamwork.git
cp -R muti-Agent-teamwork/.claude/skills/teamwork <你的项目>/.claude/skills/teamwork
```

Claude Code 在该项目内自动发现 `.claude/skills/teamwork/SKILL.md`。直接说：

```text
用 teamwork 跑这个任务：N=2，读 docs/api.md，写一份接口变更说明到 docs/
```

Claude 会加载技能并按其主循环执行。

> 注意：`.claude/skills/teamwork` 是 `skills/teamwork` 的同步副本。改源后请运行
> `python3 tools/sync_claude.py` 重新同步；CI 用 `--check` 强制一致。

## 方式 C：安装为个人技能

```bash
# macOS / Linux / WSL / Git Bash
./install/install.sh --claude

# Windows
.\install\install.ps1 -Mode claude
```

默认安装到 `~/.claude/skills/teamwork`（可用 `CLAUDE_SKILLS_DIR` 覆盖）。

---

## 运行时差异：子 Agent 怎么"复用"

Claude Code 的 `Task` 子 Agent 是**一次性**的（会话不持久）。teamwork 的"跨轮复用"在 Claude Code 中表现为：

1. **逻辑 id 不变**：第 2 轮仍叫 `w01`、`w02`……（state/dispatch/产物目录一致）；
2. **文件交接**：把该 worker 上一轮的 `result.md` 与 artifacts 作为第 2 轮 Task 的输入；
3. 审核 Agent 每一轮都必须是**全新** Task（独立性要求）；
4. Final Agent 仅 Large 级需要，由主 Agent 新开 Task；S/M 级由主 Agent 自己汇总。

DeepSeek Harness 的 `spawn_teammate/send_message` 可以保持物理 Agent 跨轮存活，但对状态机而言两者等价——都只认逻辑 id 与产物。

---

## 依赖与验证

```bash
python3 -m pip install pyyaml       # 必需
python3 -m pip install matplotlib   # 可选：PNG 框架图

# 自检（23 阶段）
python3 skills/teamwork/scripts/selftest.py

# 在一处验证技能可被正确执行：让 Claude 跑一个 1 轮小任务，观察 run 目录与状态行
/teamwork:run N=1 把本仓库 README 的“核心特性”表翻译成英文，写入 docs/FEATURES.en.md
```

## 常见问题

| 现象 | 处理 |
|------|------|
| `/teamwork:run` 未出现 | 插件未安装或未 reload：`/plugin` 查看已安装列表，或 `/reload-plugins` |
| 技能未被自动触发 | 对话里直接点名"用 teamwork 技能跑……"；或检查 `.claude/skills/teamwork/SKILL.md` 是否就位 |
| Python 不是 3.10+ | `python3 --version`；macOS 自带 python3 可能过旧，用 `brew install python` |
| 缺少 PyYAML | `python3 -m pip install pyyaml` |
| 运行产物找不到 | 默认在当前项目 `./teamwork-runs/`；设置 `TEAMWORK_RUNS_ROOT` 可改 |
| Windows 中文乱码 | `$env:PYTHONIOENCODING="utf-8"` |
