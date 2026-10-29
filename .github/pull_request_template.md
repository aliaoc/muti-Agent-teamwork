## 这个 PR 做了什么

<!-- 一句话说明动机与结果；关联 Issue 请写 Closes #123 -->

Closes #

## 改动类型

- [ ] feat：新功能 / 新能力
- [ ] fix：修复 bug
- [ ] docs：文档
- [ ] refactor：重构（行为不变）
- [ ] test：测试
- [ ] chore：CI / 构建 / 杂项

## 改动范围

- [ ] `skills/teamwork/`（唯一事实来源）
- [ ] `docs/` / `README.md`
- [ ] Claude Code 集成（`.claude-plugin/`、`commands/`、`install/`）
- [ ] CI / 工具（`.github/`、`tools/`）

## 验证（必填）

- [ ] 已运行 `python3 tools/check.py`（或说明仅跑了哪些项）
- [ ] 已运行 `python3 tools/sync_claude.py` 同步 `.claude/skills/teamwork`
- [ ] 行为变化已补 `selftest.py` 断言
- [ ] 涉及产物契约：已说明兼容性（旧 run 是否仍能 `check` 通过；是否需要升 `SCHEMA_VERSION`）
- [ ] 文档已同步（README / references / docs / CHANGELOG）

## 影响与风险

<!-- 新增依赖？评分规则变化？默认行为变化？性能/成本影响？ -->

## 截图 / 输出（可选）

<!-- 涉及框架图、评分轨迹、CLI 输出时贴图或贴文本 -->
