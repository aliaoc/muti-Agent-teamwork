"""睡眠任务（环外）：把跨 run 的错误压成教训，刷新指标，做规划校准。

刻意不做的事：
- 不碰任何 run 目录（只读 runs/*.json）；
- 不自动改评分权重（尺子演进走 `orchestrator.py dream`）；
- 不自动改 worker 数量（L2 只出报告，人工决定是否采纳）。

用法：
    python scripts/sleep.py all                       # record 已有 run + distill + retire + metrics
    python scripts/sleep.py record <run_dir> [...]    # 手动补录
    python scripts/sleep.py distill [--min-support 2]
    python scripts/sleep.py metrics
    python scripts/sleep.py calibrate
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import teamwork_lib as lib  # noqa: E402
import rsi_store  # noqa: E402


def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass


def cmd_record(args: argparse.Namespace) -> int:
    if not args.run_dirs:
        print("需要至少一个 run 目录", file=sys.stderr)
        return 2
    for raw in args.run_dirs:
        run = Path(raw).expanduser().resolve()
        if not lib.state_file(run).exists():
            print(f"[跳过] 不是有效 run：{run}", file=sys.stderr)
            continue
        result = rsi_store.record_run(run)
        print(f"[ok] 已记录 {result['run_id']} -> {result['path']}")
    return 0


def cmd_distill(args: argparse.Namespace) -> int:
    runs = rsi_store.load_runs()
    created = rsi_store.distill_lessons(runs, min_support=args.min_support)
    if not created:
        print(f"没有新教训（样本 {len(runs)} 个 run；需要 ≥2 个 run 支持同一错误类别）")
        return 0
    for lesson in created:
        print(f"[ok] {lesson['id']}（{','.join(lesson['error_classes'])}）{lesson['action'][:60]}")
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    runs = rsi_store.load_runs()
    path = rsi_store.render_metrics(runs)
    metrics = rsi_store.compute_metrics(runs)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"\n看板已写入：{path}")
    return 0


def cmd_retire(args: argparse.Namespace) -> int:
    retired = rsi_store.retire_lessons()
    print("已退役：" + (", ".join(retired) if retired else "（无）"))
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    runs = rsi_store.load_runs()
    if not runs:
        print("经验库为空：先跑几个 run 再校准")
        return 0
    buckets: dict[tuple[str, int], list[dict]] = {}
    for run in runs:
        tags = run.get("tags") or {}
        key = (str(tags.get("tier") or "?"), int(tags.get("workers") or 0))
        buckets.setdefault(key, []).append(run)
    rows = []
    for (tier, workers), items in sorted(buckets.items()):
        first_pass = sum(
            1
            for r in items
            if (r.get("scores") or [{}])[0].get("verdict") == "PASS"
        )
        avg_score = statistics.mean(
            float((r.get("scores") or [{}])[-1].get("total") or 0) for r in items
        )
        avg_iter = statistics.mean(int(r.get("iterations") or 0) for r in items)
        rows.append(
            {
                "tier": tier,
                "workers": workers,
                "runs": len(items),
                "first_pass_rate": round(first_pass / len(items), 3),
                "avg_final_score": round(avg_score, 1),
                "avg_iterations": round(avg_iter, 2),
            }
        )
    print("规划校准（只报告，不自动改配置）：")
    print(f"{'tier':<8}{'workers':<8}{'runs':<6}{'首轮通过':<10}{'终分':<8}{'平均轮数':<8}")
    for row in rows:
        print(
            f"{row['tier']:<8}{row['workers']:<8}{row['runs']:<6}"
            f"{row['first_pass_rate']:<10.0%}{row['avg_final_score']:<8}{row['avg_iterations']:<8}"
        )
    weak = [r for r in rows if r["runs"] >= 2 and r["first_pass_rate"] < 0.5]
    if weak:
        print("\n建议关注（首轮通过率 < 50%，样本 ≥2）：")
        for row in weak:
            print(f"  - {row['tier']} / {row['workers']} 人：首轮通过 {row['first_pass_rate']:.0%}")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    for run in args.run_dirs:
        path = Path(run).expanduser().resolve()
        if lib.state_file(path).exists():
            rsi_store.record_run(path)
    created = rsi_store.distill_lessons()
    retired = rsi_store.retire_lessons()
    path = rsi_store.render_metrics()
    print(f"教训新增 {len(created)} 条，退役 {len(retired)} 条，看板：{path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sleep.py", description="teamwork 环外睡眠任务")
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record", help="把 run 落库到经验库")
    record.add_argument("run_dirs", nargs="+")
    record.set_defaults(func=cmd_record)

    distill = sub.add_parser("distill", help="把跨 run 反复出现的错误压成教训")
    distill.add_argument("--min-support", type=int, default=rsi_store.LESSON_MIN_SUPPORT)
    distill.set_defaults(func=cmd_distill)

    metrics = sub.add_parser("metrics", help="刷新指标看板")
    metrics.set_defaults(func=cmd_metrics)

    retire = sub.add_parser("retire", help="淘汰命中率低于基线的教训")
    retire.set_defaults(func=cmd_retire)

    calibrate = sub.add_parser("calibrate", help="规划校准报告（只读）")
    calibrate.set_defaults(func=cmd_calibrate)

    all_cmd = sub.add_parser("all", help="record + distill + retire + metrics")
    all_cmd.add_argument("run_dirs", nargs="*")
    all_cmd.set_defaults(func=cmd_all)
    return parser


def main(argv: list[str] | None = None) -> int:
    _utf8()
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except lib.TeamworkError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
