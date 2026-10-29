"""teamwork 编排 CLI。

流程、阶段顺序、校验规则、评分合成全部由 teamwork_lib 写死；本文件只做参数解析
和输出。任何一步校验不通过都会以 exit 2 拒绝推进（这是防 AI 幻觉/跳步的关键）。

用法示例：
  python scripts/orchestrator.py init --cmd "teamwork, N=2 帮我整理报告"
  python scripts/orchestrator.py next
  python scripts/orchestrator.py status
  python scripts/orchestrator.py check
  python scripts/orchestrator.py advance
  python scripts/orchestrator.py make-packet
  python scripts/orchestrator.py render
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import teamwork_lib as lib  # noqa: E402


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass


def _out_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _human_next(data: dict) -> None:
    print(f"== {data['phase_label']}（第 {data['iteration']}/{data['n'] or '?'} 轮）==")
    print(f"角色：{data['role']}")
    print(f"状态：{data['status_line']}")
    print(f"说明：{data['instruction']}")
    if data.get("worker_range"):
        print(f"人数范围：{data['worker_range']['min']}–{data['worker_range']['max']}")
    print("需要产出：")
    for item in data.get("outputs") or []:
        print(f"  - {item}")
    if data.get("templates"):
        print("模板：")
        for item in data["templates"]:
            print(f"  - {item}")
    if data.get("subagents"):
        print("子 Agent：")
        print("  " + json.dumps(data["subagents"], ensure_ascii=False, indent=2).replace("\n", "\n  "))
    print(f"下一步：{data['next_command']}")


def _resolve_run(args: argparse.Namespace) -> Path:
    if getattr(args, "run", None):
        run = Path(args.run).expanduser().resolve()
        if not lib.state_file(run).exists():
            raise lib.TeamworkError(f"不是有效的 run 目录（缺少 .teamwork/state.json）：{run}")
        return run
    root = Path(getattr(args, "root", None) or lib.DEFAULT_RUNS_ROOT)
    if not root.exists():
        raise lib.TeamworkError(f"找不到 run 根目录：{root}")
    candidates = [
        item
        for item in root.iterdir()
        if item.is_dir() and lib.state_file(item).exists()
    ]
    if not candidates:
        raise lib.TeamworkError(f"{root} 下还没有任何 run")
    latest = max(candidates, key=lambda p: lib.state_file(p).stat().st_mtime)
    return latest


def _status_human(data: dict) -> None:
    print(f"run    : {data['run_id']}")
    print(f"目录   : {data['run_dir']}")
    print(f"阶段   : {data['phase']}（{data['phase_label']}）")
    print(f"等级   : {data['tier'] or '未分级'} ｜ N={data['n'] if data['n'] is not None else '待定'}（{data['n_mode']}）")
    print(f"迭代   : {data['current_iter']}")
    print(f"审核   : ×{data['reviewers']}（策略 {data['policy_version']}）")
    print(f"Worker : " + ("、".join(f"{w['id']}={w['status']}" for w in data["workers"]) or "（未派发）"))
    coach = data.get("coach") or {}
    if coach.get("entries") or coach.get("stuck_classes"):
        last = (coach.get("entries") or [{}])[-1]
        print(
            f"教练   : 命中率 {last.get('hit_rate') if last.get('hit_rate') is not None else '—'}"
            f" · 卡住类别 {', '.join(coach.get('stuck_classes') or []) or '无'}"
        )
    if data["scores"]:
        print("分数   : " + " → ".join(f"{s['total']} {s['verdict']}" for s in data["scores"]))
    advisory = data.get("advisory") or {}
    if advisory:
        print(
            f"建议   : {advisory['recommendation']} +{advisory['recommended_rounds']} 轮"
            f"（{advisory['score']} {advisory['verdict']}）"
        )
    print(f"看板   : {data['progress']}")
    print(f"框架图 : {data.get('framework_png') or '（未生成：未安装 matplotlib）'}")
    print(f"状态行 : {data['status_line']}")


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root or lib.DEFAULT_RUNS_ROOT)
    run_dir = lib.create_run(root, args.cmd, args.task)
    state = lib.load_state(run_dir)
    data = {
        "run_dir": str(run_dir),
        "run_id": state["run_id"],
        "n_mode": state["n_mode"],
        "explicit_n": state["explicit_n"],
        "status_line": lib.status_line(state),
        "framework_png": (
            lib.rel(run_dir, lib.run_paths(run_dir, 1)["framework_png"])
            if lib.run_paths(run_dir, 1)["framework_png"].exists()
            else None
        ),
    }
    if args.json:
        _out_json(data)
    else:
        print(f"已创建 run：{data['run_dir']}")
        print(f"状态：{data['status_line']}")
        print(f"框架图：{data['framework_png']}")
        _human_next(lib.build_next(run_dir))
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    data = lib.build_next(run)
    if args.json:
        _out_json(data)
    else:
        _human_next(data)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    data = lib.current_status(run)
    if args.json:
        _out_json(data)
    else:
        _status_human(data)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    state = lib.load_state(run)
    if args.phase:
        phase = lib.PHASE_ALIASES.get(args.phase, args.phase)
        if phase not in lib.PHASES:
            raise lib.TeamworkError(f"未知阶段：{args.phase}")
        state = dict(state)
        state["phase"] = phase
    check = lib.Check(run, state)
    lib.validate_phase(check)
    if args.json:
        _out_json(
            {
                "run": str(run),
                "phase": state["phase"],
                "iteration": state["current_iter"],
                "ok": not check.errors,
                "errors": check.errors,
                "warnings": check.warnings,
            }
        )
    else:
        for warning in check.warnings:
            print(f"[警告] {warning}")
        if check.errors:
            print(f"校验失败：{len(check.errors)} 个问题（拒绝推进）")
            for error in check.errors:
                print(f"  - {error}")
        else:
            print(f"校验通过：{state['phase']}（第 {state['current_iter']} 轮）")
    return 2 if check.errors else 0


def cmd_advance(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    result = lib.advance_run(run)
    state = lib.load_state(run)
    result["status_line"] = lib.status_line(state)
    result["framework_png"] = lib.rel(run, lib.run_paths(run, state["current_iter"])["framework_png"])
    if args.json:
        _out_json(result)
    else:
        if result["warnings"]:
            for warning in result["warnings"]:
                print(f"[警告] {warning}")
        print(f"阶段推进：{result['from']} → {result['to']}（第 {result['iteration']}/{result['n']} 轮）")
        print(f"状态行：{result['status_line']}")
        print(f"框架图：{result['framework_png']}")
        coach = result.get("coach") or {}
        if coach.get("items") or coach.get("hit_rate") is not None:
            print(
                f"教练：{len(coach.get('items') or [])} 条条目 · "
                f"命中率 {coach.get('hit_rate') if coach.get('hit_rate') is not None else '—'}"
            )
        advisory = result.get("advisory") or {}
        if advisory:
            print("--- 末轮建议（必须原样播报给用户）---")
            print(
                f"本轮 {advisory['score']} 分 / {advisory['verdict']}"
                f"（较上轮 {advisory['delta'] if advisory['delta'] is not None else '—'}，"
                f"短板：{lib.DIM_LABELS.get(advisory['weakest_dimension']['name'], '—')}"
                f" {advisory['weakest_dimension']['score']}）"
            )
            if advisory["recommendation"] == "continue":
                print(
                    f"建议再迭代 {advisory['recommended_rounds']} 轮：{advisory['rationale']}"
                )
            else:
                print(f"建议就此收尾：{advisory['rationale']}")
        print("--- 下一步 ---")
        _human_next(lib.build_next(run))
    return 0


def cmd_make_packet(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    state = lib.load_state(run)
    if state["phase"] != "FINAL":
        raise lib.TeamworkError("make-packet 只能在 FINAL 阶段运行")
    path = lib.make_review_packet(run, state)
    data = {
        "packet": lib.rel(run, path),
        "reviewers": state.get("review", {}).get("reviewers", 1),
        "policy_version": state.get("review", {}).get("policy_version", "v0"),
    }
    if args.json:
        _out_json(data)
    else:
        print(f"评审包已生成：{data['packet']}（评审 ×{data['reviewers']}，策略 {data['policy_version']}）")
        print("注意：评审子 Agent 只能读该文件与其 artifacts，禁止读 run_report/state.json。")
    return 0


def cmd_merge_review(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    state = lib.load_state(run)
    merged = lib.compute_merged_review(run, state)
    if args.json:
        _out_json(merged)
    else:
        print(f"第 {merged['iteration']} 轮：{merged['merged_total']} 分 · {merged['merged_verdict']}")
        for reviewer in merged["reviewers"]:
            print(f"  {reviewer['id']}：{reviewer['total']} · {reviewer['verdict']}")
        if merged["gate_failures"]:
            print(f"  一票否决：{', '.join(merged['gate_failures'])}")
        if merged["disagreements"]:
            print(f"  分歧维度：{merged['disagreements']}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    data = lib.render_run(run)
    if args.trend:
        try:
            import render_diagram  # noqa: WPS433

            data.update(render_diagram.render_score_trend(run))
        except Exception as exc:
            data["score_trend_error"] = str(exc)
    if args.json:
        _out_json(data)
    else:
        print("已渲染：")
        for key, value in data.items():
            print(f"  {key}: {value if value is not None else '（跳过：未安装 matplotlib）'}")
    return 0


def cmd_set_n(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    result = lib.set_n(run, args.n)
    if args.json:
        _out_json(result)
    else:
        print(f"迭代次数：{result['from']} → {result['to']}")
    return 0


def cmd_set_tier(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    result = lib.set_tier(run, args.tier, args.reason)
    if args.json:
        _out_json(result)
    else:
        print(f"等级：{result['from'] or '未分级'} → {result['to']}（N={result['n']}）")
    return 0


def cmd_dual_review(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    result = lib.set_dual_review(run, args.on)
    if args.json:
        _out_json(result)
    else:
        print(f"评审人数：×{result['reviewers']}")
    return 0


def cmd_set_reviewers(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    result = lib.set_reviewers(run, args.count)
    if args.json:
        _out_json(result)
    else:
        print(f"评审人数：×{result['reviewers']}（可随时按任务需要调整，审核开始前生效）")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    result = lib.stop_run(run, args.reason)
    if args.json:
        _out_json(result)
    else:
        print(f"已停止：阶段={result['phase']}（历史与产物保留，可后续归档）")
    return 0


def cmd_extend(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    result = lib.extend_run(run, args.rounds, args.reason, force=args.force)
    if args.json:
        _out_json(result)
    else:
        print(
            f"已追加：第 {result['from_iteration']} 轮 → 第 {result['to_iteration']} 轮，"
            f"n={result['n']}，当前阶段 {result['phase']}"
        )
    return 0


def cmd_citation_audit(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    if args.on == args.off:
        raise lib.TeamworkError("citation-audit 需要且只需要 --on 或 --off 之一")
    result = lib.set_citation_audit(run, bool(args.on), args.reason)
    if args.json:
        _out_json(result)
    else:
        print(
            f"引用核验：{result['citation_audit']}（评审 ×{result['reviewers']}）；"
            "L 级默认开启，B 专责逐条核验"
        )
    return 0


def cmd_coach_show(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    data = lib.coach_show(run)
    if args.json:
        _out_json(data)
    else:
        print(f"当前轮次：{data['iteration']}")
        print(f"卡住类别：{', '.join(data['stuck_classes']) or '无'}")
        print(f"已判无效：{', '.join(data['ineffective']) or '无'}")
        for entry in data["entries"]:
            print(
                f"  第 {entry.get('iteration')} 轮：条目 {len(entry.get('items') or [])} · "
                f"命中率 {entry.get('hit_rate') if entry.get('hit_rate') is not None else '—'}"
            )
        advisory = data.get("advisory")
        if advisory:
            print(
                f"末轮建议：{advisory['recommendation']} +{advisory['recommended_rounds']} 轮"
            )
    return 0


def cmd_dream(args: argparse.Namespace) -> int:
    import rsi_store  # noqa: WPS433

    if args.approve:
        path = rsi_store.approve(args.approve)
        print(f"已批准策略：{args.approve} -> {path}")
        return 0
    if args.rollback is not None:
        version = rsi_store.rollback(args.rollback or None)
        print(f"已回滚到：{version}")
        return 0
    path = rsi_store.build_proposal()
    if args.json:
        _out_json({"proposal": str(path)})
    else:
        print(f"提案已生成：{path}")
        print("批准：python scripts/orchestrator.py dream --approve <版本号>")
    return 0


def cmd_adopt_policy(args: argparse.Namespace) -> int:
    import rsi_store  # noqa: WPS433

    run = _resolve_run(args)
    result = rsi_store.adopt_policy(run, args.version)
    if args.json:
        _out_json(result)
    else:
        print(f"已采纳策略 {result['policy_version']}（{result['path']}）")
    return 0


def cmd_finish(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    result = lib.finish_run(run)
    if args.json:
        _out_json(result)
    else:
        print(f"已结束 run：{result['run_dir']}")
        print(f"最终报告：{result['final_report']}")
        trend = Path(result["run_dir"]) / "score_trend.png"
        print(f"分数轨迹图：{lib.rel(Path(result['run_dir']), trend) if trend.exists() else '（跳过：未安装 matplotlib）'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("run", nargs="?", help="run 目录；省略时取 --root 下最新的 run")
    common.add_argument("--root", default=None, help="run 根目录（默认 $TEAMWORK_RUNS_ROOT 或 ./teamwork-runs）")
    common.add_argument("--json", action="store_true", help="输出 JSON")

    parser = argparse.ArgumentParser(
        prog="orchestrator.py",
        description="teamwork 状态机：唯一合法的下一步由脚本给出，跳步会被拒绝（exit 2）。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="创建 run（必须带 teamwork 启动命令）")
    init.add_argument("--cmd", required=True, help='例如 "teamwork, N=2 整理报告"')
    init.add_argument("--task", default=None, help="任务描述（缺省取 --cmd 中命令之后的部分）")
    init.add_argument("--root", default=None)
    init.add_argument("--json", action="store_true")
    init.set_defaults(func=cmd_init)

    for name, func, help_text in (
        ("next", cmd_next, "打印当前阶段唯一合法的下一步"),
        ("status", cmd_status, "打印状态"),
        ("check", cmd_check, "校验当前阶段产物（失败 exit 2）"),
        ("advance", cmd_advance, "校验通过后推进到下一阶段"),
        ("make-packet", cmd_make_packet, "FINAL 阶段生成评审包"),
        ("merge-review", cmd_merge_review, "合成评审分数（只读）"),
        ("render", cmd_render, "重渲染框架图/看板"),
        ("finish", cmd_finish, "DONE 阶段收尾（生成分数轨迹图）"),
    ):
        p = sub.add_parser(name, parents=[common], help=help_text)
        p.set_defaults(func=func)
        if name == "check":
            p.add_argument("--phase", default=None, help="改为校验指定阶段（调试用）")
        if name == "render":
            p.add_argument("--trend", action="store_true", help="同时生成 score_trend.png")

    set_n = sub.add_parser("set-n", parents=[common], help="修改迭代次数")
    set_n.add_argument("--n", type=int, required=True)
    set_n.set_defaults(func=cmd_set_n)

    set_tier = sub.add_parser("set-tier", parents=[common], help="手动调整任务等级")
    set_tier.add_argument("--tier", choices=sorted(lib.TIER_RANGES), required=True)
    set_tier.add_argument("--reason", required=True)
    set_tier.set_defaults(func=cmd_set_tier)

    dual = sub.add_parser("dual-review", parents=[common], help="开启/关闭双评审")
    dual.add_argument("--on", action="store_true", help="开启双评审（需要用户确认）")
    dual.add_argument("--off", action="store_true", help="关闭双评审")
    dual.set_defaults(func=cmd_dual_review)

    reviewers = sub.add_parser(
        "reviewers", parents=[common], help="设置评审 Agent 数量（1–26，按任务需要）"
    )
    reviewers.add_argument("--count", type=int, required=True)
    reviewers.set_defaults(func=cmd_set_reviewers)

    stop = sub.add_parser("stop", parents=[common], help="提前停止（保留产物）")
    stop.add_argument("--reason", default="")
    stop.set_defaults(func=cmd_stop)

    extend = sub.add_parser("extend", parents=[common], help="DONE 后追加轮次（续跑）")
    extend.add_argument("--rounds", type=int, required=True, help="追加轮数（1–3）")
    extend.add_argument("--reason", default="")
    extend.add_argument("--force", action="store_true", help="归档旧 final_report 后再追加")
    extend.set_defaults(func=cmd_extend)

    citation = sub.add_parser(
        "citation-audit", parents=[common], help="开关 L 级引用核验（B 专责）"
    )
    citation.add_argument("--on", action="store_true")
    citation.add_argument("--off", action="store_true")
    citation.add_argument("--reason", default="")
    citation.set_defaults(func=cmd_citation_audit)

    coach = sub.add_parser("coach-show", parents=[common], help="查看教练条目与命中率")
    coach.set_defaults(func=cmd_coach_show)

    dream = sub.add_parser("dream", help="环外尺子演进（不写 run 目录）")
    dream.add_argument(
        "--offline",
        action="store_true",
        help="显式声明离线执行（默认行为，仅作可读标注）",
    )
    dream.add_argument("--propose", action="store_true", help="生成候选策略提案（默认动作）")
    dream.add_argument("--approve", default=None, help="批准提案版本号（如 v1）")
    dream.add_argument("--rollback", nargs="?", const="", default=None, help="回滚到上一版或指定版本")
    dream.add_argument("--json", action="store_true")
    dream.set_defaults(func=cmd_dream)

    adopt = sub.add_parser("adopt-policy", parents=[common], help="把经验库策略采纳进 run")
    adopt.add_argument("--version", required=True)
    adopt.set_defaults(func=cmd_adopt_policy)

    return parser


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    args = build_parser().parse_args(argv)
    if args.command == "dual-review":
        if args.on == args.off:
            raise SystemExit("dual-review 需要且只需要 --on 或 --off 之一")
        args.on = bool(args.on)
    try:
        return int(args.func(args))
    except lib.ValidationFailed as exc:
        print("[校验失败] 拒绝推进：", file=sys.stderr)
        for error in exc.errors:
            print(f"  - {error}", file=sys.stderr)
        for warning in exc.warnings:
            print(f"  [警告] {warning}", file=sys.stderr)
        return 2
    except lib.TeamworkError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n[中断] 未完成任何未提交的状态变更", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
