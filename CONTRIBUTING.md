# 贡献指南（Contributing）

感谢愿意一起改进 **teamwork**！这个仓库的定位是「可被审阅、可被复现」的多子 Agent 迭代协作插件，
所以对改动的要求比普通文档仓库更严格一点。请先花 3 分钟读完下面的硬规则，再动手。

---

## 0. 三条硬规则（最容易踩坑）

1. **唯一事实来源是 `skills/teamwork/`**
   脚本、references、模板都在这里改。`.claude/skills/teamwork/` 只是给 Claude Code 用的**生成物**，
   由 `tools/sync_claude.py` 复制而来，**禁止手改**；改了源之后必须跑同步，否则 CI 必挂。

2. **流程写在代码里，不是写在提示词里**
   阶段顺序、产物字段、评分合成、评审隔离、晋级判定都在 `scripts/teamwork_lib.py`。
   只改 `SKILL.md` 文案不会改变行为；行为变化必须同时改代码 + `selftest.py` 的断言 + 文档。

3. **不能提交的内容**
   `teamwork-runs/` 运行产物、`.teamwork/state.json`、密钥/Token、绝对路径、`__pycache__`、
   与本 PR 无关的格式化大改。仓库的 `.gitignore` 已覆盖大部分，请提交前 `git status` 自查。

---

## 1. 环境准备

```bash
# 1) Fork 后在本地克隆自己的 fork（或直接克隆本仓库，如果你是协作者）
git clone https://github.com/<你的用户名>/muti-Agent-teamwork.git
cd muti-Agent-teamwork

# 2) 依赖：Python 3.10+；PyYAML 必需，matplotlib 可选（只影响 PNG）
python3 -m pip install pyyaml
# 想看 PNG 渲染效果时再装：python3 -m pip install matplotlib

# 3) 一键跑本地等效 CI（推荐每次提交前跑）
python3 tools/check.py
```

Windows 用户：把 `python3` 换成 `python`；建议先 `set PYTHONUTF8=1`。

---

## 2. 先讨论，再动手

| 改动类型 | 建议流程 |
|---|---|
| 错别字、链接、文档澄清、小 bug | 直接改 → 提 PR |
| 行为变化 / 新阶段 / 产物字段 / 评分规则 / 默认值 | **先开 Issue** 描述动机与影响，达成一致再写代码 |
| 新运行时适配（如 Cursor、Codex、自研 Agent） | 开 Issue 说明目标平台的工具能力，再按第 4 节改 |

Issue 模板见 `.github/ISSUE_TEMPLATE/`（bug / feature）。

---

## 3. 本地开发循环

```bash
# 修改后逐项验证（tools/check.py 会按顺序跑下面三步）
python3 -m py_compile skills/teamwork/scripts/*.py
python3 tools/sync_claude.py --check
python3 skills/teamwork/scripts/selftest.py
```

说明：

- `selftest.py` 会造一个两轮 run（含 REWORK 打回、双/多评审、Worker 复用、人数上限、命令格式等 13 个阶段）。
  它默认写 `$TEAMWORK_RUNS_ROOT/_selftest/`，不污染仓库。
- `sync_claude.py` 只比较 `skills/teamwork` 与 `.claude/skills/teamwork` 的字节一致性；
  改了源没同步 → `--check` exit 2。
- 验证 PNG 路径需要 matplotlib；没有 matplotlib 时自检会自动跳过 PNG 断言（CI 覆盖两种路径）。

---

## 4. 改哪里：场景 → 文件对照

| 想改什么 | 主要文件 | 必须同步 |
|---|---|---|
| 状态机 / 阶段顺序 / 新校验规则 | `scripts/teamwork_lib.py`（`PHASES`、`validate_*`、`advance_run`、`build_next`） | `scripts/orchestrator.py`、`selftest.py` 断言、`references/protocol.md` |
| 评分 rubric / 阈值 / 评审合并 | `RUBRIC_V0`、`compute_merged_review`、`DREAM` 校验 | `references/review-rubric.md`、selftest 的分数用例 |
| 产物字段 / 目录结构 | `run_paths`、各 `validate_*` | `references/artifacts.md`、`assets/templates/*` |
| 模板文案 | `assets/templates/*.md` | `references/artifacts.md` 字段表 |
| 文字/PNG 渲染 | `render_text.py`、`render_diagram.py` | `references/diagrams.md` |
| 新运行时适配 | `SKILL.md` 的「跨 Agent 运行时」表 + 启动命令 | README「快速开始」、`docs/INSTALL-*` |
| Claude Code 集成 | `.claude-plugin/`、`commands/`、`install/` | `tools/sync_claude.py`、README |
| 文档 / 命令说明 | `README.md`、`docs/`、`examples/` | 行为变化时同步 `docs/COMMANDS.md` |

