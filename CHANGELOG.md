# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- `CONTRIBUTING.md`：贡献指南（唯一事实来源、同步规则、兼容性纪律、网页编辑与 PR 流程）。
- `.github/pull_request_template.md`、`.github/ISSUE_TEMPLATE/`（bug / feature / config）、`.github/CODEOWNERS`。
- `tools/check.py`：本地一条命令跑 py_compile + sync --check + 13 阶段 selftest。

## [1.0.1] - 2026-10-29

### Fixed
- CI：未安装 matplotlib 时 `selftest.py` 误报 PNG 断言失败；改为按可用性跳过，并新增 `TEAMWORK_NO_MPL=1` 强制模拟降级路径。
- Windows 控制台/CI（cp1252）下脚本输出中文抛 `UnicodeEncodeError`；脚本入口与 CI 统一 UTF-8。

### Added
- CI 矩阵中「Ubuntu + py3.12」安装 matplotlib，覆盖 PNG 渲染路径；其余组合验证无绘图依赖的降级路径。

## [1.0.0] - 2026-10-29

### Added
- `teamwork` 多子 Agent 迭代协作技能：Small/Medium/Large 分级、规划—派发—汇总—独立审核—复盘迭代（N 轮）。
- 状态机/校验/评分合成/评审隔离/Dream-RSI 式策略复盘写死于 `scripts/teamwork_lib.py`。
- 产物契约：全 Markdown + YAML frontmatter，内部账本 `.teamwork/state.json`；实时框架图（PNG + Mermaid/文本降级）。
- Claude Code 插件形态（`.claude-plugin/`、`commands/run.md`、`.claude/skills/` 同步副本）、DSH 与纯 CLI 用法。
- 13 阶段端到端自检与 GitHub Actions 多 OS × 多 Python 版本 CI。
