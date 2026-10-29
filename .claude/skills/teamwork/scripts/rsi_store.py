"""环外 RSI：经验库（L0）、教训蒸馏（L1）、尺子受限演进（L3）。

三条边界（与 teamwork_lib 一致）：
1. 环内（COACH）只改做法，本模块只在 run 结束后被调用；
2. 尺子演进的数字必须能复算：replay_score 由历史维度分重新加权得到，
   不是 Agent 自报；代码校验算术、覆盖、门槛，但**不能**校验历史分本身是否公允；
3. 所有写操作都在 `TEAMWORK_EXPERIENCE_HOME`（默认 ~/.teamwork/experience）内，
   不碰 run 目录；采纳策略需要显式 `adopt`。

目录结构：
    experience/
      runs/<run_id>.json          每次 run 一条结构化记录
      lessons/<lesson_id>.md      蒸馏出的做法（frontmatter + 说明）
      policies/evaluator/vN.md    已批准的策略版本
      policies/evaluator/CURRENT  当前指针
      proposals/<version>.md      待审提案
      golden/index.json           人工确认的锚点（run_id → 期望总分）
      metrics.md                  看板
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import teamwork_lib as lib  # noqa: E402

SCHEMA_VERSION = 1
LESSON_MIN_SUPPORT = 2
LESSON_TOP_K = 5
LESSON_TOKEN_BUDGET = 800
LESSON_RETIRE_AFTER = 5
HOLDOUT_MODULUS = 3  # task_hash % 3 == 0 → validation


def experience_home() -> Path:
    raw = os.environ.get("TEAMWORK_EXPERIENCE_HOME")
    base = Path(raw).expanduser() if raw else Path.home() / ".teamwork" / "experience"
    for sub in ("runs", "lessons", "policies/evaluator", "proposals", "golden"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def task_hash(task: str) -> int:
    return int(hashlib.sha1((task or "").strip().encode("utf-8")).hexdigest()[:8], 16)


def split_of(task: str) -> str:
    return "validation" if task_hash(task) % HOLDOUT_MODULUS == 0 else "train"


# --------------------------------------------------------------------------- #
# L0：run 记录
# --------------------------------------------------------------------------- #
def _iter_errors(run_dir: Path, iteration: int, state: dict[str, Any]) -> list[dict[str, Any]]:
    iter_dir = run_dir / "iterations" / f"iter-{iteration:02d}"
    scratch = lib.Check(run_dir, state)
    out: list[dict[str, Any]] = []
    for path in sorted(iter_dir.glob("review_report_*.md")):
        letter = path.stem.rsplit("_", 1)[-1]
        try:
            fm, _ = lib.read_artifact(path)
        except lib.TeamworkError:
            continue
        for err in lib.normalise_errors(scratch, fm.get("errors") or [], path.name):
            out.append({"reviewer": letter, **err})
    return out


def _coach_entries(run_dir: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in (state.get("coach") or {}).get("entries") or []:
        iteration = entry.get("iteration")
        path = lib.run_paths(run_dir, int(iteration))["rsi"]
        payload: dict[str, Any] = {}
        if path.exists():
            try:
                payload, _ = lib.read_artifact(path)
            except lib.TeamworkError:
                payload = {}
        items = []
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "id": item.get("id"),
                    "from_error": item.get("from_error") or [],
                    "applies_to": item.get("applies_to") or [],
                    "priority": item.get("priority"),
                    "root_cause": item.get("root_cause"),
                    "action": item.get("action"),
                    "verification": item.get("verification"),
                }
            )
        out.append({**entry, "items": items})
    return out


def build_record(run_dir: Path) -> dict[str, Any]:
    state = lib.load_state(run_dir)
    scores = [s for s in (state.get("scores") or []) if isinstance(s, dict)]
    iterations = int(state.get("current_iter") or 1)
    errors: list[dict[str, Any]] = []
    for iteration in range(1, iterations + 1):
        for err in _iter_errors(run_dir, iteration, state):
            err["iteration"] = iteration
            errors.append(err)
    coach_entries = _coach_entries(run_dir, state)
    # 归因：coach item 的 from_error（复合 id）→ applies_to
    attribution: dict[str, list[str]] = {}
    for entry in coach_entries:
        for item in entry["items"]:
            for ref in item.get("from_error") or []:
                attribution[str(ref)] = item.get("applies_to") or []
    for err in errors:
        composite = f"{err['reviewer']}:{err['id']}"
        err["attributed_to"] = attribution.get(composite, [])
        err["iteration"] = err.get("iteration")

    classification: dict[str, Any] = {}
    class_path = run_dir / "00_intake" / "classification.md"
    if class_path.exists():
        try:
            classification, _ = lib.read_artifact(class_path)
        except lib.TeamworkError:
            classification = {}
    signals = classification.get("signals") or {}

    final_report: dict[str, Any] = {}
    report_path = lib.run_paths(run_dir, iterations)["final_report"]
    if report_path.exists():
        try:
            final_report, _ = lib.read_artifact(report_path)
        except lib.TeamworkError:
            final_report = {}

    objective = {
        "gate_pass": _last_gate_verdict(run_dir, iterations) == "PASS",
        "citation_verified_ratio": _citation_ratio(run_dir, iterations, state),
        "iterations": iterations,
    }
    deliverable_count = 0
    final_path = lib.run_paths(run_dir, iterations)["final"]
    if final_path.exists():
        try:
            final_fm, _ = lib.read_artifact(final_path)
            deliverable_count = len(final_fm.get("deliverables") or [])
        except lib.TeamworkError:
            deliverable_count = 0
    objective["deliverables"] = deliverable_count

    lessons_applied: dict[str, int] = {}
    for iteration in range(1, iterations + 1):
        path = lib.run_paths(run_dir, iteration)["dispatch"]
        if not path.exists():
            continue
        try:
            dfm, _ = lib.read_artifact(path)
        except lib.TeamworkError:
            continue
        for lid in dfm.get("lessons_applied") or []:
            if isinstance(lid, str) and lid.strip():
                lessons_applied.setdefault(lid.strip(), iteration)

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": state.get("run_id"),
        "run_dir": str(run_dir),
        "task": state.get("task"),
        "task_hash": task_hash(str(state.get("task") or "")),
        "split": split_of(str(state.get("task") or "")),
        "tier": state.get("tier"),
        "n_mode": state.get("n_mode"),
        "n": state.get("n"),
        "iterations": iterations,
        "tags": {
            "tier": state.get("tier"),
            "external": bool(signals.get("external")),
            "verifiable": bool(signals.get("verifiable")),
            "parallel": bool(signals.get("parallel")),
            "risk": signals.get("risk"),
            "workers": int((state.get("workers") or {}).get("planned") or 0),
        },
        "scores": [
            {
                "iteration": s.get("iteration"),
                "total": s.get("total"),
                "verdict": s.get("verdict"),
                "dimensions": s.get("dimensions") or {},
                "policy_version": s.get("policy_version"),
            }
            for s in scores
        ],
        "errors": errors,
        "coach": [
            {
                "iteration": e.get("iteration"),
                "hit_rate": e.get("hit_rate"),
                "covered": e.get("covered") or [],
                "recurred": e.get("recurred") or [],
                "taxonomy_classes": e.get("taxonomy_classes") or [],
                "items": e.get("items") or [],
            }
            for e in coach_entries
        ],
        "advisory_history": state.get("advisory_history") or [],
        "advisory": state.get("advisory"),
        "advisory_response": final_report.get("advisory_response"),
        "lessons_applied": lessons_applied,
        "objective": objective,
        "cost": {
            "iterations": iterations,
            "workers": int((state.get("workers") or {}).get("planned") or 0),
            "reviewers": int((state.get("review") or {}).get("reviewers") or 1),
        },
        "finished_at": now_iso(),
    }


def _last_gate_verdict(run_dir: Path, iteration: int) -> str:
    path = lib.run_paths(run_dir, iteration)["gate"]
    if not path.exists():
        return ""
    try:
        fm, _ = lib.read_artifact(path)
    except lib.TeamworkError:
        return ""
    return str(fm.get("verdict") or "")


def _citation_ratio(run_dir: Path, iteration: int, state: dict[str, Any]) -> float | None:
    reviewers = int((state.get("review") or {}).get("reviewers") or 1)
    for idx in range(1, reviewers + 1):
        path = lib.review_report_path(run_dir, iteration, lib.review_letter(idx))
        if not path.exists():
            continue
        try:
            fm, _ = lib.read_artifact(path)
        except lib.TeamworkError:
            continue
        audit = fm.get("citation_audit") or {}
        coverage = audit.get("coverage") or {}
        total = coverage.get("total")
        verified = coverage.get("verified")
        if isinstance(total, int) and total > 0 and isinstance(verified, int):
            return round(verified / total, 3)
    return None


def record_run(run_dir: Path) -> dict[str, Any]:
    record = build_record(run_dir)
    path = experience_home() / "runs" / f"{record['run_id']}.json"
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    update_lesson_outcomes(record)
    return {"path": str(path), "run_id": record["run_id"]}


def load_runs() -> list[dict[str, Any]]:
    home = experience_home()
    runs: list[dict[str, Any]] = []
    for path in sorted((home / "runs").glob("*.json")):
        try:
            runs.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    runs.sort(key=lambda r: str(r.get("finished_at") or ""))
    return runs


# --------------------------------------------------------------------------- #
# 指标
# --------------------------------------------------------------------------- #
def compute_metrics(runs: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(runs)
    first_pass = 0
    rounds_to_pass: list[int] = []
    hit_rates: list[float] = []
    calibration: list[dict[str, Any]] = []
    class_seen: dict[str, int] = {}
    class_recurred: dict[str, int] = {}
    for run in runs:
        scores = run.get("scores") or []
        if scores and scores[0].get("verdict") == "PASS":
            first_pass += 1
        for score in scores:
            if score.get("verdict") == "PASS":
                rounds_to_pass.append(int(score.get("iteration") or 0))
                break
        for entry in run.get("coach") or []:
            if isinstance(entry.get("hit_rate"), (int, float)):
                hit_rates.append(float(entry["hit_rate"]))
        history = run.get("advisory_history") or []
        for item in history:
            iteration = int(item.get("iteration") or 0)
            later = [s for s in scores if int(s.get("iteration") or 0) == iteration + 1]
            if later and isinstance(item.get("expected_gain"), int):
                calibration.append(
                    {
                        "run_id": run.get("run_id"),
                        "iteration": iteration,
                        "predicted": int(item["expected_gain"]),
                        "actual": int(later[0].get("total") or 0) - int(item.get("score") or 0),
                    }
                )
        classes = {str(e.get("class")) for e in run.get("errors") or []}
        for klass in classes:
            class_seen[klass] = class_seen.get(klass, 0) + 1
    for prev, cur in zip(runs, runs[1:]):
        prev_classes = {str(e.get("class")) for e in prev.get("errors") or []}
        cur_classes = {str(e.get("class")) for e in cur.get("errors") or []}
        for klass in prev_classes & cur_classes:
            class_recurred[klass] = class_recurred.get(klass, 0) + 1
    recurrence = {
        klass: round(class_recurred.get(klass, 0) / max(1, class_seen[klass] - 0), 3)
        for klass in sorted(class_seen)
    }
    err = None
    if calibration:
        err = round(
            statistics.mean(abs(c["actual"] - c["predicted"]) for c in calibration), 2
        )
    return {
        "runs": total,
        "first_pass_rate": round(first_pass / total, 3) if total else None,
        "median_rounds_to_pass": (
            round(statistics.median(rounds_to_pass), 2) if rounds_to_pass else None
        ),
        "coach_hit_rate": round(statistics.mean(hit_rates), 3) if hit_rates else None,
        "calibration_error": err,
        "calibration_samples": len(calibration),
        "error_recurrence": recurrence,
        "error_classes": dict(sorted(class_seen.items())),
        "avg_iterations": (
            round(statistics.mean(int(r.get("iterations") or 0) for r in runs), 2)
            if total
            else None
        ),
    }


def render_metrics(runs: list[dict[str, Any]] | None = None) -> Path:
    runs = runs if runs is not None else load_runs()
    metrics = compute_metrics(runs)
    rows = "\n".join(
        f"| {klass} | {rate:.0%} |" for klass, rate in metrics["error_recurrence"].items()
    ) or "| — | — |"
    body = f"""# teamwork 经验库看板

