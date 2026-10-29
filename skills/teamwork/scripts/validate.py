"""独立校验入口（CI / 手工检查用）。

与 `orchestrator.py check` 等价，但不推进任何状态；校验不通过时 exit 2。
用法：
  python scripts/validate.py <run_dir> [--phase CLASSIFY] [--json]
  python3 scripts/validate.py --root ./teamwork-runs          # 取最新 run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import teamwork_lib as lib  # noqa: E402


def _resolve(run_arg: str | None, root_arg: str | None) -> Path:
    if run_arg:
        run = Path(run_arg).expanduser().resolve()
        if not lib.state_file(run).exists():
            raise lib.TeamworkError(f"不是有效的 run 目录：{run}")
        return run
    root = Path(root_arg or lib.DEFAULT_RUNS_ROOT)
    if not root.exists():
        raise lib.TeamworkError(f"找不到 run 根目录：{root}")
    candidates = [p for p in root.iterdir() if p.is_dir() and lib.state_file(p).exists()]
    if not candidates:
        raise lib.TeamworkError(f"{root} 下没有 run")
    return max(candidates, key=lambda p: lib.state_file(p).stat().st_mtime)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    parser = argparse.ArgumentParser(prog="validate.py", description="校验 teamwork run 的当前阶段产物")
    parser.add_argument("run", nargs="?", help="run 目录（省略时取 --root 下最新）")
    parser.add_argument("--root", default=None)
    parser.add_argument("--phase", default=None, help="指定要校验的阶段（默认当前阶段）")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        run = _resolve(args.run, args.root)
        state = lib.load_state(run)
        if args.phase:
            if args.phase not in lib.PHASES:
                raise lib.TeamworkError(f"未知阶段：{args.phase}")
            state = dict(state)
            state["phase"] = args.phase
        check = lib.Check(run, state)
        lib.validate_phase(check)
    except lib.TeamworkError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2
    payload = {
        "run": str(run),
        "phase": state["phase"],
        "iteration": state["current_iter"],
        "ok": not check.errors,
        "errors": check.errors,
        "warnings": check.warnings,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for warning in check.warnings:
            print(f"[警告] {warning}")
        if check.errors:
            print(f"校验失败：{len(check.errors)} 个问题")
            for error in check.errors:
                print(f"  - {error}")
        else:
            print(f"校验通过：{state['phase']}（第 {state['current_iter']} 轮）")
    return 2 if check.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
