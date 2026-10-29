#!/usr/bin/env bash
# teamwork 安装脚本（macOS / Linux / Git Bash / WSL）
#
#   ./install/install.sh --claude                 安装为 Claude Code 个人技能
#   ./install/install.sh --dsh                    安装到 DeepSeek Harness 技能目录
#   ./install/install.sh --dest ~/my-skills       安装到自定义父目录（得到 ~/my-skills/teamwork）
#   ./install/install.sh --claude --force --test  覆盖安装并运行自检
#
# 环境变量：
#   CLAUDE_SKILLS_DIR  覆盖 Claude Code 技能根目录（默认 ~/.claude/skills）
#   DSH_SKILLS_DIR     覆盖 DeepSeek Harness 技能根目录
#   PYTHON             Python 解释器（默认依次找 python3 / python）
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/skills/teamwork"

MODE="claude"
DEST_PARENT=""
FORCE=0
RUN_TEST=0

usage() {
  cat <<'EOF'
用法: install.sh [选项]

  --claude            安装到 Claude Code 个人技能目录
                      （$CLAUDE_SKILLS_DIR 或 ~/.claude/skills）/teamwork
  --dsh               安装到 DeepSeek Harness 技能目录（$DSH_SKILLS_DIR 或
                      D:/apps/deepseek-harness/data/skills）/teamwork
  --dest DIR          安装到自定义父目录，最终为 DIR/teamwork
  --force             目标已存在时覆盖（默认拒绝，避免误删本地改动）
  --test              安装后运行 selftest.py（13 阶段自检，约 1 分钟）
  -h, --help          显示本帮助

环境变量: CLAUDE_SKILLS_DIR / DSH_SKILLS_DIR / PYTHON / TEAMWORK_RUNS_ROOT
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --claude) MODE="claude"; shift ;;
    --dsh) MODE="dsh"; shift ;;
    --dest) MODE="dest"; DEST_PARENT="${2:?--dest 需要一个目录参数}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --test) RUN_TEST=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$MODE" in
  claude)
    DEST_PARENT="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
    ;;
  dsh)
    DEST_PARENT="${DSH_SKILLS_DIR:-D:/apps/deepseek-harness/data/skills}"
    ;;
  dest)
    [[ -n "$DEST_PARENT" ]] || { echo "错误: --dest 需要目录参数" >&2; exit 2; }
    ;;
esac

DEST="$DEST_PARENT/teamwork"

PY=""
for candidate in "${PYTHON:-}" python3 python; do
  [[ -n "$candidate" ]] || continue
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
[[ -n "$PY" ]] || { echo "错误: 找不到 Python（请设置 PYTHON 环境变量）" >&2; exit 2; }

if ! "$PY" -c "import yaml" >/dev/null 2>&1; then
  echo "错误: Python 缺少 PyYAML。请先安装：$PY -m pip install pyyaml" >&2
  exit 2
fi

if [[ -e "$DEST" ]]; then
  if [[ "$FORCE" -ne 1 ]]; then
    echo "目标已存在: $DEST" >&2
    echo "如需覆盖请加 --force（会先备份为 $DEST.backup-<时间戳>）" >&2
    exit 2
  fi
  BACKUP="$DEST.backup-$(date +%Y%m%d-%H%M%S)"
  mv "$DEST" "$BACKUP"
  echo "[ok] 已备份旧版本到 $BACKUP"
fi

mkdir -p "$DEST_PARENT"
# 复制时排除 __pycache__/*.pyc
cp -R "$SRC" "$DEST"
find "$DEST" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find "$DEST" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete 2>/dev/null || true

echo "[ok] 已安装 teamwork -> $DEST"
"$PY" "$DEST/scripts/orchestrator.py" --help >/dev/null && echo "[ok] 命令行入口可用"

if [[ "$RUN_TEST" -eq 1 ]]; then
  echo "[..] 运行自检（TEAMWORK_RUNS_ROOT=$DEST_PARENT/.teamwork-selftest）"
  TEAMWORK_RUNS_ROOT="$DEST_PARENT/.teamwork-selftest" "$PY" "$DEST/scripts/selftest.py"
  rm -rf "$DEST_PARENT/.teamwork-selftest"
  echo "[ok] 自检通过并已清理临时目录"
fi

cat <<EOF

安装完成。接下来：
  Claude Code: 新开会话，输入 /teamwork:run N=3 <任务>；或直接说"用 teamwork 跑……"
  DeepSeek Harness: 新开会话，输入  teamwork, N=3 <任务>
  纯命令行: $PY "$DEST/scripts/orchestrator.py" --help
EOF