- 样本：**{metrics['runs']}** 个 run
- 首轮通过率：{_pct(metrics['first_pass_rate'])}
- 达 PASS 中位轮数：{metrics['median_rounds_to_pass'] if metrics['median_rounds_to_pass'] is not None else '—'}
- **教练命中率**：{_pct(metrics['coach_hit_rate'])}
- 建议校准误差（预测增益 vs 实际增益）：{metrics['calibration_error'] if metrics['calibration_error'] is not None else '—'}（{metrics['calibration_samples']} 个样本）
- 平均轮数：{metrics['avg_iterations'] if metrics['avg_iterations'] is not None else '—'}

## 错误类别复发率

| 类别 | 相邻 run 复发率 |
|---|---|
{rows}

> 「复发率」= 该类错误在相邻两个 run 都出现的次数 / 该类出现过的 run 数。
> 这是 RSI 唯一有说服力的证据：如果它不降，说明"自我改进"没有发生。
"""
    path = experience_home() / "metrics.md"
    path.write_text(body, encoding="utf-8")
    return path


def _pct(value: Any) -> str:
    return f"{value:.0%}" if isinstance(value, (int, float)) else "—"


# --------------------------------------------------------------------------- #
# L1：教训
# --------------------------------------------------------------------------- #
LESSON_RE = re.compile(r"^L-\d{8}-\d{2}$")


def _lesson_paths() -> list[Path]:
    return sorted((experience_home() / "lessons").glob("L-*.md"))


def load_lessons(include_retired: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in _lesson_paths():
        try:
            fm, body = lib.read_artifact(path)
        except lib.TeamworkError:
            continue
        fm["id"] = path.stem
        fm["body"] = body
        fm["path"] = str(path)
        if not include_retired and fm.get("status") == "retired":
            continue
        out.append(fm)
    return out


def distill_lessons(
    runs: list[dict[str, Any]] | None = None, min_support: int = LESSON_MIN_SUPPORT
) -> list[dict[str, Any]]:
    """把跨 run 反复出现、且教练给过可执行动作的错误压成教训。"""
    runs = runs if runs is not None else load_runs()
    buckets: dict[tuple[Any, ...], dict[str, Any]] = {}
    for run in runs:
        class_by_ref: dict[str, str] = {}
        for err in run.get("errors") or []:
            class_by_ref[f"{err.get('reviewer')}:{err.get('id')}"] = str(err.get("class"))
        for entry in run.get("coach") or []:
            for item in entry.get("items") or []:
                classes = tuple(
                    sorted(
                        {
                            class_by_ref.get(str(ref), "unclassified")
                            for ref in item.get("from_error") or []
                        }
                    )
                )
                if not classes:
                    continue
                key = (classes, tuple(item.get("applies_to") or []))
                bucket = buckets.setdefault(
                    key,
                    {
                        "classes": classes,
                        "applies_to": list(item.get("applies_to") or []),
                        "runs": set(),
                        "actions": [],
                        "root_causes": [],
                        "tiers": set(),
                        "external": [],
                        "workers": [],
                    },
                )
                bucket["runs"].add(run.get("run_id"))
                if item.get("action"):
                    bucket["actions"].append(str(item["action"]))
                if item.get("root_cause"):
                    bucket["root_causes"].append(str(item["root_cause"]))
                tags = run.get("tags") or {}
                if tags.get("tier"):
                    bucket["tiers"].add(str(tags["tier"]))
                bucket["external"].append(bool(tags.get("external")))
                bucket["workers"].append(int(tags.get("workers") or 0))

    created: list[dict[str, Any]] = []
    existing = {tuple(sorted(l.get("error_classes") or [])): l for l in load_lessons()}
    for key, bucket in buckets.items():
        support = len(bucket["runs"])
        if support < min_support:
            continue
        classes = list(bucket["classes"])
        if tuple(sorted(classes)) in existing:
            continue
        action = _most_common(bucket["actions"])
        if not action:
            continue
        lesson_id = _next_lesson_id()
        trigger = {
            "tiers": sorted(bucket["tiers"]),
            "external": all(bucket["external"]) if bucket["external"] else None,
            "min_workers": min([w for w in bucket["workers"] if w] or [0]),
        }
        payload = {
            "schema_version": SCHEMA_VERSION,
            "id": lesson_id,
            "trigger": trigger,
            "error_classes": classes,
            "applies_to": bucket["applies_to"],
            "action": action,
            "root_cause": _most_common(bucket["root_causes"]),
            "evidence": sorted(str(r) for r in bucket["runs"]),
            "confidence": round(min(0.9, 0.5 + 0.1 * support), 2),
            "applied": 0,
            "resolved": 0,
            "status": "active",
            "created_at": now_iso(),
        }
        path = experience_home() / "lessons" / f"{lesson_id}.md"
        lib.write_artifact(path, payload, f"# {lesson_id}\n\n{action}\n")
        created.append(payload)
    return created


def _most_common(values: list[str]) -> str:
    if not values:
        return ""
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _next_lesson_id() -> str:
    day = datetime.now().strftime("%Y%m%d")
    used = {p.stem for p in _lesson_paths()}
    for idx in range(1, 100):
        candidate = f"L-{day}-{idx:02d}"
        if candidate not in used:
            return candidate
    raise lib.TeamworkError("当天的教训编号已用尽")


def score_lesson(lesson: dict[str, Any], state: dict[str, Any], error_classes: list[str]) -> float:
    trigger = lesson.get("trigger") or {}
    tags = {
        "tier": state.get("tier"),
        "external": None,
        "workers": int((state.get("workers") or {}).get("planned") or 0),
    }
    tier_match = 1.0 if tags["tier"] in (trigger.get("tiers") or []) else 0.0
    class_match = (
        1.0
        if set(lesson.get("error_classes") or []) & set(error_classes or [])
        else 0.0
    )
    created = lesson.get("created_at")
    decay = 0.0
    if isinstance(created, str):
        try:
            stamp = datetime.fromisoformat(created)
            days = max(0, (datetime.now().astimezone() - stamp).days)
            decay = max(0.0, 1 - days / 90)
        except ValueError:
            decay = 0.0
    return 0.5 * tier_match + 0.3 * class_match + 0.2 * decay


def retrieve_lessons(
    state: dict[str, Any], error_classes: list[str], limit: int = LESSON_TOP_K
) -> list[dict[str, Any]]:
    lessons = load_lessons()
    scored = []
    for lesson in lessons:
        score = score_lesson(lesson, state, error_classes)
        if score <= 0:
            continue
        scored.append((score, lesson))
    scored.sort(key=lambda item: item[0], reverse=True)
    picked: list[dict[str, Any]] = []
    budget = LESSON_TOKEN_BUDGET
    for score, lesson in scored[:limit]:
        action = str(lesson.get("action") or "")[:240]
        cost = len(action) + 40
        if cost > budget:
            break
        budget -= cost
        picked.append(
            {
                "id": lesson.get("id"),
                "action": action,
                "error_classes": lesson.get("error_classes") or [],
                "confidence": lesson.get("confidence"),
                "score": round(score, 3),
            }
        )
    return picked


def update_lesson_outcomes(record: dict[str, Any]) -> None:
    """按 dispatch 里 lessons_applied 记账：本轮之后再没出现同类错误 = resolved。"""
    run_dir = Path(record.get("run_dir") or "") if record.get("run_dir") else None
    applied_map = record.get("lessons_applied") or {}
    if not applied_map:
        return
    lessons = {l["id"]: l for l in load_lessons(include_retired=True)}
    for lesson_id, iteration in applied_map.items():
        lesson = lessons.get(str(lesson_id))
        path = lesson.get("path") if lesson else None
        if not path:
            continue
        classes = set(lesson.get("error_classes") or [])
        later = [
            e
            for e in record.get("errors") or []
            if int(e.get("iteration") or 0) > int(iteration)
        ]
        resolved = not (classes & {str(e.get("class")) for e in later})
        fm = {k: v for k, v in lesson.items() if k not in ("body", "path")}
        fm["applied"] = int(fm.get("applied") or 0) + 1
        fm["resolved"] = int(fm.get("resolved") or 0) + (1 if resolved else 0)
        lib.write_artifact(Path(path), fm, lesson.get("body") or "")


def retire_lessons() -> list[str]:
    retired: list[str] = []
    lessons = load_lessons()
    if not lessons:
        return retired
    baseline = statistics.mean(
        (int(l.get("resolved") or 0) / max(1, int(l.get("applied") or 0))) for l in lessons
    )
    for lesson in lessons:
        applied = int(lesson.get("applied") or 0)
        if applied < LESSON_RETIRE_AFTER:
            continue
        rate = int(lesson.get("resolved") or 0) / applied
        if rate < baseline - 0.1:
            fm = {k: v for k, v in lesson.items() if k not in ("body", "path")}
            fm["status"] = "retired"
            fm["retired_at"] = now_iso()
            lib.write_artifact(Path(lesson["path"]), fm, lesson.get("body") or "")
            retired.append(str(lesson["id"]))
    return retired


# --------------------------------------------------------------------------- #
# L3：尺子受限演进
# --------------------------------------------------------------------------- #
def _weights_score(dimensions: dict[str, Any], weights: dict[str, int]) -> float:
    total = 0.0
    for name, weight in weights.items():
        value = dimensions.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total += float(value) * float(weight) / 100.0
    return total


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 2) if values else 0.0


def _candidate_weights(base: dict[str, int], runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """候选必须是确定性生成的，不能由模型随便写。"""
    dims = list(base)
    means: dict[str, float] = {}
    for name in dims:
        values = [
            float(s["dimensions"][name])
            for run in runs
            for s in run.get("scores") or []
            if isinstance(s.get("dimensions"), dict) and name in s["dimensions"]
        ]
        means[name] = _mean(values)
    weakest = min(dims, key=lambda d: means[d])
    strongest = max(dims, key=lambda d: means[d])
    candidates = []

    def make(cid: str, edits: dict[str, int], note: str) -> None:
        weights = dict(base)
        for name, delta in edits.items():
            weights[name] = weights[name] + delta
        if sum(weights.values()) != 100 or any(v < 0 for v in weights.values()):
            return
        if any(abs(weights[n] - base[n]) > 10 for n in base):
            return
        candidates.append(
            {
                "id": cid,
                "edits": sum(1 for delta in edits.values() if delta),
                "change": note,
                "weights": weights,
            }
        )

    make("c1", {weakest: 5, strongest: -5}, f"{weakest} +5 / {strongest} -5（补短板）")
    make("c2", {"evidence": 10, "cost": -10}, "evidence +10 / cost -10（证据优先）")
    make("c3", {"correctness": 10, "maintainability": -10}, "correctness +10 / maintainability -10")
    return candidates[:3]


def build_proposal(
    runs: list[dict[str, Any]] | None = None, noise_floor: int | None = None
) -> Path:
    runs = runs if runs is not None else load_runs()
    usable = [r for r in runs if any(s.get("dimensions") for s in r.get("scores") or [])]
    tasks = {r.get("task_hash") for r in usable}
    if len(usable) < 2 or len(tasks) < 2:
        raise lib.TeamworkError(
            f"样本不足：需要 ≥2 个 run 且 ≥2 个不同任务才能提晋级（当前 {len(usable)} run / "
            f"{len(tasks)} 任务）"
        )
    base = dict(lib.RUBRIC_V0["weights"])
    noise = int(noise_floor if noise_floor is not None else lib.RUBRIC_V0["noise_floor"])
    train = [r for r in usable if r.get("split") != "validation"]
    validation = [r for r in usable if r.get("split") == "validation"]
    if not train:
        train = usable
    if not validation:
        raise lib.TeamworkError("没有 holdout 样本（按任务哈希切分后 validation 为空），拒绝提晋级")
    baseline_all = _mean(
        [_weights_score(s["dimensions"], base) for r in usable for s in r.get("scores") or [] if s.get("dimensions")]
    )
    baseline_train = _mean(
        [_weights_score(s["dimensions"], base) for r in train for s in r.get("scores") or [] if s.get("dimensions")]
    )
    baseline_val = _mean(
        [_weights_score(s["dimensions"], base) for r in validation for s in r.get("scores") or [] if s.get("dimensions")]
    )
    entries = []
    best: dict[str, Any] | None = None
    for cand in _candidate_weights(base, usable):
        train_scores = [
            _weights_score(s["dimensions"], cand["weights"])
            for r in train
            for s in r.get("scores") or []
            if s.get("dimensions")
        ]
        val_scores = [
            _weights_score(s["dimensions"], cand["weights"])
            for r in validation
            for s in r.get("scores") or []
            if s.get("dimensions")
        ]
        replay = _mean(train_scores)
        val = _mean(val_scores)
        entry = {
            **cand,
            "replay_score": replay,
            "validation_score": val,
            "world_scores": [
                {
                    "run_id": r.get("run_id"),
                    "iteration": s.get("iteration"),
                    "score": round(_weights_score(s["dimensions"], cand["weights"]), 2),
                }
                for r in usable
                for s in r.get("scores") or []
                if s.get("dimensions")
            ],
            "validation_delta": round(val - baseline_val, 2),
        }
        entries.append(entry)
        if best is None or entry["replay_score"] > best["replay_score"]:
            best = entry
    assert best is not None
    tasks_ok = len(tasks) >= 2
    promote = (
        best["replay_score"] - baseline_all > noise
        and best["validation_delta"] > 0
        and tasks_ok
    )
    version = _next_policy_version()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "proposal": version,
        "generated_by": "dream --offline",
        "generated_at": now_iso(),
        "policy_before": "v0",
        "noise_floor": noise,
        "max_edits_per_iteration": int(lib.RUBRIC_V0["max_edits_per_iteration"]),
        "sample": {
            "runs": len(usable),
            "tasks": len(tasks),
            "train": len(train),
            "validation": len(validation),
            "holdout": f"task_hash % {HOLDOUT_MODULUS} == 0",
        },
        "baseline": {
            "all": baseline_all,
            "train": baseline_train,
            "validation": baseline_val,
        },
        "candidates": entries,
        "decision": "promote" if promote else "keep",
        "policy_after": version if promote else "v0",
        "reason": (
            f"最佳候选 {best['id']}：全量 +{round(best['replay_score'] - baseline_all, 2)} 分、"
            f"holdout {best['validation_delta']:+.2f} 分，噪声下限 {noise}；"
            f"样本 {len(usable)} run / {len(tasks)} 任务"
            if promote
            else f"最佳候选 {best['id']} 未同时满足噪声下限/ holdout 正增益/ ≥2 任务，keep v0"
        ),
    }
    ok, problems = validate_proposal(payload)
    if not ok:
        raise lib.TeamworkError("提案未通过校验：\n" + "\n".join(problems))
    path = experience_home() / "proposals" / f"{version}.md"
    lib.write_artifact(path, payload, _proposal_body(payload))
    return path


def _proposal_body(fm: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {c['id']} | {c['change']} | {c['replay_score']} | {c['validation_score']} "
        f"| {c['validation_delta']:+.2f} | {c['edits']} |"
        for c in fm["candidates"]
    )
    return (
        "# 环外尺子演进提案\n\n"
        f"- 决策：**{fm['decision']}** → {fm['policy_after']}\n"
        f"- 样本：{fm['sample']['runs']} run / {fm['sample']['tasks']} 任务"
        f"（train {fm['sample']['train']} / validation {fm['sample']['validation']}）\n"
        f"- 基线：all {fm['baseline']['all']} / train {fm['baseline']['train']} / "
        f"validation {fm['baseline']['validation']}\n"
        f"- 噪声下限：{fm['noise_floor']}\n\n"
        "| 候选 | 改动 | replay(train) | holdout | holdout Δ | 编辑数 |\n|---|---|---|---|---|---|\n"
        + rows
        + "\n\n## 理由\n\n"
        + fm["reason"]
        + "\n\n## 批准\n\n```bash\npython scripts/orchestrator.py dream --approve "
        + str(fm["proposal"])
        + "\n```\n"
    )


def validate_proposal(fm: dict[str, Any]) -> tuple[bool, list[str]]:
    """C2 的代码化：覆盖、算术、噪声下限、编辑预算、holdout。"""
    problems: list[str] = []
    noise = int(fm.get("noise_floor") or 0)
    max_edits = int(fm.get("max_edits_per_iteration") or 3)
    candidates = fm.get("candidates")
    if not isinstance(candidates, list) or not (1 <= len(candidates) <= 3):
        problems.append("candidates 需要 1–3 个")
        return False, problems
    sample = fm.get("sample") or {}
    if int(sample.get("tasks") or 0) < 2:
        problems.append("晋级样本必须覆盖 ≥2 个不同任务（防止单任务过拟合）")
    baseline = fm.get("baseline") or {}
    base_all = float(baseline.get("all") or 0)
    best = max(
        (c for c in candidates if isinstance(c, dict)),
        key=lambda c: float(c.get("replay_score") or 0),
        default={},
    )
    for cand in candidates:
        if not isinstance(cand, dict):
            problems.append("候选必须是映射")
            continue
        worlds = cand.get("world_scores")
        if not isinstance(worlds, list) or not worlds:
            problems.append(f"{cand.get('id')}：缺少 world_scores（必须覆盖历史轮次）")
            continue
        scores = [float(w.get("score")) for w in worlds if isinstance(w, dict)]
        if cand.get("replay_score") != round(statistics.mean(scores), 2):
            problems.append(
                f"{cand.get('id')}：replay_score 与 world_scores 均值不一致"
                f"（写 {cand.get('replay_score')}，应为 {round(statistics.mean(scores), 2)}）"
            )
        weights = cand.get("weights") or {}
        if set(weights) != set(lib.RUBRIC_V0["weights"]):
            problems.append(f"{cand.get('id')}：weights 必须恰好六个维度")
        else:
            for name, value in weights.items():
                if abs(int(value) - lib.RUBRIC_V0["weights"][name]) > 10:
                    problems.append(f"{cand.get('id')}：{name} 权重变化超过 ±10")
            if sum(weights.values()) != 100:
                problems.append(f"{cand.get('id')}：weights 之和必须为 100")
        if int(cand.get("edits") or 0) > max_edits:
            problems.append(f"{cand.get('id')}：超出编辑预算 {max_edits}")
        if isinstance(weights, dict) and set(weights) == set(lib.RUBRIC_V0["weights"]):
            actual_edits = sum(
                1
                for name, value in weights.items()
                if int(value) != lib.RUBRIC_V0["weights"][name]
            )
            if int(cand.get("edits") or 0) != actual_edits:
                problems.append(
                    f"{cand.get('id')}：edits={cand.get('edits')} 与实际权重改动数 "
                    f"{actual_edits} 不一致"
                )
    if fm.get("decision") == "promote":
        if float(best.get("replay_score") or 0) - base_all <= noise:
            problems.append(
                f"提升 {round(float(best.get('replay_score') or 0) - base_all, 2)} 未超过噪声下限 {noise}"
            )
        if float(best.get("validation_delta") or 0) <= 0:
            problems.append("holdout 上没有正增益，不允许 promote")
        after = fm.get("policy_after")
        if not isinstance(after, str) or not lib.POLICY_VERSION_RE.match(after):
            problems.append("promote 时 policy_after 必须是 vN")
        elif after == fm.get("policy_before"):
            problems.append("policy_after 必须不同于 policy_before")
        drift = golden_drift({c.get("id"): c.get("weights") for c in candidates if isinstance(c, dict)})
        worst = max((abs(v) for v in drift.values()), default=0.0)
        if worst > 3:
            problems.append(f"golden set 漂移 {worst:.2f} 分超过 ±3")
    elif fm.get("decision") == "keep":
        if fm.get("policy_after") != fm.get("policy_before"):
            problems.append("keep 时 policy_after 必须等于 policy_before")
    else:
        problems.append("decision 必须是 promote/keep")
    return not problems, problems


def golden_drift(candidates: dict[str, Any]) -> dict[str, float]:
    path = experience_home() / "golden" / "index.json"
    if not path.exists():
        return {}
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    runs = {r.get("run_id"): r for r in load_runs()}
    out: dict[str, float] = {}
    for cid, weights in candidates.items():
        if not isinstance(weights, dict):
            continue
        deltas = []
        for run_id, expected in index.items():
            run = runs.get(run_id)
            if not run:
                continue
            scores = [
                _weights_score(s["dimensions"], weights)
                for s in run.get("scores") or []
                if s.get("dimensions")
            ]
            if scores and isinstance(expected, (int, float)):
                deltas.append(abs(statistics.mean(scores) - float(expected)))
        if deltas:
            out[str(cid)] = round(max(deltas), 2)
    return out


def _next_policy_version() -> str:
    home = experience_home() / "policies" / "evaluator"
    versions = []
    for path in home.glob("v*.md"):
        match = re.match(r"^v(\d+)$", path.stem)
        if match:
            versions.append(int(match.group(1)))
    return f"v{max(versions, default=0) + 1}"


def approve(version: str) -> Path:
    home = experience_home()
    proposal = home / "proposals" / f"{version}.md"
    if not proposal.exists():
        raise lib.TeamworkError(f"找不到提案：{proposal}")
    fm, _ = lib.read_artifact(proposal)
    ok, problems = validate_proposal(fm)
    if not ok:
        raise lib.TeamworkError("提案未通过校验：\n" + "\n".join(problems))
    if fm.get("decision") != "promote":
        raise lib.TeamworkError("该提案的决策是 keep，不能批准为正式策略")
    weights = None
    best = max(fm["candidates"], key=lambda c: float(c.get("replay_score") or 0))
    weights = best.get("weights")
    policy = {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "weights": weights,
        "gates": list(lib.RUBRIC_V0["gates"]),
        "noise_floor": int(fm.get("noise_floor") or 5),
        "max_edits_per_iteration": int(fm.get("max_edits_per_iteration") or 3),
        "supersedes": fm.get("policy_before"),
        "approved_at": now_iso(),
        "lineage": {"proposal": str(proposal), "candidate": best.get("id")},
    }
    path = home / "policies" / "evaluator" / f"{version}.md"
    lib.write_artifact(path, policy, f"# 评估策略 {version}\n\n来自 {proposal.name} / {best.get('id')}。\n")
    (home / "policies" / "evaluator" / "CURRENT").write_text(version + "\n", encoding="utf-8")
    return path


def rollback(version: str | None = None) -> str:
    home = experience_home() / "policies" / "evaluator"
    current_file = home / "CURRENT"
    current = current_file.read_text(encoding="utf-8").strip() if current_file.exists() else "v0"
    if version:
        target = version
    else:
        versions = sorted(
            (int(p.stem[1:]), p.stem) for p in home.glob("v*.md") if re.match(r"^v\d+$", p.stem)
        )
        earlier = [name for num, name in versions if num < int(current.lstrip("v") or 0)]
        if not earlier:
            raise lib.TeamworkError("没有更早的策略版本可回滚")
        target = earlier[-1]
    if not (home / f"{target}.md").exists():
        raise lib.TeamworkError(f"找不到策略 {target}")
    current_file.write_text(target + "\n", encoding="utf-8")
    return target


def adopt_policy(run_dir: Path, version: str) -> dict[str, Any]:
    source = experience_home() / "policies" / "evaluator" / f"{version}.md"
    if not source.exists():
        raise lib.TeamworkError(f"经验库里没有策略 {version}（先 dream --approve）")
    state = lib.load_state(run_dir)
    if state["phase"] not in ("INIT", "CLASSIFY", "PLAN"):
        raise lib.TeamworkError("只能在 INIT/CLASSIFY/PLAN 阶段采纳新策略")
    fm, _ = lib.read_artifact(source)
    target = lib.policy_path(run_dir, version)
    lib.write_artifact(target, fm, f"# 审核策略 {version}\n\n从经验库采纳，来源 {source.name}。\n")
    check = lib.Check(run_dir, state)
    lib.validate_policy(check, version)
    if check.errors:
        raise lib.ValidationFailed(check.errors)
    state["review"]["policy_version"] = version
    lib.append_history(state, "adopt-policy", version)
    lib.save_state(run_dir, state)
    return {"policy_version": version, "path": str(target)}
