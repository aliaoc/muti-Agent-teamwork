"""自测：在 $TEAMWORK_RUNS_ROOT/_selftest 下造完整 run，覆盖 v2.0 的全部门禁。

阶段 1–13   状态机主流程（REWORK、双评审、多任务计数、CLI）
阶段 14     引用核验（结构锁/算术锁/清单锁/离线降级/虚构门禁）
阶段 15     COACH（结构锁/事实锁/切片锁/命中率/升级到 PLAN）
阶段 16     末轮建议矩阵、finish 留痕门禁、extend 闭环
阶段 17     权重跟随 rubric、策略变化上限、环外提案门槛
阶段 18     DREAM→COACH 迁移兼容
阶段 19     经验库落库、指标、教训蒸馏

运行：python scripts/selftest.py（需 PyYAML；matplotlib 可选）
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
import rsi_store  # noqa: E402

SELFTEST_DIR = Path(
    os.environ.get("TEAMWORK_RUNS_ROOT", str(lib.DEFAULT_RUNS_ROOT))
) / "_selftest"
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


def expect_reject(run: Path, needle: str, label: str) -> None:
    try:
        lib.advance_run(run)
        check(False, f"{label}：应拒绝推进")
    except lib.ValidationFailed as exc:
        joined = "\n".join(exc.errors)
        check(needle in joined, f"{label}：拒绝原因含「{needle}」")
        if needle not in joined:
            print(f"      实际：{joined[:300]}")


# --------------------------------------------------------------------------- #
# 造产物
# --------------------------------------------------------------------------- #
def mk_classification(run: Path, tier: str = "Medium", workers: int = 3) -> None:
    write(
        run,
        "00_intake/classification.md",
        {
            "schema_version": 1,
            "tier": tier,
            "tier_reason": "涉及多个独立子任务，需要外部检索与汇总，有可验证产物",
            "signals": {
                "files": 3,
                "external": True,
                "verifiable": True,
                "parallel": True,
                "risk": "medium" if tier == "Large" else "low",
                "user_demand": True,
            },
            "n_adjust": 0,
            "workers_planned": workers,
            "user_confirmed": True,
        },
        f"# 分级\n\n{tier}：{workers} 个并行子任务。\n",
    )


def mk_plan(run: Path, iteration: int, tier: str = "Medium", workers: int = 3,
            addresses: list[str] | None = None) -> None:
    breakdown = [
        {"desc": f"子任务 {idx}", "assignee": f"w{idx:02d}"} for idx in range(1, workers + 1)
    ]
    fm = {
        "schema_version": 1,
        "iteration": iteration,
        "tier": tier,
        "objective": f"第 {iteration} 轮：整理可行方案并给出证据",
        "breakdown": breakdown,
        "accepted_criteria": ["结论有证据链", "风险已标注", "产物文件存在"],
        "risks": ["证据来源可能不足"],
        "worker_count": workers,
        "alternatives": ["方案 A：单 agent", "方案 B：多 worker 并行"] if tier == "Large" else [],
    }
    if addresses:
        fm["addresses_errors"] = [
            {"class": klass, "mitigation": "计划层单设取证 worker，并把验收提前到取证后"}
            for klass in addresses
        ]
    write(
        run,
        f"01_plans/plan-iter-{iteration:02d}.md",
        fm,
        f"# 计划（第 {iteration} 轮）\n\n" + "\n".join(f"{i}. {b['desc']}" for i, b in enumerate(breakdown, 1)) + "\n",
    )


def mk_dispatch(
    run: Path,
    iteration: int,
    workers: int = 3,
    coach_items: dict[str, list[dict]] | None = None,
    applied: list[str] | None = None,
    deferred: list[dict] | None = None,
    lessons: list[str] | None = None,
) -> list[str]:
    rels = []
    entries = []
    for idx in range(1, workers + 1):
        wid = f"w{idx:02d}"
        artifact = run / "iterations" / f"iter-{iteration:02d}" / "workers" / f"{wid}_artifacts" / "out.md"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(f"# {wid} 产物（第 {iteration} 轮）\n\n内容占位。\n", encoding="utf-8")
        rels.append(lib.rel(run, artifact))
        item = {
            "id": wid,
            "scope": f"子任务 {idx}",
            "deliverables": [lib.rel(run, artifact)],
            "acceptance": "产物存在且有正文",
        }
        if coach_items and coach_items.get(wid):
            item["coach_items"] = coach_items[wid]
        entries.append(item)
    fm = {
        "schema_version": 1,
        "iteration": iteration,
        "mode": "parallel",
        "workers": entries,
    }
    if applied is not None:
        fm["coach_applied"] = applied
    if deferred is not None:
        fm["coach_deferred"] = deferred
    if lessons:
        fm["lessons_applied"] = lessons
    write(
        run,
        f"01_plans/dispatch-iter-{iteration:02d}.md",
        fm,
        f"# 派发（第 {iteration} 轮）\n\n并行执行，各自写自己的目录。\n",
    )
    return rels


SOURCE_A = {
    "id": "S01",
    "claim_ref": "coverage[0]",
    "url": "https://arxiv.org/abs/2309.06180",
    "title": "Efficient Memory Management for LLM Serving with PagedAttention",
    "publisher": "arXiv",
    "published_at": "2023-09-12",
    "quote": "near-zero waste in KV cache memory",
    "locator": "Abstract",
    "contributed_by": "w01",
}
SOURCE_B = {
    "id": "S02",
    "claim_ref": "coverage[1]",
    "url": "https://example.org/report-2024",
    "title": "2024 推理性能报告",
    "publisher": "Example",
    "published_at": "2024-06-01",
    "quote": "throughput improved by 2.1x",
    "locator": "§3.2",
    "contributed_by": "w02",
}


def mk_workers(
    run: Path,
    iteration: int,
    dispatch_rels: list[str],
    update_w01: bool = False,
    with_sources: bool = False,
) -> None:
    for idx, rel in enumerate(dispatch_rels, 1):
        wid = f"w{idx:02d}"
        version = "（重做版）" if update_w01 and wid == "w01" else ""
        claim = {
            "text": f"{wid} 在第 {iteration} 轮完成了子任务 {idx}{version}",
            "evidence": [rel],
        }
        if with_sources:
            claim["sources"] = [dict(SOURCE_A if wid == "w01" else SOURCE_B, contributed_by=wid)]
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
                "claims": [claim],
                "open_questions": [],
                "confidence": "high",
            },
            f"# {wid} 结果\n\n子任务 {idx} 完成{version}。\n",
        )


def mk_final(
    run: Path, iteration: int, deliverable: str, with_sources: bool = False
) -> None:
    fm = {
        "schema_version": 1,
        "iteration": iteration,
        "summary": f"第 {iteration} 轮汇总：结论与证据已整理",
        "deliverables": [{"path": deliverable, "sha256": sha(run / deliverable)}],
        "coverage": [
            {"requirement": "结论有证据链", "where": deliverable, "status": "covered"},
            {"requirement": "风险已标注", "where": "run_report.md", "status": "covered"},
        ],
        "unresolved": [],
    }
    if with_sources:
        fm["sources"] = [dict(SOURCE_A), dict(SOURCE_B)]
    write(
        run,
        f"iterations/iter-{iteration:02d}/final_result.md",
        fm,
        f"# 最终结果（第 {iteration} 轮）\n\n结论：方案可行。证据见 {deliverable}。\n",
    )
    write(
        run,
        f"iterations/iter-{iteration:02d}/run_report.md",
        {
            "schema_version": 1,
            "iteration": iteration,
            "tier": "Medium",
            "workers": len(list((run / "iterations" / f"iter-{iteration:02d}" / "workers").glob("w*_result.md"))),
            "highlights": [f"第 {iteration} 轮 worker 全部完成"],
            "issues": [],
            "next_suggestions": [],
        },
        f"# 运行报告（第 {iteration} 轮）\n\n并行完成，无阻塞。\n",
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
    if total >= lib.PASS_THRESHOLD:
        return "PASS"
    if total >= lib.REVISE_THRESHOLD:
        return "REVISE"
    return "FAIL"


def mk_review(
    run: Path,
    iteration: int,
    reviewer: str,
    total: int,
    *,
    role: str = "general",
    errors: list[dict] | None = None,
    gates: list[str] | None = None,
    audit: dict | None = None,
    weights: dict | None = None,
    evidence: list[str] | None = None,
) -> None:
    packet_rel = f"iterations/iter-{iteration:02d}/review_packet.md"
    weights = weights or lib.RUBRIC_V0["weights"]
    artifacts = [
        f"iterations/iter-{iteration:02d}/workers/w01_artifacts/out.md",
        f"iterations/iter-{iteration:02d}/workers/w02_artifacts/out.md",
    ]
    evidence = evidence or [artifacts[0], artifacts[1]]
    dims = [
        {
            "name": name,
            "weight": weight,
            "score": total,
            "evidence": list(evidence),
        }
        for name, weight in weights.items()
    ]
    fm = {
        "schema_version": 1,
        "reviewer": reviewer,
        "role": role,
        "iteration": iteration,
        "rubric_version": state_of(run)["review"].get("policy_version", "v0"),
        "inputs_read": [packet_rel, *artifacts],
        "independence_attestation": True,
        "dimensions": dims,
        "gates_triggered": gates or [],
        "errors": errors or [],
        "optimizations": [{"suggestion": "证据引用再具体一些", "expected_gain": "+3"}],
        "total": total,
        "verdict": verdict_for(total),
    }
    if role == "citation_audit":
        fm["citation_audit"] = audit or {
            "mode": "online",
            "coverage": {
                "total": 2,
                "audited": 2,
                "verified": 2,
                "unverifiable": 0,
                "misattributed": 0,
                "fabricated": 0,
            },
            "items": [
                {"id": "S01", "verdict": "verified", "method": "fetch", "locator": "Abstract",
                 "checked_at": lib.now_iso(), "note": "原文摘要确有该表述"},
                {"id": "S02", "verdict": "verified", "method": "fetch", "locator": "§3.2",
                 "checked_at": lib.now_iso(), "note": "数字一致"},
            ],
        }
    path = run / "iterations" / f"iter-{iteration:02d}" / f"review_report_{reviewer}.md"
    write(
        run,
        lib.rel(run, path),
        fm,
        f"# 审核报告 {reviewer}（第 {iteration} 轮）\n\n总分 {total}，结论 {verdict_for(total)}。\n",
    )


def mk_coach(
    run: Path,
    iteration: int,
    *,
    verdict: str,
    score: int,
    items: list[dict] | None = None,
    taxonomy: list[dict] | None = None,
    advisory_input: dict | None = None,
    escalations: list[dict] | None = None,
) -> None:
    fm = {
        "schema_version": 1,
        "iteration": iteration,
        "tier": state_of(run).get("tier"),
        "verdict_in": verdict,
        "score_in": score,
        "error_taxonomy": taxonomy
        if taxonomy is not None
        else [{"class": "evidence_gap", "count": 2, "attributed_to": ["w01", "plan.step-2"]}],
        "items": items or [],
        "dream_hints": ["若 evidence_gap 反复出现，离线评估是否加'无源结论'检查项"],
        "escalations": escalations or [],
    }
    if advisory_input is not None:
        fm["advisory_input"] = advisory_input
    write(
        run,
        f"iterations/iter-{iteration:02d}/rsi_report.md",
        fm,
        f"# RSI 教练报告（第 {iteration} 轮）\n\n"
        f"本轮 {score} 分 {verdict}。\n\n"
        "教练只读本轮评审与产物，不评分、不改产物、不派活。\n",
    )


def advance(run: Path, expected_to: str) -> None:
    result = lib.advance_run(run)
    check(result["to"] == expected_to, f"推进到 {expected_to}（实际 {result['to']}）")


# --------------------------------------------------------------------------- #
def main() -> int:  # noqa: C901 - 自测按阶段线性展开，便于定位
    print("== 清理旧的 selftest 目录 ==")
    if SELFTEST_DIR.exists():
        shutil.rmtree(SELFTEST_DIR)
    SELFTEST_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["TEAMWORK_EXPERIENCE_HOME"] = str(SELFTEST_DIR / "experience")

    print("== 阶段 1：创建 run（N=3，显式）==")
    run = lib.create_run(SELFTEST_DIR, "teamwork, N=3 自测：整理可行方案并给出证据")
    expect_phase(run, "INIT")
    state = state_of(run)
    check(state["n_mode"] == "explicit" and state["explicit_n"] == 3, "N=3 显式模式")
    check((run / "framework.mmd").exists(), "framework.mmd 已生成")
    check((run / "PROGRESS.md").exists(), "PROGRESS.md 已生成")
    check((run / "review_policy/v0.md").exists(), "review_policy/v0.md 已生成")
    if HAS_MPL:
        check((run / "framework.png").exists(), "framework.png 已生成")
    else:
        print("  [skip] 未安装 matplotlib，跳过 PNG 断言")

    advance(run, "CLASSIFY")
    expect_reject(run, "classification", "缺 classification 时")

    print("== 阶段 2：分级（Medium）==")
    mk_classification(run, "Medium", 3)
    advance(run, "PLAN")
    state = state_of(run)
    check(state["tier"] == "Medium" and state["n"] == 3, "等级 Medium / N=3")
    check(state["review"]["reviewers"] == 1, "Medium 不自动加评审")

    print("== 阶段 3：第 1 轮 计划 → 派发 → 执行 → 汇总 ==")
    mk_plan(run, 1, "Medium", 3)
    advance(run, "DISPATCH")
    rels1 = mk_dispatch(run, 1, 3)
    advance(run, "WORKERS")
    mk_workers(run, 1, rels1)
    advance(run, "FINAL")
    mk_final(run, 1, rels1[0])
    lib.set_dual_review(run, True)
    check(state_of(run)["review"]["reviewers"] == 2, "双评审已开启（A/B 均为 general）")
    check(
        state_of(run)["review"]["roles"] == {"A": "general", "B": "general"},
        "Medium 双评审角色都是 general",
    )
    lib.make_review_packet(run, state_of(run))
    advance(run, "GATE")

    print("== 阶段 4：GATE 打回 → 重做 → PASS ==")
    mk_gate(run, 1, "REWORK", ["w01"], "w01 的证据引用不完整")
    advance(run, "WORKERS")
    check(state_of(run)["rework_count"] == 1, "rework_count=1")
    mk_workers(run, 1, rels1, update_w01=True)
    advance(run, "FINAL")
    lib.make_review_packet(run, state_of(run))
    advance(run, "GATE")
    mk_gate(run, 1, "PASS", [], "重做后通过")
    advance(run, "REVIEW")

    print("== 阶段 5：第 1 轮审核（78 REVISE）==")
    errors1 = [
        {"id": "E1", "class": "evidence_gap", "located": "final_result.md#L12", "recurred_from": None},
        {"id": "E2", "class": "incomplete_coverage", "located": "final_result.md#L20", "recurred_from": None},
    ]
    mk_review(run, 1, "A", 78, errors=errors1)
    expect_reject(run, "review_report_B", "双评审只有 A 时")
    mk_review(run, 1, "B", 78, errors=errors1)
    advance(run, "COACH")
    state = state_of(run)
    check(state["scores"][0]["total"] == 78 and state["scores"][0]["verdict"] == "REVISE", "合成 78 REVISE")
    check((run / "iterations/iter-01/review_scores.md").exists(), "review_scores.md 已生成")
    score_fm, _ = lib.read_artifact(run / "iterations/iter-01/review_scores.md")
    check("merged_dimensions" in score_fm, "review_scores 记录合并维度均分")

    print("== 阶段 6：COACH 结构与事实锁 ==")
    expect_reject(run, "rsi_report.md", "缺教练报告时")
    good_items = [
        {
            "id": "C1",
            "from_error": ["A:E1", "B:E1"],
            "root_cause": "拆分把取证和写作放同一个 worker，取证被写作挤掉",
            "action": "w01 只做检索与取证，先产出 sources.yaml",
            "applies_to": ["w01"],
            "verification": "w01_artifacts/sources.yaml 存在且每条含 url+locator+quote",
            "priority": "must_fix",
        },
        {
            "id": "C2",
            "from_error": ["A:E2", "B:E2"],
            "root_cause": "并行派发未约定产物格式，汇总字段对不上",
            "action": "所有 worker 产物统一 frontmatter：claim/evidence/confidence",
            "applies_to": ["all"],
            "verification": "下轮所有 result.md 的 frontmatter 字段一致",
            "priority": "should_fix",
        },
    ]
    mk_coach(
        run, 1, verdict="REVISE", score=78,
        items=[{**good_items[0], "from_error": ["E9"]}],
    )
    expect_reject(run, "指向不存在的 error", "from_error 指向不存在的 error 时")
    mk_coach(
        run, 1, verdict="REVISE", score=78,
        items=[{**good_items[0], "action": "参考 https://evil.example.com 的做法"}],
    )
    expect_reject(run, "评审包之外的 URL", "教练引入新事实时")
    mk_coach(run, 1, verdict="REVISE", score=78, items=good_items)
    advance(run, "PLAN")
    state = state_of(run)
    check(state["current_iter"] == 2, "进入第 2 轮")
    check(state["coach"]["entries"][0]["items"] == ["C1", "C2"], "教练条目已入账")

    print("== 阶段 7：DISPATCH 切片锁 ==")
    mk_plan(run, 2, "Medium", 3)
    advance(run, "DISPATCH")
    # 漏下发 C2
    mk_dispatch(run, 2, 3, coach_items={"w01": [{"id": "C1", "action": "先取证"}]},
                applied=["C1", "C2"], deferred=[])
    expect_reject(run, "coach_items 里没有", "漏下发教练条目时")
    # 越权下发：C1 只给 w01，却塞给 w02
    mk_dispatch(
        run, 2, 3,
        coach_items={"w01": [{"id": "C1", "action": "先取证"}],
                     "w02": [{"id": "C1", "action": "先取证"}, {"id": "C2", "action": "统一格式"}],
                     "w03": [{"id": "C2", "action": "统一格式"}]},
        applied=["C1", "C2"], deferred=[],
    )
    expect_reject(run, "越权下发", "把 C1 下发给 w02 时")
    # 串到别人产物
    mk_dispatch(
        run, 2, 3,
        coach_items={"w01": [{"id": "C1", "action": "参考 w02_artifacts/out.md"}, {"id": "C2", "action": "统一格式"}],
                     "w02": [{"id": "C2", "action": "统一格式"}],
                     "w03": [{"id": "C2", "action": "统一格式"}]},
        applied=["C1", "C2"], deferred=[],
    )
    expect_reject(run, "破坏隔离", "w01 的条目提到 w02 产物时")
    # 合法切片
    mk_dispatch(
        run, 2, 3,
        coach_items={"w01": [{"id": "C1", "action": "先取证"}, {"id": "C2", "action": "统一格式"}],
                     "w02": [{"id": "C2", "action": "统一格式"}],
                     "w03": [{"id": "C2", "action": "统一格式"}]},
        applied=["C1", "C2"], deferred=[],
    )
    advance(run, "WORKERS")
    check(True, "合法切片通过")

    print("== 阶段 8：第 2 轮 78 REVISE（老问题复发，考教练命中率）==")
    mk_workers(run, 2, rels1)
    advance(run, "FINAL")
    mk_final(run, 2, rels1[0])
    lib.make_review_packet(run, state_of(run))
    advance(run, "GATE")
    mk_gate(run, 2, "PASS", [], "第 2 轮通过")
    advance(run, "REVIEW")
    recurred = [
        {"id": "E1", "class": "evidence_gap", "located": "final_result.md#L12", "recurred_from": "A:E1"},
        {"id": "E2", "class": "incomplete_coverage", "located": "final_result.md#L20", "recurred_from": None},
    ]
    mk_review(run, 2, "A", 78, errors=recurred)
    mk_review(
        run, 2, "B", 78,
        errors=[{**recurred[0], "recurred_from": "B:E1"}, {**recurred[1]}],
    )
    advance(run, "COACH")
    check(True, "第 2 轮进入 COACH")

    print("== 阶段 9：命中率、卡住类别、升级到 PLAN ==")
    mk_coach(
        run, 2, verdict="REVISE", score=78,
        items=[{
            "id": "C1",
            "from_error": ["A:E1", "B:E1"],
            "root_cause": "仍是取证与写作同人",
            "action": "把取证独立成 w01 的唯一职责",
            "applies_to": ["w01"],
            "verification": "sources.yaml 先于结论产出",
            "priority": "must_fix",
        }],
        escalations=[{"class": "evidence_gap", "reason": "连续两轮复发，计划层必须改拆分"}],
    )
    advance(run, "PLAN")
    state = state_of(run)
    entry = state["coach"]["entries"][1]
    check(entry["hit_rate"] == 0.5, f"命中率 1-2/4=0.5（实际 {entry['hit_rate']}）")
    check("evidence_gap" in state["coach"]["stuck_classes"], "evidence_gap 被标记为卡住")
    check(state["current_iter"] == 3, "进入第 3 轮")

    print("== 阶段 10：计划层必须正面处理卡住的类别 ==")
    mk_plan(run, 3, "Medium", 3)
    expect_reject(run, "addresses_errors", "计划缺 addresses_errors 时")
    mk_plan(run, 3, "Medium", 3, addresses=["evidence_gap"])
    advance(run, "DISPATCH")

    print("== 阶段 11：第 3 轮 PASS（C4 证据密度）==")
    mk_dispatch(
        run, 3, 3,
        coach_items={"w01": [{"id": "C1", "action": "先取证"}],
                     "w02": [], "w03": []},
        applied=["C1"], deferred=[],
    )
    advance(run, "WORKERS")
    mk_workers(run, 3, rels1)
    advance(run, "FINAL")
    mk_final(run, 3, rels1[0])
    lib.make_review_packet(run, state_of(run))
    advance(run, "GATE")
    mk_gate(run, 3, "PASS", [], "第 3 轮通过")
    advance(run, "REVIEW")
    # C4：PASS 但证据全指向 packet 自身 → 必须拒绝
    mk_review(run, 3, "A", 86, evidence=[f"iterations/iter-03/review_packet.md"] * 2)
    mk_review(run, 3, "B", 86, evidence=[f"iterations/iter-03/review_packet.md"] * 2)
    expect_reject(run, "自指漏洞", "PASS 证据全指向 packet 时")
    # C4：PASS 但有 errors → 拒绝
    mk_review(run, 3, "A", 86, errors=[{"id": "E1", "class": "evidence_gap", "located": "x#1"}])
    expect_reject(run, "PASS 报告不允许有 errors", "PASS 仍带 errors 时")
    mk_review(run, 3, "A", 86)
    mk_review(run, 3, "B", 86)
    advance(run, "COACH")
    state = state_of(run)
    check(state["scores"][2]["total"] == 86 and state["scores"][2]["verdict"] == "PASS", "第 3 轮 86 PASS")

    print("== 阶段 12：末轮建议由代码计算 ==")
    mk_coach(run, 3, verdict="PASS", score=86, items=[], taxonomy=[])
    expect_reject(run, "advisory_input", "末轮缺 advisory_input 时")
    mk_coach(
        run, 3, verdict="PASS", score=86, items=[], taxonomy=[],
        escalations=[{"class": "evidence_gap", "reason": "前两轮复发，最终报告需单列该风险"}],
        advisory_input={
            "estimated_gain_next_round": 6,
            "remaining_gaps": [],
            "diminishing": False,
            "rationale": "已是 86 分且证据维度 86，继续迭代收益低于噪声下限。",
        },
    )
    advance(run, "DONE")
    state = state_of(run)
    advisory = state["advisory"]
    check(advisory["score"] == 86 and advisory["verdict"] == "PASS", "建议记录 86 PASS")
    check(advisory["delta"] == 8, f"delta=8（实际 {advisory['delta']}）")
    check(advisory["recommendation"] == "stop", "PASS 且无短板 → stop")
    check((run / "iterations/iter-03/iteration_advisory.md").exists(), "iteration_advisory.md 已生成")

    print("== 阶段 13：advisory 不可手改 ==")
    adv_path = run / "iterations/iter-03/iteration_advisory.md"
    fm, body = lib.read_artifact(adv_path)
    tampered = {**fm, "recommended_rounds": 3}
    lib.write_artifact(adv_path, tampered, body)
    temp = lib.Check(run, state_of(run))
    lib.validate_advisory(temp)
    check(any("脚本计算不一致" in e for e in temp.errors), "手改建议数值被拒绝")
    lib.write_artifact(adv_path, fm, body)
    temp = lib.Check(run, state_of(run))
    lib.validate_advisory(temp)
    check(not temp.errors, "恢复后校验通过")

    print("== 阶段 14：收尾与经验库落库 ==")
    write(
        run,
        "final_report.md",
        {
            "schema_version": 1,
            "run": state["run_id"],
            "tier": "Medium",
            "iterations": 3,
            "trajectory": [
                {"iteration": 1, "total": 78, "verdict": "REVISE"},
                {"iteration": 2, "total": 78, "verdict": "REVISE"},
                {"iteration": 3, "total": 86, "verdict": "PASS"},
            ],
            "outcome": "第 3 轮达到 PASS；教练条目把取证独立成 w01 职责后生效。",
        },
        "# 最终报告\n\n78 → 78 → 86 PASS。\n",
    )
    result = lib.finish_run(run)
    check(state_of(run)["finished"] is True, "finished=true")
    check(isinstance(result.get("experience"), dict), "finish 返回经验库结果")
    check(
        (SELFTEST_DIR / "experience" / "runs" / f"{state['run_id']}.json").exists(),
        "经验库已落库 run 记录",
    )
    if HAS_MPL:
        check((run / "score_trend.png").exists(), "score_trend.png 已生成")
    check((run / "framework.mmd").read_text(encoding="utf-8").startswith("flowchart"), "framework.mmd 是 Mermaid")
    check("PASS" in (run / "PROGRESS.md").read_text(encoding="utf-8"), "PROGRESS.md 含迭代记录")

    print("== 阶段 15：建议规则矩阵 ==")
    base_state = {
        "current_iter": 2,
        "n": 2,
        "n_mode": "explicit",
        "review": {"policy_version": "v0"},
        "scores": [],
    }
    payload = {"advisory_input": {"estimated_gain_next_round": 6, "rationale": "规则矩阵测试"}}

    def advise(pairs: list[tuple[int, str]], weakest: int = 86) -> dict:
        scores = [
            {
                "iteration": idx + 1,
                "total": total,
                "verdict": verdict,
                "dimensions": {name: weakest for name in lib.RUBRIC_V0["weights"]},
            }
            for idx, (total, verdict) in enumerate(pairs)
        ]
        st = {**base_state, "scores": scores, "current_iter": len(scores)}
        return lib.compute_advisory(run, st, payload)

    cases = [
        ([(88, "PASS")], 88, "stop", 0, "首轮达标"),
        ([(84, "REVISE"), (86, "PASS")], 86, "stop", 0, "达标但提升微弱"),
        ([(81, "REVISE"), (87, "PASS")], 70, "continue", 1, "达标但证据薄弱"),
        ([(78, "REVISE"), (82, "REVISE")], 68, "continue", 1, "差一点点"),
        ([(63, "REVISE"), (68, "REVISE")], 60, "continue", 2, "差得远"),
        ([(60, "FAIL"), (61, "FAIL")], 55, "continue", 2, "触底"),
        ([(76, "REVISE"), (76, "REVISE")], 70, "stop", 0, "连续停滞"),
    ]
    for scores, weakest, rec, rounds, label in cases:
        got = advise(scores, weakest)
        check(
            got["recommendation"] == rec and got["recommended_rounds"] == rounds,
            f"{label}：{rec}/{rounds}（实际 {got['recommendation']}/{got['recommended_rounds']}）",
        )

    print("== 阶段 16：finish 留痕门禁与 extend 闭环 ==")
    ext_root = SELFTEST_DIR / "extend-runs"
    ext_root.mkdir(parents=True, exist_ok=True)
    ext = lib.create_run(ext_root, "teamwork, N=1 续跑测试")
    lib.advance_run(ext)
    mk_classification(ext, "Medium", 3)
    lib.advance_run(ext)
    mk_plan(ext, 1, "Medium", 3)
    lib.advance_run(ext)
    ext_rels = mk_dispatch(ext, 1, 3)
    lib.advance_run(ext)
    mk_workers(ext, 1, ext_rels)
    lib.advance_run(ext)
    mk_final(ext, 1, ext_rels[0])
    lib.make_review_packet(ext, state_of(ext))
    lib.advance_run(ext)
    mk_gate(ext, 1, "PASS", [], "通过")
    lib.advance_run(ext)
    mk_review(ext, 1, "A", 82,
              errors=[{"id": "E1", "class": "evidence_gap", "located": "final_result.md#L9"}])
    lib.advance_run(ext)  # → COACH
    mk_coach(ext, 1, verdict="REVISE", score=82,
             items=[],
             advisory_input={"estimated_gain_next_round": 6, "remaining_gaps": ["§3 无源"],
                             "diminishing": False,
                             "rationale": "差距 3 分，历史上单轮最大提升 6 分，一轮可达 85。"})
    lib.advance_run(ext)  # → DONE
    ext_advisory = state_of(ext)["advisory"]
    check(
        ext_advisory["recommendation"] == "continue" and ext_advisory["recommended_rounds"] == 1,
        f"82 分建议再迭代 1 轮（实际 {ext_advisory['recommendation']}/{ext_advisory['recommended_rounds']}）",
    )
    write(
        ext, "final_report.md",
        {
            "schema_version": 1,
            "run": state_of(ext)["run_id"],
            "tier": "Medium",
            "iterations": 1,
            "trajectory": [{"iteration": 1, "total": 82, "verdict": "REVISE"}],
            "outcome": "测试续跑",
        },
        "# 最终报告\n\n82 REVISE。\n",
    )
    try:
        lib.finish_run(ext)
        check(False, "建议续跑但没记录用户决定时应拒绝收尾")
    except lib.ValidationFailed as exc:
        check(any("advisory_response" in e for e in exc.errors), "finish 要求 advisory_response")
    try:
        lib.extend_run(ext, 1)
        check(False, "final_report 已存在时 extend 应要求 --force")
    except lib.TeamworkError:
        check(True, "extend 未加 --force 被拒绝")
    try:
        lib.extend_run(ext, 4, force=True)
        check(False, "extend 超过 3 轮应被拒绝")
    except lib.TeamworkError:
        check(True, "extend --rounds 4 被拒绝")
    lib.extend_run(ext, 1, reason="用户接受建议", force=True)
    ext_state = state_of(ext)
    check(ext_state["current_iter"] == 2 and ext_state["n"] == 2, "extend 后 iter=2 / n=2")
    check(ext_state["phase"] == "PLAN", "extend 后回到 PLAN")
    check(ext_state["advisory"] is None, "extend 清空旧建议，等新一轮重算")
    check((ext / "final_report.iter-01.md").exists(), "旧 final_report 已归档（append-only）")

    print("== 阶段 17：C1 权重跟随 rubric ==")
    pol_root = SELFTEST_DIR / "policy-runs"
    pol_root.mkdir(parents=True, exist_ok=True)
    pol = lib.create_run(pol_root, "teamwork, N=1 权重跟随测试")
    art = pol / "iterations/iter-01/workers/w01_artifacts/out.md"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text("x\n", encoding="utf-8")
    v1_weights = dict(lib.RUBRIC_V0["weights"])
    v1_weights["evidence"] = 30
    v1_weights["cost"] = 0
    lib.write_artifact(
        lib.policy_path(pol, "v1"),
        {
            "schema_version": 1,
            "version": "v1",
            "weights": v1_weights,
            "gates": list(lib.RUBRIC_V0["gates"]),
            "noise_floor": 5,
            "max_edits_per_iteration": 3,
        },
        "# 策略 v1\n\n证据 30 / 成本 0。\n",
    )
    st = lib.load_state(pol)
    st["review"]["policy_version"] = "v1"
    st["review"]["reviewers"] = 1
    lib.save_state(pol, st)
    dims_scores = {
        "correctness": 60, "completeness": 80, "evidence": 100,
        "robustness": 80, "maintainability": 80, "cost": 80,
    }
    dims = [
        {"name": name, "weight": v1_weights[name], "score": score,
         "evidence": [lib.rel(pol, art), lib.rel(pol, art)]}
        for name, score in dims_scores.items()
    ]
    total_v1 = int(round(sum(dims_scores[n] * v1_weights[n] / 100 for n in v1_weights)))
    report = pol / "iterations/iter-01/review_report_A.md"
    lib.write_artifact(
        report,
        {
            "schema_version": 1, "reviewer": "A", "role": "general", "iteration": 1,
            "rubric_version": "v1", "inputs_read": [lib.rel(pol, art)],
            "independence_attestation": True, "dimensions": dims,
            "gates_triggered": [], "errors": [], "optimizations": [],
            "total": total_v1, "verdict": verdict_for(total_v1),
        },
        "# 审核 A\n\n按 v1 打分。\n",
    )
    chk = lib.Check(pol, st)
    packet_fm = {"citations": [], "citation_policy": {"required": False}}
    lib.validate_review_report(chk, report, "A", lib.load_rubric(pol, "v1"), "v1", packet_fm, "general")
    check(not chk.errors, f"按 v1 权重的报告通过（total={total_v1}）")
    chk = lib.Check(pol, st)
    lib.validate_review_report(chk, report, "A", lib.RUBRIC_V0, "v0", packet_fm, "general")
    check(any("weight 必须是" in e for e in chk.errors), "按 v0 权重校验同一报告会被拒绝（C1 已修）")
    bad_policy = {
        "schema_version": 1, "version": "v2",
        "weights": {**lib.RUBRIC_V0["weights"], "evidence": 35},
        "gates": list(lib.RUBRIC_V0["gates"]), "noise_floor": 5,
        "max_edits_per_iteration": 3,
    }
    lib.write_artifact(lib.policy_path(pol, "v2"), bad_policy, "# v2\n")
    chk = lib.Check(pol, st)
    lib.validate_policy(chk, "v2")
    check(any("±10" in e for e in chk.errors), "单维权重变化 >±10 被拒绝")

    print("== 阶段 18：环外提案门槛（C2）==")
    def proposal(
        delta: float = 6.0,
        tasks: int = 2,
        edits: int = 2,
        promote: bool = True,
        weight_set: dict | None = None,
    ) -> dict:
        weights = dict(weight_set or lib.RUBRIC_V0["weights"])
        if weight_set is None:
            weights["evidence"] += 5
            weights["cost"] -= 5
        return {
            "schema_version": 1,
            "proposal": "v9",
            "policy_before": "v0",
            "noise_floor": 5,
            "max_edits_per_iteration": 3,
            "sample": {"runs": 4, "tasks": tasks, "train": 3, "validation": 1},
            "baseline": {"all": 74.0, "train": 74.0, "validation": 74.0},
            "candidates": [{
                "id": "c1",
                "edits": edits,
                "weights": weights,
                "world_scores": [
                    {"run_id": "r1", "iteration": 1, "score": 74 + delta},
                    {"run_id": "r1", "iteration": 2, "score": 74 + delta},
                ],
                "replay_score": 74 + delta,
                "validation_score": 74 + delta,
                "validation_delta": delta,
                "change": "evidence +5 / cost -5",
            }],
            "decision": "promote" if promote else "keep",
            "policy_after": "v9" if promote else "v0",
            "reason": "测试",
        }
    ok, problems = rsi_store.validate_proposal(proposal())
    check(ok, f"合法提案通过（{problems}）")
    ok, problems = rsi_store.validate_proposal(proposal(delta=3.0))
    check(any("噪声下限" in p for p in problems), "提升 3 分未过噪声下限被拒绝")
    ok, problems = rsi_store.validate_proposal(proposal(tasks=1))
    check(any("≥2 个不同任务" in p for p in problems), "单一任务样本被拒绝")
    four_changes = dict(lib.RUBRIC_V0["weights"])
    four_changes["evidence"] += 10
    four_changes["cost"] -= 10
    four_changes["correctness"] += 5
    four_changes["robustness"] -= 5
    ok, problems = rsi_store.validate_proposal(proposal(edits=4, weight_set=four_changes))
    check(any("编辑预算" in p for p in problems), "超出编辑预算被拒绝")
    ok, problems = rsi_store.validate_proposal(proposal(edits=1))
    check(any("实际权重改动数" in p for p in problems), "自报 edits 与真实改动不符被拒绝")
    ok, problems = rsi_store.validate_proposal(proposal(delta=10.0, promote=True))
    check(not any("replay_score" in p for p in problems), "replay 算术自洽（覆盖全部历史轮）")

    print("== 阶段 19：DREAM→COACH 迁移 ==")
    migrated = lib.migrate_state(
        {"phase": "DREAM", "current_iter": 2, "review": {"reviewers": 2}}
    )
    check(migrated["phase"] == "COACH", "phase=DREAM 读入后按 COACH 处理")
    check(migrated["review"]["roles"] == {"A": "general", "B": "general"}, "补齐 roles 默认值")

    print("== 阶段 20：经验库指标与教训蒸馏 ==")
    record = rsi_store.build_record(run)
    check(record["iterations"] == 3 and len(record["scores"]) == 3, "记录含 3 轮分数")
    check(len(record["coach"]) == 3, f"记录含 3 轮教练：{len(record['coach'])}")
    check(record["coach"][0]["hit_rate"] is None, "第 1 轮无上一轮条目 → 不计算命中率")
    check(record["coach"][1]["hit_rate"] == 0.5, "第 2 轮命中率 0.5（4 条覆盖，2 条复发）")
    metrics = rsi_store.compute_metrics([record])
    check(metrics["runs"] == 1, "指标样本 1")
    check(metrics["coach_hit_rate"] == 0.75, f"指标含教练命中率（{metrics['coach_hit_rate']}）")
    check("evidence_gap" in metrics.get("error_classes", {}), "指标含错误类别计数")

    def synth(task: str, cls: str = "evidence_gap") -> dict:
        return {
            "run_id": task,
            "task": task,
            "task_hash": rsi_store.task_hash(task),
            "split": rsi_store.split_of(task),
            "tags": {"tier": "Medium", "external": True, "workers": 3},
            "scores": [{"iteration": 1, "total": 78, "verdict": "REVISE",
                        "dimensions": {"correctness": 80, "completeness": 78, "evidence": 70,
                                       "robustness": 80, "maintainability": 80, "cost": 80}}],
            "errors": [{"reviewer": "A", "id": "E1", "class": cls}],
            "coach": [{"iteration": 1, "hit_rate": 0.5, "items": [
                {"id": "C1", "from_error": ["A:E1"], "applies_to": ["w01"],
                 "action": "单设取证 worker，先产出 sources.yaml"}
            ]}],
            "objective": {}, "cost": {"iterations": 1, "workers": 3, "reviewers": 1},
        }
    created = rsi_store.distill_lessons([synth("样本甲"), synth("样本乙")], min_support=2)
    check(len(created) == 1, f"两个 run 支持同一类 → 蒸馏 1 条教训（实际 {len(created)}）")
    lessons = rsi_store.load_lessons()
    check(lessons and lessons[0]["error_classes"] == ["evidence_gap"], "教训按错误类别归档")
    retrieved = rsi_store.retrieve_lessons(
        {"tier": "Medium", "workers": {"planned": 3}}, ["evidence_gap"]
    )
    check(bool(retrieved), "教训可被检索到")
    check(len(retrieved[0]["action"]) <= 240, "注入内容受长度预算约束")

    print("== 阶段 21：CLI 入口与 exit 2 ==")
    cli_root = SELFTEST_DIR / "cli-runs"
    cli_root.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    def run_cli(*args: str) -> tuple[int, str, str]:
        out_path = SELFTEST_DIR / "_cli_stdout.tmp"
        err_path = SELFTEST_DIR / "_cli_stderr.tmp"
        with open(out_path, "w", encoding="utf-8") as out, open(err_path, "w", encoding="utf-8") as err:
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / "orchestrator.py"), *args],
                stdout=out, stderr=err, stdin=subprocess.DEVNULL, cwd=str(SCRIPTS),
                env=env, timeout=180,
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
    rc, out, err = run_cli("coach-show", cli_run, "--json")
    check(rc == 0, f"CLI coach-show 可用（exit {rc}）")
    rc, out, err = run_cli("citation-audit", cli_run, "--off", "--json")
    check(rc == 0 and json.loads(out)["citation_audit"] == "off", "CLI citation-audit --off 可用")
    rc, out, err = run_cli("reviewers", cli_run, "--count", "3", "--json")
    check(rc == 0 and json.loads(out)["reviewers"] == 3, "CLI reviewers --count 3 成功")

    print("== 阶段 22：L 级引用核验（B 专责）==")
    cite_root = SELFTEST_DIR / "citation-runs"
    cite_root.mkdir(parents=True, exist_ok=True)
    cite = lib.create_run(cite_root, "teamwork, N=1 L 级引用核验测试")
    lib.advance_run(cite)
    mk_classification(cite, "Large", 5)
    lib.advance_run(cite)
    cite_state = state_of(cite)
    check(cite_state["review"]["reviewers"] == 2, "L 级默认 2 位评审")
    check(
        cite_state["review"]["roles"] == {"A": "general", "B": "citation_audit"},
        "L 级 B 专责引用核验",
    )
    check(cite_state["review"]["citation_audit"] == "auto", "引用核验默认 auto（L 级开启）")
    mk_plan(cite, 1, "Large", 5)
    lib.advance_run(cite)
    cite_rels = mk_dispatch(cite, 1, 5)
    lib.advance_run(cite)
    mk_workers(cite, 1, cite_rels, with_sources=True)
    lib.advance_run(cite)
    mk_final(cite, 1, cite_rels[0], with_sources=True)
    packet = lib.make_review_packet(cite, state_of(cite))
    packet_fm, _ = lib.read_artifact(packet)
    check(len(packet_fm.get("citations") or []) == 2, "评审包生成 2 条 citations")
    check(packet_fm["citation_policy"]["required"] is True, "L 级 citation_policy.required=true")
    lib.advance_run(cite)
    mk_gate(cite, 1, "PASS", [], "通过")
    lib.advance_run(cite)

    valid_audit = {
        "mode": "online",
        "coverage": {"total": 2, "audited": 2, "verified": 2,
                     "unverifiable": 0, "misattributed": 0, "fabricated": 0},
        "items": [
            {"id": "S01", "verdict": "verified", "method": "fetch", "locator": "Abstract",
             "checked_at": lib.now_iso(), "note": "原文摘要确有该表述"},
            {"id": "S02", "verdict": "verified", "method": "fetch", "locator": "§3.2",
             "checked_at": lib.now_iso(), "note": "数字一致"},
        ],
    }
    mk_review(cite, 1, "A", 80,
              errors=[{"id": "E1", "class": "evidence_gap", "located": "final_result.md#L8"}])
    missing = {**valid_audit, "items": [valid_audit["items"][0]],
               "coverage": {"total": 1, "audited": 1, "verified": 1,
                            "unverifiable": 0, "misattributed": 0, "fabricated": 0}}
    mk_review(cite, 1, "B", 75, role="citation_audit", audit=missing)
    expect_reject(cite, "漏项", "B 漏核一条来源时")
    no_time = {**valid_audit, "items": [
        {k: v for k, v in valid_audit["items"][0].items() if k != "checked_at"},
        valid_audit["items"][1],
    ]}
    mk_review(cite, 1, "B", 75, role="citation_audit", audit=no_time)
    expect_reject(cite, "结构锁", "verified 缺 checked_at 时")
    offline = {**valid_audit, "mode": "offline"}
    mk_review(cite, 1, "B", 75, role="citation_audit", audit=offline)
    expect_reject(cite, "离线模式禁止", "离线仍判 verified 时")
    fabricated = {
        "mode": "online",
        "coverage": {"total": 2, "audited": 2, "verified": 1,
                     "unverifiable": 0, "misattributed": 0, "fabricated": 1},
        "items": [valid_audit["items"][0],
                  {"id": "S02", "verdict": "fabricated", "method": "fetch",
                   "locator": "查无此页", "checked_at": lib.now_iso(), "note": "404"}],
    }
    mk_review(cite, 1, "B", 75, role="citation_audit", audit=fabricated)
    expect_reject(cite, "虚构来源", "fabricated 未触发一票否决时")
    misattributed = {
        "mode": "online",
        "coverage": {"total": 2, "audited": 2, "verified": 1,
                     "unverifiable": 0, "misattributed": 1, "fabricated": 0},
        "items": [valid_audit["items"][0],
                  {"id": "S02", "verdict": "misattributed", "method": "fetch",
                   "locator": "§3.2 实为反例", "checked_at": lib.now_iso(), "note": "结论写反"}],
    }
    mk_review(cite, 1, "B", 90, role="citation_audit", audit=misattributed)
    expect_reject(cite, "封顶 60", "misattributed 但 evidence 未封顶时")
    mk_review(cite, 1, "B", 75, role="citation_audit", audit=valid_audit)
    lib.advance_run(cite)
    cite_state = state_of(cite)
    check(cite_state["phase"] == "COACH", "引用核验合法 → 推进到 COACH")
    check(cite_state["scores"][0]["total"] == 78, f"合成 78（实际 {cite_state['scores'][0]['total']}）")
    mk_coach(cite, 1, verdict="REVISE", score=78, items=[], taxonomy=[],
             advisory_input={"estimated_gain_next_round": 6, "remaining_gaps": ["证据不足"],
                             "diminishing": False, "rationale": "差距 7 分，历史单轮最大提升 6 分。"})
    lib.advance_run(cite)
    check(state_of(cite)["advisory"]["recommendation"] == "continue", "78 分建议续跑")
    check(len(state_of(cite)["advisory"]["recommended_rounds"] and [1]) == 1, "建议轮数为正整数")

    print("== 阶段 23：L 级人数上限与多任务隔离 ==")
    check(lib.TIER_RANGES["Large"] == (5, 7), "Large worker 范围 5–7（+Final Agent 共 8）")
    cap_root = SELFTEST_DIR / "cap-runs"
    cap_root.mkdir(parents=True, exist_ok=True)
    cap = lib.create_run(cap_root, "teamwork, N=1 L 级上限测试")
    fake_art = cap / "iterations" / "iter-01" / "workers" / "w01_artifacts" / "out.md"
    fake_art.parent.mkdir(parents=True, exist_ok=True)
    fake_art.write_text("x\n", encoding="utf-8")

    def dispatch_check(target: Path, tier: str, iteration: int, ids: list[str]) -> "lib.Check":
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

    large_ids = [f"w{idx:02d}" for idx in range(1, 9)]
    chk = dispatch_check(cap, "Large", 1, large_ids)
    check(any("5–7" in e for e in chk.errors), "Large 8 个 worker 被拒绝（上限 7）")
    chk = dispatch_check(cap, "Large", 1, large_ids[:7])
    check(not chk.errors, "Large 7 个 worker 通过（+Final=8）")

    multi_root = SELFTEST_DIR / "multi-task"
    multi_root.mkdir(parents=True, exist_ok=True)
    task_a = lib.create_run(multi_root, "teamwork, N=1 任务甲")
    task_b = lib.create_run(multi_root, "teamwork, N=1 任务乙")
    ids6 = [f"w{idx:02d}" for idx in range(1, 7)]
    chk_a = dispatch_check(task_a, "Large", 1, ids6)
    chk_b = dispatch_check(task_b, "Large", 1, ids6)
    check(not chk_a.errors and not chk_b.errors, "同一对话两个任务各 6 worker 互不占用")
    lib.advance_run(task_a)
    lib.advance_run(task_b)
    names_a = set(state_of(task_a)["workers"]["agents"].values())
    names_b = set(state_of(task_b)["workers"]["agents"].values())
    check(len(names_a) == 6 and not (names_a & names_b), "两任务物理 agent 名互不重叠")

    print()
    if FAILURES:
        print(f"自测失败：{len(FAILURES)} 项")
        for item in FAILURES:
            print(f" - {item}")
        return 1
    print(f"自测全部通过。run 目录：{run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
