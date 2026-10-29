"""自测：在 $TEAMWORK_RUNS_ROOT/_selftest（默认 ./teamwork-runs/_selftest）下造一个完整 run。

覆盖：
- 状态机全流程（INIT→…→DONE→finish），两轮迭代，第一轮含 REWORK 打回；
- 双评审（A+B）与单评审切换；评审独立性（缺 B 时拒绝推进）；
- 每个阶段都渲染 framework.mmd / PROGRESS.md（装了 matplotlib 时另出 framework.png）；
- 校验不通过时拒绝推进（exit 2 的等价异常）；
- CLI 入口（init/advance/status/check/next）的退出码与 JSON 输出。

运行：python3 scripts/selftest.py（Windows 用 python；必须 pip install pyyaml，matplotlib 可选）。
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import teamwork_lib as lib  # noqa: E402

# 默认写到 $TEAMWORK_RUNS_ROOT/_selftest（默认 ./teamwork-runs/_selftest）。
SELFTEST_DIR = Path(
    os.environ.get("TEAMWORK_RUNS_ROOT", str(lib.DEFAULT_RUNS_ROOT))
) / "_selftest"

# matplotlib 是可选依赖：未安装时只产出 PROGRESS.md / framework.mmd，跳过 PNG 断言。
# TEAMWORK_NO_MPL=1 可强制模拟「未安装」路径（CI/本地都可复现）。
HAS_MPL = os.environ.get("TEAMWORK_NO_MPL") != "1" and importlib.util.find_spec("matplotlib") is not None

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)
        print(f"  [FAIL] {message}")
    else:
        print(f"  [ok] {message}")


def sha(path: Path) -> str:
    return lib.sha256_file(path)


def write(run: Path, relative: str, fm: dict, body: str = "") -> Path:
    path = run / relative
    lib.write_artifact(path, fm, body)
    return path


def state_of(run: Path) -> dict:
    return lib.load_state(run)


def expect_phase(run: Path, phase: str) -> dict:
    state = state_of(run)
    check(state["phase"] == phase, f"阶段应为 {phase}（实际 {state['phase']}）")
    return state


def mk_classification(run: Path) -> None:
    write(
        run,
        "00_intake/classification.md",
        {
            "schema_version": 1,
            "tier": "Medium",
            "tier_reason": "涉及 3 个独立子任务，需要检索并汇总，有可验证产物",
            "signals": {
                "files": 3,
                "external": True,
                "verifiable": True,
                "parallel": True,
                "risk": "low",
                "user_demand": True,
            },
            "n_adjust": 0,
            "workers_planned": 3,
            "user_confirmed": True,
        },
        "# 分级\n\nMedium：3 个并行子任务，2 轮迭代。\n",
    )


def mk_plan(run: Path, iteration: int) -> None:
    write(
        run,
        f"01_plans/plan-iter-{iteration:02d}.md",
        {
            "schema_version": 1,
            "iteration": iteration,
            "tier": "Medium",
            "objective": f"第 {iteration} 轮：整理可行方案并给出证据",
            "breakdown": [
                {"desc": "梳理需求与约束", "assignee": "w01"},
                {"desc": "收集证据并对比方案", "assignee": "w02"},
                {"desc": "写出结论与风险", "assignee": "w03"},
            ],
            "accepted_criteria": ["结论有证据链", "风险已标注", "产物文件存在"],
            "risks": ["证据来源可能不足"],
            "worker_count": 3,
        },
        f"# 计划（第 {iteration} 轮）\n\n1. w01 梳理需求\n2. w02 收集证据\n3. w03 写结论\n",
    )


def mk_dispatch(run: Path, iteration: int) -> list[str]:
    rels = []
    workers = []
    for idx in range(1, 4):
        wid = f"w{idx:02d}"
        artifact = run / "iterations" / f"iter-{iteration:02d}" / "workers" / f"{wid}_artifacts" / "out.md"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(f"# {wid} 产物（第 {iteration} 轮）\n\n内容占位。\n", encoding="utf-8")
        rels.append(lib.rel(run, artifact))
        workers.append(
            {
                "id": wid,
                "scope": f"子任务 {idx}",
                "deliverables": [lib.rel(run, artifact)],
                "acceptance": "产物存在且有正文",
            }
        )
    write(
        run,
        f"01_plans/dispatch-iter-{iteration:02d}.md",
        {
            "schema_version": 1,
            "iteration": iteration,
            "mode": "parallel",
            "workers": workers,
        },
        f"# 派发（第 {iteration} 轮）\n\n三个 worker 并行，各自写自己的目录。\n",
    )
    return rels


def mk_workers(run: Path, iteration: int, dispatch_rels: list[str], update_w01: bool = False) -> None:
    for idx, rel in enumerate(dispatch_rels, 1):
        wid = f"w{idx:02d}"
        version = "（重做版）" if update_w01 and wid == "w01" else ""
        write(
            run,
            f"iterations/iter-{iteration:02d}/workers/{wid}_result.md",
            {
                "schema_version": 1,
                "worker_id": wid,
                "iteration": iteration,
                "scope": f"子任务 {idx}",
                "status": "completed",
                "deliverables": [{"path": rel, "sha256": sha(run / rel)}],
                "claims": [
                    {
                        "text": f"{wid} 在第 {iteration} 轮完成了子任务 {idx}{version}",
                        "evidence": [rel],
                    }
                ],
                "open_questions": [],
                "confidence": "high",
            },
            f"# {wid} 结果\n\n子任务 {idx} 完成{version}。\n",
        )


def mk_final(run: Path, iteration: int, deliverable: str) -> None:
    write(
        run,
        f"iterations/iter-{iteration:02d}/final_result.md",
        {
            "schema_version": 1,
            "iteration": iteration,
            "summary": f"第 {iteration} 轮汇总：结论与证据已整理",
            "deliverables": [{"path": deliverable, "sha256": sha(run / deliverable)}],
            "coverage": [
                {"requirement": "结论有证据链", "where": deliverable, "status": "covered"},
                {"requirement": "风险已标注", "where": "run_report.md", "status": "covered"},
            ],
            "unresolved": [],
        },
        f"# 最终结果（第 {iteration} 轮）\n\n结论：方案可行。证据见 {deliverable}。\n",
    )
    write(
        run,
        f"iterations/iter-{iteration:02d}/run_report.md",
        {
            "schema_version": 1,
            "iteration": iteration,
            "tier": "Medium",
            "workers": 3,
            "highlights": [f"第 {iteration} 轮 3 个 worker 全部完成"],
            "issues": [],
            "next_suggestions": ["保持当前分工"] if iteration == 1 else [],
        },
        f"# 运行报告（第 {iteration} 轮）\n\n3 个 worker 并行完成，无阻塞。\n",
    )


def mk_gate(run: Path, iteration: int, verdict: str, targets: list[str], note: str) -> None:
    checklist = [
        {"item": "需求覆盖", "pass": verdict == "PASS"},
        {"item": "证据齐全", "pass": verdict == "PASS"},
        {"item": "产物文件存在", "pass": True},
    ]
    write(
        run,
        f"iterations/iter-{iteration:02d}/gate.md",
        {
            "schema_version": 1,
            "iteration": iteration,
            "verdict": verdict,
            "checklist": checklist,
            "rework_targets": targets,
            "note": note,
        },
        f"# 验收（第 {iteration} 轮）\n\n结论：{verdict}。{note}\n",
    )


def verdict_for(total: int) -> str:
    if total >= 85:
        return "PASS"
    if total >= 60:
        return "REVISE"
    return "FAIL"


def mk_review(run: Path, iteration: int, reviewer: str, total: int) -> None:
    packet_rel = f"iterations/iter-{iteration:02d}/review_packet.md"
    dims = [
        {
            "name": name,
            "weight": weight,
            "score": total,
            "evidence": [packet_rel],
        }
        for name, weight in lib.RUBRIC_V0["weights"].items()
    ]
    path = run / "iterations" / f"iter-{iteration:02d}" / f"review_report_{reviewer}.md"
    write(
        run,
        lib.rel(run, path),
        {
            "schema_version": 1,
            "reviewer": reviewer,
            "iteration": iteration,
            "rubric_version": "v0",
            "inputs_read": [packet_rel, f"iterations/iter-{iteration:02d}/final_result.md"],
            "independence_attestation": True,
            "dimensions": dims,
            "gates_triggered": [],
            "errors": [],
            "optimizations": [{"suggestion": "证据引用再具体一些", "expected_gain": "+3"}],
            "total": total,
            "verdict": verdict_for(total),
        },
        f"# 审核报告 {reviewer}（第 {iteration} 轮）\n\n总分 {total}，结论 {verdict_for(total)}。\n",
    )


def mk_ledger(run: Path, iteration: int, decision: str, after: str) -> None:
    write(
        run,
        "review_policy/replay_ledger.md",
        {
            "schema_version": 1,
            "entries": [
                {
                    "iteration": iteration,
                    "policy_before": "v0",
                    "candidates": [
                        {
                            "id": "c1",
                            "change": "证据维度要求逐条给出文件+行号",
                            "replay_score": 78,
                        },
                        {
                            "id": "c2",
                            "change": "降低主观维度权重",
                            "replay_score": 71,
                        },
                    ],
                    "decision": decision,
                    "policy_after": after,
                    "reason": "候选未在历史迭代上体现区分度，保持 v0",
                }
            ],
        },
        "# 重放账本\n\n第 1 轮：候选 c1 未达到晋级门槛（胜出需 ≥2 条历史且不回归），keep。\n",
    )


def advance(run: Path, expected_to: str) -> None:
    result = lib.advance_run(run)
    check(result["to"] == expected_to, f"推进到 {expected_to}（实际 {result['to']}）")


def main() -> int:
    print("== 清理旧的 selftest 目录 ==")
    if SELFTEST_DIR.exists():
        shutil.rmtree(SELFTEST_DIR)
    SELFTEST_DIR.mkdir(parents=True, exist_ok=True)

    print("== 创建 run ==")
    run = lib.create_run(
        SELFTEST_DIR,
        "teamwork, N=2 自测：整理一份可行方案并给出证据",
    )
    print(f"  run = {run}")
    state = expect_phase(run, "INIT")
    check(state["n_mode"] == "explicit" and state["explicit_n"] == 2, "N=2 显式模式")
    if HAS_MPL:
        check((run / "framework.png").exists() and (run / "framework.png").stat().st_size > 0, "framework.png 已生成")
    else:
        print("  [skip] 未安装 matplotlib，跳过 framework.png 检查（framework.mmd/PROGRESS.md 仍校验）")
    check((run / "framework.mmd").exists(), "framework.mmd 已生成")
    check((run / "PROGRESS.md").exists(), "PROGRESS.md 已生成")
    check((run / "review_policy/v0.md").exists(), "review_policy/v0.md 已生成")

    print("== 阶段 1：INIT→CLASSIFY ==")
    advance(run, "CLASSIFY")
    print("== 跳步必须被拒绝 ==")
    try:
        lib.advance_run(run)
        check(False, "缺少 classification 时 advance 应失败")
    except lib.ValidationFailed as exc:
        check(any("classification" in error for error in exc.errors), "拒绝推进并给出缺失产物")

    print("== 阶段 2：CLASSIFY→PLAN ==")
    mk_classification(run)
    advance(run, "PLAN")
    state = state_of(run)
    check(state["tier"] == "Medium", "等级 Medium")
    check(state["n"] == 2, "自动轮数=Medium 默认 2")
    check(state["workers"]["planned"] == 3, "计划 worker=3")

    print("== 阶段 3：PLAN→DISPATCH→WORKERS ==")
    mk_plan(run, 1)
    advance(run, "DISPATCH")
    iteration1_rels = mk_dispatch(run, 1)
    advance(run, "WORKERS")
    mk_workers(run, 1, iteration1_rels)
    advance(run, "FINAL")
    nxt = lib.build_next(run)
    check(nxt["role"].startswith("主 Agent"), "Medium 的 FINAL 由主 Agent 直接做（不启子 Agent）")
    check(nxt["subagents"]["role"] == "main", "FINAL subagents.role=main")

    print("== 阶段 4：FINAL 双评审打包 ==")
    mk_final(run, 1, iteration1_rels[0])
    lib.set_dual_review(run, True)
    check(state_of(run)["review"]["reviewers"] == 2, "双评审已开启")
    lib.make_review_packet(run, state_of(run))
    advance(run, "GATE")

    print("== 阶段 5：GATE 打回 → WORKERS → FINAL ==")
    mk_gate(run, 1, "REWORK", ["w01"], "w01 的证据引用不完整")
    advance(run, "WORKERS")
    check(state_of(run)["rework_count"] == 1, "rework_count=1")
    mk_workers(run, 1, iteration1_rels, update_w01=True)
    advance(run, "FINAL")
    lib.make_review_packet(run, state_of(run))
    advance(run, "GATE")
    mk_gate(run, 1, "PASS", [], "重做后通过")
    advance(run, "REVIEW")

    print("== 阶段 6：双评审缺少 B 时必须拒绝 ==")
    mk_review(run, 1, "A", 78)
    try:
        lib.advance_run(run)
        check(False, "双评审只有 A 时应拒绝推进")
    except lib.ValidationFailed as exc:
        check(any("review_report_B" in error for error in exc.errors), "缺少 B 报告被拒绝")
    mk_review(run, 1, "B", 78)
    advance(run, "DREAM")
    state = state_of(run)
    check(len(state["scores"]) == 1, "第 1 轮分数已入库")
    check(state["scores"][0]["total"] == 78 and state["scores"][0]["verdict"] == "REVISE", "合成 78 REVISE")
    check(state["scores"][0]["reviewers"] == 2, "合成记录 reviewers=2")
    check((run / "iterations/iter-01/review_scores.md").exists(), "review_scores.md 已生成")

    print("== 阶段 7：DREAM（keep）→ 第 2 轮 ==")
    mk_ledger(run, 1, "keep", "v0")
    advance(run, "PLAN")
    state = state_of(run)
    check(state["current_iter"] == 2, "进入第 2 轮")
    check(state["review"]["policy_version"] == "v0", "策略保持 v0")
    lib.set_reviewers(run, 3)
    check(state_of(run)["review"]["reviewers"] == 3, "评审人数可设为 3（审核开始前生效）")

    print("== 阶段 8：第 2 轮（3 位评审）→ DONE ==")
    check(state_of(run)["review"]["reviewers"] == 3, "沿用 3 位评审")
    mk_plan(run, 2)
    advance(run, "DISPATCH")
    iteration2_rels = mk_dispatch(run, 2)
    advance(run, "WORKERS")
    state = state_of(run)
    check(
        set(state["workers"]["reused"]) == {"w01", "w02", "w03"},
        f"第 2 轮复用全部 worker（{state['workers']['reused']}）",
    )
    check(state["workers"]["new_ids"] == [], "第 2 轮未新建 worker")
    mk_workers(run, 2, iteration2_rels)
    advance(run, "FINAL")
    mk_final(run, 2, iteration2_rels[0])
    lib.make_review_packet(run, state_of(run))
    advance(run, "GATE")
    mk_gate(run, 2, "PASS", [], "第 2 轮通过")
    advance(run, "REVIEW")
    for letter in ("A", "B", "C"):
        mk_review(run, 2, letter, 86)
    advance(run, "DONE")
    state = state_of(run)
    check(state["current_iter"] == 2 and state["phase"] == "DONE", "两轮后进入 DONE")
    check(len(state["scores"]) == 2, "分数轨迹 2 条")
    check(state["scores"][1]["total"] == 86 and state["scores"][1]["verdict"] == "PASS", "第 2 轮 86 PASS")
    check(state["scores"][1]["reviewers"] == 3, "合成记录 reviewers=3")

    print("== 阶段 9：收尾 ==")
    write(
        run,
        "final_report.md",
        {
            "schema_version": 1,
            "run": state["run_id"],
            "tier": "Medium",
            "iterations": 2,
            "trajectory": [
                {"iteration": 1, "total": 78, "verdict": "REVISE"},
                {"iteration": 2, "total": 86, "verdict": "PASS"},
            ],
            "outcome": "第 2 轮达到 PASS；证据链完整。",
        },
        "# 最终报告\n\n两轮迭代：78 REVISE → 86 PASS。\n",
    )
    result = lib.finish_run(run)
    state = state_of(run)
    check(state["finished"] is True, "finished=true")
    if HAS_MPL:
        check((run / "score_trend.png").exists() and (run / "score_trend.png").stat().st_size > 0, "score_trend.png 已生成")
    else:
        print("  [skip] 未安装 matplotlib，跳过 score_trend.png 检查（按文字产物验收）")
    check(Path(result["run_dir"]).exists(), "finish 返回 run_dir")
    check((run / "framework.mmd").read_text(encoding="utf-8").startswith("flowchart"), "framework.mmd 是 Mermaid flowchart")
    check("PASS" in (run / "PROGRESS.md").read_text(encoding="utf-8"), "PROGRESS.md 含迭代记录")

    print("== 阶段 10：CLI 入口与 exit 2 ==")
    cli_root = SELFTEST_DIR / "cli-runs"
    cli_root.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    def run_cli(*args: str) -> tuple[int, str, str]:
        # 沙箱下 Python 无法创建管道，故用临时文件承接 stdout/stderr。
        out_path = SELFTEST_DIR / "_cli_stdout.tmp"
        err_path = SELFTEST_DIR / "_cli_stderr.tmp"
        with open(out_path, "w", encoding="utf-8") as out, open(err_path, "w", encoding="utf-8") as err:
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / "orchestrator.py"), *args],
                stdout=out,
                stderr=err,
                stdin=subprocess.DEVNULL,
                cwd=str(SCRIPTS),
                env=env,
                timeout=180,
            )
        return proc.returncode, out_path.read_text(encoding="utf-8"), err_path.read_text(encoding="utf-8")

    rc, out, err = run_cli("init", "--cmd", "teamwork, N=1 CLI 跳步测试", "--root", str(cli_root), "--json")
    check(rc == 0, f"CLI init 成功（exit {rc}）：{err.strip()[:200]}")
    cli_run = json.loads(out)["run_dir"]
    rc, out, err = run_cli("advance", cli_run, "--json")
    check(rc == 0, "CLI advance INIT→CLASSIFY 成功")
    rc, out, err = run_cli("advance", cli_run, "--json")
    check(rc == 2, f"CLI 跳步 exit 2（实际 {rc}）")
    check("缺少产物" in err, "CLI 跳步提示缺少产物")
    rc, out, err = run_cli("status", cli_run, "--json")
    check(rc == 0 and json.loads(out)["phase"] == "CLASSIFY", "CLI status 正确")
    rc, out, err = run_cli("check", cli_run, "--json")
    check(rc == 2, "CLI check 缺产物时 exit 2")
    rc, out, err = run_cli("next", cli_run, "--json")
    check(rc == 0 and "classification" in json.loads(out)["outputs"][0], "CLI next 指向 classification")
    rc, out, err = run_cli("render", cli_run, "--json")
    check(rc == 0, f"CLI render 成功（exit {rc}）：{err.strip()[:200]}")
    rc, out, err = run_cli("reviewers", cli_run, "--count", "3", "--json")
    check(
        rc == 0 and json.loads(out).get("reviewers") == 3,
        f"CLI reviewers --count 3 成功（exit {rc}）：{err.strip()[:200]}",
    )

    print("== 阶段 11：命令格式与 N=? 自动轮数 ==")
    for text, expect_token in (
        ("teamwork, N=2 任务", "2"),
        ("teamwork,N=? 任务", "?"),
        ("teamwork，N=1 任务", "1"),
    ):
        token, rest = lib.parse_command(text)
        check(token == expect_token and rest == "任务", f"解析命令：{text}")
    for bad in ("N=2 任务", "teamwork N=2 任务", "teamwork, 2 任务"):
        try:
            lib.parse_command(bad)
            check(False, f"非法命令应报错：{bad}")
        except lib.TeamworkError:
            check(True, f"非法命令被拒绝：{bad}")

    auto_root = SELFTEST_DIR / "auto-runs"
    auto_root.mkdir(parents=True, exist_ok=True)
    auto = lib.create_run(auto_root, "teamwork, N=? 自动轮数测试")
    st = state_of(auto)
    check(st["n_mode"] == "auto" and st["n"] is None, "N=? 初始为 auto 且 n 未定")
    lib.advance_run(auto)
    write(
        auto,
        "00_intake/classification.md",
        {
            "schema_version": 1,
            "tier": "Medium",
            "tier_reason": "自动轮数测试",
            "signals": {
                "files": 3,
                "external": True,
                "verifiable": True,
                "parallel": True,
                "risk": "low",
                "user_demand": True,
            },
            "n_adjust": 1,
            "n_reason": "验收偏主观，多一轮打磨",
            "workers_planned": 3,
        },
        "# 分级\n\nMedium，自动轮数 +1。\n",
    )
    lib.advance_run(auto)
    st = state_of(auto)
    check(st["n"] == lib.TIER_DEFAULT_N["Medium"] + 1, f"自动 N=3（实际 {st['n']}）")
    check(st["tier"] == "Medium", "自动分级 Medium")

    print("== 阶段 12：L 级上限 8 与 S/M worker 复用 ==")
    check(
        lib.final_agent_mode("Small") == "main" and lib.final_agent_mode("Medium") == "main",
        "S/M 级 Final=主 Agent",
    )
    check(lib.final_agent_mode("Large") == "subagent", "L 级 Final=全新子 Agent")
    check(lib.TIER_RANGES["Large"] == (5, 7), "Large worker 范围 5–7（+Final Agent 共 8）")
    check(lib.MAX_WORKERS_FINAL_CAP == 8, "Worker+Final 合计上限 8")

    cap_root = SELFTEST_DIR / "cap-runs"
    cap_root.mkdir(parents=True, exist_ok=True)
    cap = lib.create_run(cap_root, "teamwork, N=1 L 级上限测试")
    fake_art = cap / "iterations" / "iter-01" / "workers" / "w01_artifacts" / "out.md"
    fake_art.parent.mkdir(parents=True, exist_ok=True)
    fake_art.write_text("x\n", encoding="utf-8")

    def dispatch_check(iteration: int, ids: list[str]) -> "lib.Check":
        path = cap / "01_plans" / f"dispatch-iter-{iteration:02d}.md"
        workers = [
            {
                "id": wid,
                "scope": "s",
                "deliverables": [lib.rel(cap, fake_art)],
                "acceptance": "ok",
            }
            for wid in ids
        ]
        lib.write_artifact(
            path,
            {"schema_version": 1, "iteration": iteration, "mode": "parallel", "workers": workers},
            "# 派发\n\n测试用最小派发。\n",
        )
        st = lib.load_state(cap)
        st["current_iter"] = iteration
        st["phase"] = "DISPATCH"
        chk = lib.Check(cap, st)
        lib.validate_dispatch(chk)
        return chk

    large_ids = [f"w{idx:02d}" for idx in range(1, 9)]
    st = lib.load_state(cap)
    st["tier"] = "Large"
    lib.save_state(cap, st)
    chk = dispatch_check(1, large_ids)
    check(any("5–7" in error for error in chk.errors), "Large 8 个 worker 被拒绝（上限 7）")
    chk = dispatch_check(1, large_ids[:7])
    check(not chk.errors, "Large 7 个 worker 通过（+Final=8）")

    st = lib.load_state(cap)
    st["tier"] = "Medium"
    st["workers"] = {"planned": 0, "ids": [], "registry": {"w01": 1, "w02": 1, "w03": 1}}
    lib.save_state(cap, st)
    chk = dispatch_check(2, ["w01", "w02", "w03"])
    check(not chk.warnings and not chk.errors, "Medium 复用全部 worker 无告警")
    chk = dispatch_check(2, ["w01", "w02", "w04"])
    check(any("建议复用" in warning for warning in chk.warnings), "Medium 新建 w04 触发复用告警")

    print("== 阶段 13：人数上限只按单个任务（run）计数，同一对话多任务互不占用 ==")
    multi_root = SELFTEST_DIR / "multi-task"
    multi_root.mkdir(parents=True, exist_ok=True)
    task_a = lib.create_run(multi_root, "teamwork, N=1 任务甲")
    task_b = lib.create_run(multi_root, "teamwork, N=1 任务乙")

    def dispatch_check_for(target: "Path", tier: str, iteration: int, ids: list[str]) -> "lib.Check":
        art = target / "iterations" / f"iter-{iteration:02d}" / "workers" / "w01_artifacts" / "out.md"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text("x\n", encoding="utf-8")
        workers = [
            {"id": wid, "scope": "s", "deliverables": [lib.rel(target, art)], "acceptance": "ok"}
            for wid in ids
        ]
        lib.write_artifact(
            target / "01_plans" / f"dispatch-iter-{iteration:02d}.md",
            {"schema_version": 1, "iteration": iteration, "mode": "parallel", "workers": workers},
            "# 派发\n\n测试用最小派发。\n",
        )
        st = lib.load_state(target)
        st["tier"] = tier
        st["current_iter"] = iteration
        st["phase"] = "DISPATCH"
        lib.save_state(target, st)
        chk = lib.Check(target, st)
        lib.validate_dispatch(chk)
        return chk

    ids6 = [f"w{idx:02d}" for idx in range(1, 7)]
    chk_a = dispatch_check_for(task_a, "Large", 1, ids6)
    check(not chk_a.errors, "任务甲：Large 6 worker 通过")
    chk_b = dispatch_check_for(task_b, "Large", 1, ids6)
    check(
        not chk_b.errors,
        "任务乙：同一对话里第二个任务也用 6 worker 通过（上限不跨任务累计）",
    )
    lib.advance_run(task_a)
    lib.advance_run(task_b)
    st_a, st_b = lib.load_state(task_a), lib.load_state(task_b)
    names_a = set(st_a["workers"].get("agents", {}).values())
    names_b = set(st_b["workers"].get("agents", {}).values())
    check(len(names_a) == 6 and len(names_b) == 6, "两个任务各 6 个物理 agent 名")
    check(not (names_a & names_b), "两任务的物理 agent 名互不重叠（同一对话多任务隔离）")
    check(
        all(name == lib.agent_name(st_a["run_id"], wid) for wid, name in st_a["workers"]["agents"].items()),
        "任务甲物理名 = agent_name(run_id, 逻辑 id)",
    )

    # 同一任务跨迭代累计：registry 已有 w01–w07，再派 w02–w08（新增 w08）必须拒绝
    st = lib.load_state(task_a)
    st["current_iter"] = 2
    st["phase"] = "DISPATCH"
    st["workers"] = {
        "planned": 6,
        "ids": ids6,
        "registry": {f"w{idx:02d}": 1 for idx in range(1, 8)},
        "agents": {},
    }
    lib.save_state(task_a, st)
    chk = dispatch_check_for(task_a, "Large", 2, [f"w{idx:02d}" for idx in range(2, 9)])
    check(any("累计 Worker 数不得超过 7" in e for e in chk.errors), "同一任务累计第 8 个 worker 被拒绝")
    check(any("单个任务" in e for e in chk.errors), "拒绝信息说明上限按单个任务计数")

    # build_next 暴露物理名与按任务计数信息
    st = lib.load_state(task_a)
    st["phase"] = "WORKERS"
    st["current_iter"] = 1
    st["workers"] = {
        "planned": 6,
        "ids": ids6,
        "registry": {wid: 1 for wid in ids6},
        "agents": {wid: lib.agent_name(st["run_id"], wid) for wid in ids6},
        "reused": [],
        "new_ids": ids6,
    }
    lib.save_state(task_a, st)
    nxt = lib.build_next(task_a)
    check(
        sorted(nxt["subagents"]["agents"]) == ids6,
        "WORKERS 的 next 输出含每个 worker 的 agent_name",
    )
    check(
        all(
            item["agent_name"] == lib.agent_name(st["run_id"], item["id"])
            for item in nxt["subagents"]["workers"]
        ),
        "worker 卡片的 agent_name 与 agent_name(run_id, id) 一致",
    )

    print()
    if FAILURES:
        print(f"自测失败：{len(FAILURES)} 项")
        for item in FAILURES:
            print(f" - {item}")
        return 1
    print(f"自测全部通过。run 目录：{run}")
    if HAS_MPL:
        print(f"框架图：{run / 'framework.png'}（另见 framework.mmd、PROGRESS.md）")
        print(f"分数轨迹图：{run / 'score_trend.png'}")
    else:
        print(f"框架图（文字版）：{run / 'framework.mmd'}、{run / 'PROGRESS.md'}")
        print("未安装 matplotlib：跳过 PNG（安装后自动生成 framework.png / score_trend.png）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