**命名与路径约定**：新增产物文件要同时更新 `run_paths()`、`TEMPLATES`、`references/artifacts.md` 和
selftest（至少断言文件存在 + 字段合法）。

---

## 5. 兼容性与回归纪律

- **产物字段只增不删**；破坏性改动请升级 `SCHEMA_VERSION` 并在 `validate_*` 里做分支兼容。
- 修改 `validate_*` / `advance_run` 必须补一条 selftest 断言（成功与拒绝各一条更佳）。
- 改动后旧 run 仍应能 `python3 skills/teamwork/scripts/orchestrator.py check <旧 run>`；
  仓库自带的完成态 run 是回归样本。
- 改评分阈值/权重时，同步 `references/review-rubric.md`、README 第 9/10 节和 FAQ，避免文档自相矛盾。
- 新增外部依赖 = 提高安装门槛，必须先在 Issue 里讨论；matplotlib 就属于「可选依赖」的边界。

---

## 6. 分支与提交信息

```bash
git checkout -b feat/描述        # 或 fix/…、docs/…、refactor/…、test/…、chore/…
git commit -m "feat: 一句话说明改了什么"
git push -u origin feat/描述
```

- 采用 Conventional Commits 前缀：`feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`。
- 一个 PR 只做一类改动；大改请拆成可独立审阅的多个 PR。
- 提交信息说清 **动机**，比罗列文件更有用。

---

## 7. Pull Request 检查清单

PR 模板会带同样的清单（`.github/pull_request_template.md`）：

- [ ] 只改了 `skills/teamwork/`（以及必要的 README/docs），并已 `python3 tools/sync_claude.py`
- [ ] `python3 tools/check.py` 通过（或说明未跑的原因）
- [ ] 行为变化已补 selftest 断言；产物契约变化已在描述里说明兼容性
- [ ] 文档已同步（README / references / docs）
- [ ] 没有提交运行产物、密钥、临时文件

CI 会跑 4 个矩阵任务（Ubuntu/Windows × Py3.10/3.12），任何一项红都会被要求修。

---

## 8. CI 与分支保护

- 工作流：`.github/workflows/selftest.yml`，由 `push` 到 `main` 和 `pull_request` 触发。
- 四个检查名：
  `selftest (ubuntu-latest, py3.10)`、`selftest (ubuntu-latest, py3.12)`、
  `selftest (windows-latest, py3.10)`、`selftest (windows-latest, py3.12)`。
- `main` 已配置规则集：禁止强推、禁止删除分支；PR 合并需要上述检查通过。
  维护者可以直接推送（规则集留了管理员旁路），其他贡献者请走 PR。
- 来自 fork 的首次 PR 需要维护者点一次「Approve and run workflows」。

---

## 9. 在 GitHub 网页上直接编辑（不装本地环境）

**有写权限的协作者**：

1. 打开目标文件 → 右上角铅笔图标 `Edit`；
2. 改完点 `Commit changes…` → 选择 **Create a new branch for this commit** → 填分支名；
3. 直接发起 Pull Request（页面会提示 `Propose changes`）；
4. 在 PR 里等 CI；CI 只读依赖，不需要额外权限。

**没有写权限的外部贡献者**：

1. 仓库页右上角 `Fork` → 在你的 fork 里用同样的铅笔编辑；
2. 提交时选 `Create a new branch`（在 fork 内）；
3. 回到上游仓库 → `Contribute` → `Open pull request`。

**多文件/更像 IDE 的方式**：

- 在仓库任意页面按 `.`（或把 URL 里的 `.com` 换成 `.dev`）→ 打开 **github.dev** 网页版 VS Code，
  可以多文件编辑、搜索、diff，提交时同样选择分支 + PR；
- `Code ▾ → Codespaces → Create codespace` 可获得带终端的完整环境（能跑 `tools/check.py`）。

**网页编辑的边界**：浏览器里不能跑本地测试（除非开 Codespaces），所以行为类改动仍建议本地或 Codespaces 验证；
合并冲突可以在网页 PR 里解决，但复杂冲突（如二进制/大改）建议回本地。

---

## 10. 发布流程（维护者）

1. 更新 `CHANGELOG.md`（Unreleased → 版本号）与 `.claude-plugin/plugin.json` 的 `version`；
2. `python3 tools/check.py` 全绿 + CI 绿；
3. `git tag vX.Y.Z && git push origin vX.Y.Z`；
4. 在 GitHub Releases 里粘贴 CHANGELOG 段落；
5. 需要时同步 DSH 安装目录：`cp -R skills/teamwork "D:/apps/deepseek-harness/data/skills/teamwork"`。

---

## 11. 许可

仓库采用 MIT 许可证（见 `LICENSE`）。提交 PR 即表示你同意以 MIT 协议发布你的贡献。
