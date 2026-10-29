#!/usr/bin/env python3
"""本地等效 CI：一条命令跑完 CI 里的关键检查。

顺序：
    1. py_compile  skills/teamwork/scripts/*.py
    2. sync --check（skills/teamwork 与 .claude/skills/teamwork 字节一致）
    3. 13 阶段 selftest（可用 --skip-selftest 跳过）

用法：
    python3 tools/check.py
    python3 tools/check.py --skip-selftest

退出码：0 = 全部通过；1 = 有检查失败（可直接用于 pre-commit / CI 门禁）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "skills" / "teamwork" / "scripts"
CHECK_RUNS = REPO / ".tmp-check" / "runs"


def _prefer_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def run(label: str, cmd: list[str], env: dict[str, str] | None = None) -> bool:
    print(f"\n== {label} ==")
    print("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(REPO), env=env)
    if proc.returncode != 0:
        print(f"[失败] {label}（exit {proc.returncode}）", file=sys.stderr)
        return False
    print(f"[ok] {label}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="本地等效 CI 检查")
    parser.add_argument("--skip-selftest", action="store_true", help="只跑 py_compile + sync --check")
    args = parser.parse_args()

    _prefer_utf8_stdio()
    ok = True

    py_files = sorted(str(p.relative_to(REPO)) for p in SCRIPTS.glob("*.py"))
    if not py_files:
        print(f"[错误] 在 {SCRIPTS} 下没有找到 .py 文件", file=sys.stderr)
        return 1
    ok &= run("py_compile", [sys.executable, "-m", "py_compile", *py_files])

    ok &= run("sync --check", [sys.executable, "tools/sync_claude.py", "--check"])

    if args.skip_selftest:
        print("\n== 13 阶段 selftest（已跳过）==")
    else:
        CHECK_RUNS.mkdir(parents=True, exist_ok=True)
        env = {
            **os.environ,
            "TEAMWORK_RUNS_ROOT": str(CHECK_RUNS),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        ok &= run("13 阶段 selftest", [sys.executable, str(SCRIPTS / "selftest.py")], env=env)

    print()
    if ok:
        print("全部检查通过。")
        return 0
    print("检查失败，请修复后重试。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
