"""teamwork skill 共享库。

设计原则：流程、阶段顺序、产物字段、评分合成、晋级判定全部写死在这里；
模型只负责在「内容槽位」里写正文，不能改流程。所有中间产物是 Markdown +
YAML frontmatter；唯一的机器账本是 <run>/.teamwork/state.json。

本模块被 orchestrator.py / validate.py / render_diagram.py / selftest.py 共同引用。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = 1
DEFAULT_RUNS_ROOT = Path(
    os.environ.get("TEAMWORK_RUNS_ROOT")
    or (Path.cwd() / "teamwork-runs")
).expanduser()
SKILL_ROOT = Path(__file__).resolve().parent.parent

PHASES = (
    "INIT",
    "CLASSIFY",
    "PLAN",
    "DISPATCH",
    "WORKERS",
    "FINAL",
    "GATE",
    "REVIEW",
    "DREAM",
    "DONE",
)
PHASE_LABEL = {
    "INIT": "初始化",
    "CLASSIFY": "分级",
    "PLAN": "规划",
    "DISPATCH": "派发",
    "WORKERS": "执行",
    "FINAL": "汇总",
    "GATE": "验收",
    "REVIEW": "审核",
    "DREAM": "复盘/做梦",
    "DONE": "完成",
}
PHASE_ROLE = {
    "INIT": "主 Agent",
    "CLASSIFY": "主 Agent",
    "PLAN": "主 Agent",
    "DISPATCH": "主 Agent",
    "WORKERS": "子 Agent（Worker）",
    "FINAL": "主 Agent 或 Final Agent（按等级）",
    "GATE": "主 Agent",
    "REVIEW": "审核 Agent（全新独立子 Agent）",
    "DREAM": "审核 Agent（做梦模式）",
    "DONE": "主 Agent",
}

TIER_RANGES = {"Small": (1, 2), "Medium": (3, 4), "Large": (5, 7)}
TIER_DEFAULT_N = {"Small": 1, "Medium": 2, "Large": 3}
TIER_UPGRADE = {"Small": "Medium", "Medium": "Large", "Large": "Large"}
# S/M 级由主 Agent 直接汇总；L 级才另开全新 Final Agent。
TIER_FINAL_AGENT = {"Small": "main", "Medium": "main", "Large": "subagent"}
# L 级 Worker + Final Agent 合计上限（reviewers 不占用该名额，数量弹性）。
MAX_WORKERS_FINAL_CAP = 8
MAX_REVIEWERS = 26
N_MIN, N_MAX = 1, 10
MAX_REWORK = 2
WORKER_ID_RE = re.compile(r"^w\d{2}$")
POLICY_VERSION_RE = re.compile(r"^v\d+$")

RUBRIC_V0: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "version": "v0",
    "weights": {
        "correctness": 30,
        "completeness": 20,
        "evidence": 20,
        "robustness": 10,
        "maintainability": 10,
        "cost": 10,
    },
    "gates": [
        "unsupported_claims",
        "fabricated_evidence",
        "off_topic",
        "claimed_pass_without_run",
    ],
    "noise_floor": 5,
    "max_edits_per_iteration": 3,
}
DIM_LABELS = {
    "correctness": "正确性",
    "completeness": "完整性",
    "evidence": "证据与可验证性",
    "robustness": "鲁棒性",
    "maintainability": "可维护/可回滚",
    "cost": "成本效率",
}
GATE_LABELS = {
    "unsupported_claims": "无证据断言",
    "fabricated_evidence": "虚构证据",
    "off_topic": "答非所问",
    "claimed_pass_without_run": "未运行却声称通过",
}
VERDICTS = ("PASS", "REVISE", "FAIL")

TEMPLATES = {
    "INIT": [],
    "CLASSIFY": ["classification.md"],
    "PLAN": ["plan.md"],
    "DISPATCH": ["dispatch.md"],
    "WORKERS": ["worker_result.md"],
    "FINAL": ["final_result.md", "run_report.md"],
    "GATE": ["gate.md"],
    "REVIEW": ["review_report.md"],
    "DREAM": ["replay_ledger.md"],
    "DONE": ["final_report.md"],
}


class TeamworkError(Exception):
    """可直接展示给用户的错误（CLI exit 2）。"""


class ValidationFailed(TeamworkError):
    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        self.errors = errors
        self.warnings = warnings or []
        super().__init__("\n".join(errors))


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_slug(text: str, maxlen: int = 18) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text, flags=re.UNICODE)
    slug = re.sub(r"-{2,}", "-", slug).strip("-_")[:maxlen].strip("-_")
    return slug or "task"


# --------------------------------------------------------------------------- #
# 子 Agent 物理命名（每个任务独立命名空间，防止同一对话多任务串用）
# --------------------------------------------------------------------------- #
def agent_name(run_id: str, wid: str) -> str:
    """给 run 内的逻辑 id 生成全局唯一的 durable teammate 名称。

    - 逻辑 id（w01…）只在本 run 的 state/产物里使用；
    - 物理名称带 run 指纹前缀，保证同一对话里多个任务各自的 w01 不会互相覆盖；
    - 返回值符合 teammate 命名要求（lower-kebab-case，<= 63 字符）。
    """
    digest = hashlib.sha1(run_id.encode("utf-8")).hexdigest()[:6]
    return f"tw-{digest}-{wid}"


def final_agent_name(run_id: str) -> str:
    digest = hashlib.sha1(run_id.encode("utf-8")).hexdigest()[:6]
    return f"tw-{digest}-final"


def reviewer_agent_name(run_id: str, letter: str) -> str:
    digest = hashlib.sha1(run_id.encode("utf-8")).hexdigest()[:6]
    return f"tw-{digest}-rev-{letter.lower()}"


def dream_agent_name(run_id: str) -> str:
    digest = hashlib.sha1(run_id.encode("utf-8")).hexdigest()[:6]
    return f"tw-{digest}-dream"


def is_inside(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def rel(run_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(run_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- #
# Markdown frontmatter 读写
# --------------------------------------------------------------------------- #
FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.S
)


def read_artifact(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        raise TeamworkError(f"缺少产物：{path}")
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise TeamworkError(f"{path.name} 缺少 YAML frontmatter（文件必须以 --- 开头）")
    try:
        fm = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise TeamworkError(f"{path.name} 的 frontmatter 不是合法 YAML：{exc}") from exc
    if not isinstance(fm, dict):
        raise TeamworkError(f"{path.name} 的 frontmatter 必须是键值映射")
    return fm, match.group(2)


def write_artifact(path: Path, fm: dict[str, Any], body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = yaml.safe_dump(
        fm, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    text = f"---\n{header}---\n"
    if body and body.strip():
        text += "\n" + body.rstrip() + "\n"
    path.write_text(text, encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------- #
# 命令解析与路径
# --------------------------------------------------------------------------- #
CMD_RE = re.compile(r"^\s*teamwork\s*[,，]\s*N\s*=\s*(\d+|\?)(?=\s|$|[,，:：])", re.IGNORECASE)


def parse_command(text: str) -> tuple[str, str]:
    match = CMD_RE.match(text or "")
    if not match:
        raise TeamworkError(
            "启动命令格式错误：必须以 `teamwork, N=<数字|?>` 开头，"
            "例如 `teamwork, N=2 帮我整理一份报告`"
        )
    token = match.group(1)
    rest = re.sub(r"^[\s,，:：]+", "", text[match.end():])
    return token, rest.strip()


def run_paths(run_dir: Path, iteration: int) -> dict[str, Path]:
    iter_name = f"iter-{iteration:02d}"
    iter_dir = run_dir / "iterations" / iter_name
    workers_dir = iter_dir / "workers"
    return {
        "task": run_dir / "00_intake" / "task.md",
        "classification": run_dir / "00_intake" / "classification.md",
        "plan": run_dir / "01_plans" / f"plan-iter-{iteration:02d}.md",
        "dispatch": run_dir / "01_plans" / f"dispatch-iter-{iteration:02d}.md",
        "iter_dir": iter_dir,
        "workers_dir": workers_dir,
        "final": iter_dir / "final_result.md",
        "run_report": iter_dir / "run_report.md",
        "packet": iter_dir / "review_packet.md",
        "gate": iter_dir / "gate.md",
        "review_a": iter_dir / "review_report_A.md",
        "review_b": iter_dir / "review_report_B.md",
        "scores": iter_dir / "review_scores.md",
        "summary": iter_dir / "iteration_summary.md",
        "policy_dir": run_dir / "review_policy",
        "ledger": run_dir / "review_policy" / "replay_ledger.md",
        "final_report": run_dir / "final_report.md",
        "progress": run_dir / "PROGRESS.md",
        "framework_png": run_dir / "framework.png",
        "framework_mmd": run_dir / "framework.mmd",
        "score_png": run_dir / "score_trend.png",
    }


def worker_result_path(run_dir: Path, iteration: int, worker_id: str) -> Path:
    return run_paths(run_dir, iteration)["workers_dir"] / f"{worker_id}_result.md"


def policy_path(run_dir: Path, version: str) -> Path:
    return run_dir / "review_policy" / f"{version}.md"


def final_agent_mode(tier: str | None) -> str:
    """S/M 级由主 Agent 直接汇总；L 级才启动全新 Final Agent。"""
    return TIER_FINAL_AGENT.get(tier or "", "main")


def phase_role(state: dict[str, Any], phase: str) -> str:
    if phase == "FINAL":
        if final_agent_mode(state.get("tier")) == "subagent":
            return "Final Agent（全新子 Agent）"
        return "主 Agent（直接汇总，不调用子 Agent）"
    return PHASE_ROLE.get(phase, "主 Agent")


def review_letter(index: int) -> str:
    if not 1 <= index <= MAX_REVIEWERS:
        raise TeamworkError(f"评审人数必须在 1–{MAX_REVIEWERS} 之间")
    return chr(ord("A") + index - 1)


def review_report_path(run_dir: Path, iteration: int, letter: str) -> Path:
    return run_paths(run_dir, iteration)["iter_dir"] / f"review_report_{letter}.md"


def state_file(run_dir: Path) -> Path:
    return run_dir / ".teamwork" / "state.json"


def load_state(run_dir: Path) -> dict[str, Any]:
    path = state_file(run_dir)
    if not path.exists():
        raise TeamworkError(f"不是有效的 run 目录（缺少 .teamwork/state.json）：{run_dir}")
    return read_json(path)


def save_state(run_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    save_json(state_file(run_dir), state)


def append_history(state: dict[str, Any], event: str, detail: str = "") -> None:
    state.setdefault("history", []).append(
        {"at": now_iso(), "event": event, "detail": detail}
    )


# --------------------------------------------------------------------------- #
# 校验工具
# --------------------------------------------------------------------------- #
class Check:
    def __init__(self, run_dir: Path, state: dict[str, Any]):
        self.run_dir = run_dir
        self.state = state
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.data: dict[str, Any] = {}

    def err(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def file(self, path: Path, label: str, inside: bool = False) -> bool:
        if not path.exists():
            self.err(f"缺少产物：{label}")
            return False
        if not path.is_file():
            self.err(f"不是文件：{label}")
            return False
        if inside and not is_inside(self.run_dir, path):
            self.err(f"路径越界（必须位于 run 目录内）：{label}")
            return False
        return True

    def artifact(
        self, path: Path, label: str, inside: bool = False
    ) -> tuple[dict[str, Any], str] | None:
        if not self.file(path, label, inside=inside):
            return None
        try:
            return read_artifact(path)
        except TeamworkError as exc:
            self.err(str(exc))
            return None

    def ref_path(
        self,
        raw: Any,
        label: str,
        inside: bool = True,
        must_exist: bool = True,
    ) -> Path | None:
        if not isinstance(raw, str) or not raw.strip():
            self.err(f"{label}：路径必须是非空字符串")
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = self.run_dir / path
        if inside and not is_inside(self.run_dir, path):
            self.err(f"{label}：路径越界（必须位于 run 目录内）：{raw}")
            return None
        if must_exist and not path.exists():
            self.err(f"{label}：引用的文件不存在：{raw}")
            return None
        return path


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def f_str(
    check: Check,
    fm: dict[str, Any],
    key: str,
    where: str,
    *,
    required: bool = True,
    allow_empty: bool = False,
) -> str | None:
    if key not in fm:
        if required:
            check.err(f"{where}：frontmatter 缺少字段 `{key}`")
        return None
    value = fm[key]
    if not isinstance(value, str):
        check.err(f"{where}：`{key}` 必须是字符串")
        return None
    if not allow_empty and not value.strip():
        check.err(f"{where}：`{key}` 不能为空")
        return None
    return value


def f_int(
    check: Check,
    fm: dict[str, Any],
    key: str,
    where: str,
    *,
    lo: int | None = None,
    hi: int | None = None,
    required: bool = True,
) -> int | None:
    if key not in fm:
        if required:
            check.err(f"{where}：frontmatter 缺少字段 `{key}`")
        return None
    value = fm[key]
    if not _is_int(value):
        check.err(f"{where}：`{key}` 必须是整数")
        return None
    if lo is not None and value < lo:
        check.err(f"{where}：`{key}` 不能小于 {lo}")
    if hi is not None and value > hi:
        check.err(f"{where}：`{key}` 不能大于 {hi}")
    return value


def f_bool(
    check: Check, fm: dict[str, Any], key: str, where: str, *, required: bool = True
) -> bool | None:
    if key not in fm:
        if required:
            check.err(f"{where}：frontmatter 缺少字段 `{key}`")
        return None
    value = fm[key]
    if not isinstance(value, bool):
        check.err(f"{where}：`{key}` 必须是布尔值")
        return None
    return value


def f_enum(
    check: Check,
    fm: dict[str, Any],
    key: str,
    where: str,
    allowed: tuple[str, ...] | list[str],
    *,
    required: bool = True,
) -> str | None:
    value = f_str(check, fm, key, where, required=required)
    if value is None:
        return None
    if value not in allowed:
        check.err(f"{where}：`{key}` 必须是 {'/'.join(allowed)} 之一（当前 `{value}`）")
        return None
    return value


def f_list(
    check: Check,
    fm: dict[str, Any],
    key: str,
    where: str,
    *,
    min_len: int = 0,
    required: bool = True,
) -> list[Any] | None:
    if key not in fm:
        if required:
            check.err(f"{where}：frontmatter 缺少字段 `{key}`")
        return None
    value = fm[key]
    if not isinstance(value, list):
        check.err(f"{where}：`{key}` 必须是列表")
        return None
    if len(value) < min_len:
        check.err(f"{where}：`{key}` 至少需要 {min_len} 项（当前 {len(value)} 项）")
    return value


def f_dict(
    check: Check,
    fm: dict[str, Any],
    key: str,
    where: str,
    *,
    required: bool = True,
) -> dict[str, Any] | None:
    if key not in fm:
        if required:
            check.err(f"{where}：frontmatter 缺少字段 `{key}`")
        return None
    value = fm[key]
    if not isinstance(value, dict):
        check.err(f"{where}：`{key}` 必须是映射")
        return None
    return value


def f_sha(
    check: Check,
    fm: dict[str, Any],
    key: str,
    where: str,
    path: Path | None,
    *,
    required: bool = False,
) -> None:
    if key not in fm:
        if required:
            check.err(f"{where}：frontmatter 缺少字段 `{key}`")
        return
    value = fm[key]
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        check.err(f"{where}：`{key}` 必须是 64 位十六进制 sha256")
        return
    if path is not None and path.is_file():
        actual = sha256_file(path)
        if actual != value.lower():
            check.err(f"{where}：`{key}` 与文件实际内容不匹配（实际 {actual[:12]}…）")


def validate_body(check: Check, body: str, label: str) -> None:
    if not body or not body.strip():
        check.err(f"{label}：Markdown 正文不能为空")


# --------------------------------------------------------------------------- #
# 各阶段校验
# --------------------------------------------------------------------------- #
def validate_task(check: Check) -> None:
    paths = run_paths(check.run_dir, check.state["current_iter"])
    got = check.artifact(paths["task"], "00_intake/task.md", inside=True)
    if not got:
        return
    fm, body = got
    where = "task.md"
    f_int(check, fm, "schema_version", where, lo=SCHEMA_VERSION, hi=SCHEMA_VERSION)
    f_str(check, fm, "command", where)
    f_str(check, fm, "task", where)
    f_str(check, fm, "created_at", where)
    validate_body(check, body, where)


def validate_classification(check: Check) -> None:
    paths = run_paths(check.run_dir, check.state["current_iter"])
    got = check.artifact(paths["classification"], "00_intake/classification.md", inside=True)
    if not got:
        return
    fm, body = got
    where = "classification.md"
    f_int(check, fm, "schema_version", where, lo=SCHEMA_VERSION, hi=SCHEMA_VERSION)
    tier = f_enum(check, fm, "tier", where, tuple(TIER_RANGES))
    f_str(check, fm, "tier_reason", where)
    signals = f_dict(check, fm, "signals", where)
    if signals is not None:
        expected = {
            "files": int,
            "external": bool,
            "verifiable": bool,
            "parallel": bool,
            "risk": str,
            "user_demand": bool,
        }
        for key, typ in expected.items():
            if key not in signals:
                check.err(f"{where}：signals 缺少 `{key}`")
            elif typ is int and not _is_int(signals[key]):
                check.err(f"{where}：signals.{key} 必须是整数")
            elif typ is bool and not isinstance(signals[key], bool):
                check.err(f"{where}：signals.{key} 必须是布尔值")
        risk = signals.get("risk")
        if isinstance(risk, str) and risk not in ("low", "medium", "high"):
            check.err(f"{where}：signals.risk 只能是 low/medium/high")
    adjust = f_int(check, fm, "n_adjust", where, lo=-1, hi=1)
    reason = fm.get("n_reason", "")
    if adjust not in (0, None) and not (isinstance(reason, str) and reason.strip()):
        check.err(f"{where}：n_adjust 不为 0 时必须写 `n_reason`")
    if tier:
        lo, hi = TIER_RANGES[tier]
        workers = f_int(check, fm, "workers_planned", where, lo=lo, hi=hi)
        check.data["workers_planned"] = workers
    f_bool(check, fm, "user_confirmed", where, required=False)
    validate_body(check, body, where)


def validate_plan(check: Check) -> None:
    iteration = check.state["current_iter"]
    paths = run_paths(check.run_dir, iteration)
    got = check.artifact(paths["plan"], f"01_plans/plan-iter-{iteration:02d}.md", inside=True)
    if not got:
        return
    fm, body = got
    where = f"plan-iter-{iteration:02d}.md"
    f_int(check, fm, "schema_version", where, lo=SCHEMA_VERSION, hi=SCHEMA_VERSION)
    f_int(check, fm, "iteration", where, lo=iteration, hi=iteration)
    tier = f_enum(check, fm, "tier", where, tuple(TIER_RANGES))
    f_str(check, fm, "objective", where)
    breakdown = f_list(check, fm, "breakdown", where, min_len=1)
    if breakdown:
        for idx, item in enumerate(breakdown, 1):
            if not isinstance(item, dict):
                check.err(f"{where}：breakdown 第 {idx} 项必须是映射")
                continue
            if not item.get("desc"):
                check.err(f"{where}：breakdown 第 {idx} 项缺少 desc")
            assignee = item.get("assignee")
            if not isinstance(assignee, str) or not (
                assignee == "main" or WORKER_ID_RE.match(assignee)
            ):
                check.err(f"{where}：breakdown 第 {idx} 项 assignee 必须是 wNN 或 main")
    f_list(check, fm, "accepted_criteria", where, min_len=1)
    risks = f_list(check, fm, "risks", where)
    worker_count = f_int(check, fm, "worker_count", where, lo=1, hi=8)
    if tier:
        lo, hi = TIER_RANGES[tier]
        if worker_count is not None and not (lo <= worker_count <= hi):
            check.err(f"{where}：{tier} 的 worker_count 必须在 {lo}–{hi}")
        if tier == "Large":
            f_list(check, fm, "alternatives", where, min_len=2)
            if risks is not None and len(risks) < 1:
                check.err(f"{where}：Large 任务至少写 1 条 risk")
        if tier == "Medium" and risks is not None and len(risks) < 1:
            check.err(f"{where}：Medium 任务至少写 1 条 risk")
    validate_body(check, body, where)


def validate_dispatch(check: Check) -> None:
    iteration = check.state["current_iter"]
    paths = run_paths(check.run_dir, iteration)
    got = check.artifact(paths["dispatch"], f"01_plans/dispatch-iter-{iteration:02d}.md", inside=True)
    if not got:
        return
    fm, body = got
    where = f"dispatch-iter-{iteration:02d}.md"
    f_int(check, fm, "schema_version", where, lo=SCHEMA_VERSION, hi=SCHEMA_VERSION)
    f_int(check, fm, "iteration", where, lo=iteration, hi=iteration)
    mode = f_enum(check, fm, "mode", where, ("parallel", "staged"))
    workers = f_list(check, fm, "workers", where, min_len=1)
    tier = check.state.get("tier")
    if workers is not None:
        if tier:
            lo, hi = TIER_RANGES[tier]
            if not (lo <= len(workers) <= hi):
                check.err(f"{where}：{tier} 的 worker 数必须在 {lo}–{hi}（当前 {len(workers)}）")
        ids: list[str] = []
        for idx, item in enumerate(workers, 1):
            if not isinstance(item, dict):
                check.err(f"{where}：workers 第 {idx} 项必须是映射")
                continue
            wid = item.get("id")
            if not isinstance(wid, str) or not WORKER_ID_RE.match(wid):
                check.err(f"{where}：workers 第 {idx} 项 id 必须是 wNN")
                continue
            if wid in ids:
                check.err(f"{where}：worker id 重复：{wid}")
            ids.append(wid)
            if not isinstance(item.get("scope"), str) or not item["scope"].strip():
                check.err(f"{where}：{wid} 缺少 scope")
            deliverables = item.get("deliverables")
            if not isinstance(deliverables, list) or not deliverables:
                check.err(f"{where}：{wid} 缺少 deliverables")
            else:
                for raw in deliverables:
                    if not isinstance(raw, str) or not raw.strip():
                        check.err(f"{where}：{wid} 的 deliverables 必须是非空路径字符串")
                    elif Path(raw).is_absolute():
                        check.err(f"{where}：{wid} 的 deliverables 必须写 run 内相对路径：{raw}")
            if not isinstance(item.get("acceptance"), str) or not item["acceptance"].strip():
                check.err(f"{where}：{wid} 缺少 acceptance")
        if mode == "staged":
            deps = fm.get("dependencies")
            if not isinstance(deps, list):
                check.err(f"{where}：staged 模式需要 dependencies 列表")
            else:
                for dep in deps:
                    if not isinstance(dep, dict) or dep.get("worker") not in ids:
                        check.err(f"{where}：dependencies 出现未知 worker")
        else:
            deps = fm.get("dependencies")
            if isinstance(deps, list) and deps:
                check.err(f"{where}：parallel 模式不应有 dependencies")
        if tier in ("Small", "Medium") and iteration > 1:
            registry = set((check.state.get("workers") or {}).get("registry") or {})
            fresh = [wid for wid in ids if wid not in registry]
            if fresh:
                check.warn(
                    f"{where}：{tier} 级任务建议复用已有 worker；本轮新增 {', '.join(fresh)}"
                )
        if tier:
            previous = set((check.state.get("workers") or {}).get("registry") or {})
            union = sorted(previous | set(ids))
            task_cap = TIER_RANGES[tier][1]
            if len(union) > task_cap:
                final_note = "（L 级 Worker + Final Agent 合计上限 8）" if tier == "Large" else ""
                check.err(
                    f"{where}：本任务（run）累计 Worker 数不得超过 {task_cap} 个{final_note}；"
                    f"当前累计 {len(union)} 个：{', '.join(union)}。"
                    "人数上限只按单个任务（单个 run）计数——同一对话/上下文里的多个任务各自独立计数、互不占用。"
                )
        check.data["worker_ids"] = ids
    validate_body(check, body, where)


def validate_worker_results(check: Check) -> None:
    iteration = check.state["current_iter"]
    paths = run_paths(check.run_dir, iteration)
    dispatch = check.artifact(
        paths["dispatch"], f"01_plans/dispatch-iter-{iteration:02d}.md", inside=True
    )
    if not dispatch:
        return
    fm, _ = dispatch
    workers = fm.get("workers") or []
    ids = [w.get("id") for w in workers if isinstance(w, dict) and w.get("id")]
    for wid in ids:
        result_path = worker_result_path(check.run_dir, iteration, wid)
        got = check.artifact(result_path, rel(check.run_dir, result_path), inside=True)
        if not got:
            continue
        rfm, body = got
        where = f"{wid}_result.md"
        f_int(check, rfm, "schema_version", where, lo=SCHEMA_VERSION, hi=SCHEMA_VERSION)
        f_str(check, rfm, "worker_id", where)
        if rfm.get("worker_id") != wid:
            check.err(f"{where}：worker_id 必须等于 {wid}")
        f_int(check, rfm, "iteration", where, lo=iteration, hi=iteration)
        f_str(check, rfm, "scope", where)
        status = f_enum(check, rfm, "status", where, ("completed", "failed", "blocked"))
        deliverables = f_list(check, rfm, "deliverables", where, min_len=0)
        if status == "completed" and deliverables is not None and len(deliverables) < 1:
            check.err(f"{where}：completed 状态至少要有 1 个 deliverable")
        if deliverables:
            for item in deliverables:
                if not isinstance(item, dict):
                    check.err(f"{where}：deliverables 每项必须是映射")
                    continue
                path = check.ref_path(item.get("path"), f"{where} deliverables", inside=True)
                f_sha(check, item, "sha256", f"{where} deliverables", path)
        claims = f_list(check, rfm, "claims", where, min_len=0)
        if status == "completed" and claims is not None and len(claims) < 1:
            check.err(f"{where}：completed 状态至少要有 1 条 claim")
        if claims:
            for idx, claim in enumerate(claims, 1):
                if not isinstance(claim, dict):
                    check.err(f"{where}：claims 第 {idx} 项必须是映射")
                    continue
                if not isinstance(claim.get("text"), str) or not claim["text"].strip():
                    check.err(f"{where}：claims 第 {idx} 项缺少 text")
                evidence = claim.get("evidence")
                if not isinstance(evidence, list) or not evidence:
                    check.err(f"{where}：claims 第 {idx} 项必须有 evidence（证据路径）")
                else:
                    for ev in evidence:
                        if isinstance(ev, str) and ev.strip().lower().startswith(("http://", "https://")):
                            # 外部网络证据：允许以 URL 形式登记，不参与本地路径存在性校验。
                            continue
                        check.ref_path(ev, f"{where} claim {idx} evidence", inside=False)
        f_list(check, rfm, "open_questions", where)
        f_enum(check, rfm, "confidence", where, ("high", "medium", "low"))
        validate_body(check, body, where)


def validate_final(check: Check) -> None:
    iteration = check.state["current_iter"]
    paths = run_paths(check.run_dir, iteration)
    final = check.artifact(paths["final"], rel(check.run_dir, paths["final"]), inside=True)
    if final:
        fm, body = final
        where = "final_result.md"
        f_int(check, fm, "schema_version", where, lo=SCHEMA_VERSION, hi=SCHEMA_VERSION)
        f_int(check, fm, "iteration", where, lo=iteration, hi=iteration)
        f_str(check, fm, "summary", where)
        deliverables = f_list(check, fm, "deliverables", where, min_len=1)
        if deliverables:
            for item in deliverables:
                if not isinstance(item, dict):
                    check.err(f"{where}：deliverables 每项必须是映射")
                    continue
                path = check.ref_path(item.get("path"), f"{where} deliverables", inside=True)
                f_sha(check, item, "sha256", f"{where} deliverables", path)
        coverage = f_list(check, fm, "coverage", where, min_len=1)
        if coverage:
            for idx, item in enumerate(coverage, 1):
                if not isinstance(item, dict):
                    check.err(f"{where}：coverage 第 {idx} 项必须是映射")
                    continue
                for key in ("requirement", "where"):
                    if not isinstance(item.get(key), str) or not item[key].strip():
                        check.err(f"{where}：coverage 第 {idx} 项缺少 {key}")
                if item.get("status") not in ("covered", "partial", "missing"):
                    check.err(f"{where}：coverage 第 {idx} 项 status 必须是 covered/partial/missing")
        f_list(check, fm, "unresolved", where)
        delivery = fm.get("delivery")
        if delivery is not None:
            if not isinstance(delivery, list):
                check.err(f"{where}：delivery 必须是列表")
            else:
                for idx, item in enumerate(delivery, 1):
                    if not isinstance(item, dict):
                        check.err(f"{where}：delivery 第 {idx} 项必须是映射")
                        continue
                    raw = item.get("path")
                    if not isinstance(raw, str) or not raw.strip():
                        check.err(f"{where}：delivery 第 {idx} 项缺少 path")
                        continue
                    target = Path(raw)
                    if not target.is_absolute():
                        target = check.run_dir / target
                    if not target.is_file():
                        check.err(f"{where}：delivery 指定的落盘文件不存在：{raw}")
                        continue
                    f_sha(
                        check,
                        item,
                        "sha256",
                        f"{where} delivery",
                        target,
                        required=True,
                    )
        validate_body(check, body, where)

    report = check.artifact(paths["run_report"], rel(check.run_dir, paths["run_report"]), inside=True)
    if report:
        fm, body = report
        where = "run_report.md"
        f_int(check, fm, "schema_version", where, lo=SCHEMA_VERSION, hi=SCHEMA_VERSION)
        f_int(check, fm, "iteration", where, lo=iteration, hi=iteration)
        f_enum(check, fm, "tier", where, tuple(TIER_RANGES))
        f_int(check, fm, "workers", where, lo=1, hi=8)
        f_list(check, fm, "highlights", where, min_len=1)
        f_list(check, fm, "issues", where)
        f_list(check, fm, "next_suggestions", where)
        validate_body(check, body, where)

    packet = check.artifact(paths["packet"], rel(check.run_dir, paths["packet"]), inside=True)
    if packet:
        fm, body = packet
        where = "review_packet.md"
        f_int(check, fm, "schema_version", where, lo=SCHEMA_VERSION, hi=SCHEMA_VERSION)
        f_int(check, fm, "iteration", where, lo=iteration, hi=iteration)
        f_enum(check, fm, "tier", where, tuple(TIER_RANGES))
        f_str(check, fm, "task", where)
        f_list(check, fm, "acceptance", where, min_len=1)
        f_str(check, fm, "rubric_version", where)
        reviewers = f_int(check, fm, "reviewers", where, lo=1, hi=MAX_REVIEWERS)
        expected_reviewers = check.state.get("review", {}).get("reviewers", 1)
        if reviewers is not None and reviewers != expected_reviewers:
            check.err(f"{where}：reviewers={reviewers} 与当前配置 {expected_reviewers} 不一致")
        artifacts = f_list(check, fm, "artifacts", where, min_len=1)
        if artifacts:
            for item in artifacts:
                if not isinstance(item, dict):
                    check.err(f"{where}：artifacts 每项必须是映射")
                    continue
                path = check.ref_path(item.get("path"), f"{where} artifacts", inside=True)
                f_sha(check, item, "sha256", f"{where} artifacts", path, required=True)
                if "run_report" in str(item.get("path", "")):
                    check.err(f"{where}：review packet 不得包含 run_report（会破坏评审独立性）")
        forbidden = f_list(check, fm, "forbidden", where, min_len=1)
        if forbidden:
            joined = " ".join(str(x) for x in forbidden)
            for must in ("run_report", "state.json"):
                if must not in joined:
                    check.err(f"{where}：forbidden 必须包含 {must}")
        validate_body(check, body, where)


def validate_gate(check: Check) -> None:
    iteration = check.state["current_iter"]
    paths = run_paths(check.run_dir, iteration)
    got = check.artifact(paths["gate"], rel(check.run_dir, paths["gate"]), inside=True)
    if not got:
        return
    fm, body = got
    where = "gate.md"
    f_int(check, fm, "schema_version", where, lo=SCHEMA_VERSION, hi=SCHEMA_VERSION)
    f_int(check, fm, "iteration", where, lo=iteration, hi=iteration)
    verdict = f_enum(check, fm, "verdict", where, ("PASS", "REWORK"))
    checklist = f_list(check, fm, "checklist", where, min_len=1)
    if checklist:
        for idx, item in enumerate(checklist, 1):
            if not isinstance(item, dict):
                check.err(f"{where}：checklist 第 {idx} 项必须是映射")
                continue
            if not item.get("item"):
                check.err(f"{where}：checklist 第 {idx} 项缺少 item")
            if not isinstance(item.get("pass"), bool):
                check.err(f"{where}：checklist 第 {idx} 项 pass 必须是布尔值")
    targets = f_list(check, fm, "rework_targets", where)
    dispatch = check.artifact(
        paths["dispatch"], f"01_plans/dispatch-iter-{iteration:02d}.md", inside=True
    )
    ids: list[str] = []
    if dispatch:
        ids = [w.get("id") for w in (dispatch[0].get("workers") or []) if isinstance(w, dict)]
    if verdict == "REWORK":
        if not targets:
            check.err(f"{where}：REWORK 必须给 rework_targets")
        else:
            for target in targets:
                if ids and target not in ids:
                    check.err(f"{where}：rework_targets 出现未知 worker：{target}")
    f_str(check, fm, "note", where, allow_empty=False)
    check.data["gate_verdict"] = verdict
    if body.strip() == "":
        check.warn(f"{where}：正文为空（建议写验收说明）")


def compute_review(fm: dict[str, Any], rubric: dict[str, Any]) -> dict[str, Any]:
    weights = rubric["weights"]
    dims = fm.get("dimensions") or []
    by_name = {
        d.get("name"): d for d in dims if isinstance(d, dict) and isinstance(d.get("name"), str)
    }
    missing = [name for name in weights if name not in by_name]
    extra = [name for name in by_name if name not in weights]
    gate_failures = [g for g in (fm.get("gates_triggered") or []) if g in rubric["gates"]]
    total = 0.0
    for name, weight in weights.items():
        dim = by_name.get(name) or {}
        score = dim.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            total += float(score) * float(weight) / 100.0
    total_int = int(round(total))
    if gate_failures or total_int < 60:
        verdict = "FAIL"
    elif total_int < 85:
        verdict = "REVISE"
    else:
        verdict = "PASS"
    return {
        "total": total_int,
        "verdict": verdict,
        "gate_failures": gate_failures,
        "missing": missing,
        "extra": extra,
    }


def validate_review_report(
    check: Check, path: Path, reviewer: str, rubric: dict[str, Any], expected_version: str
) -> dict[str, Any] | None:
    got = check.artifact(path, rel(check.run_dir, path), inside=True)
    if not got:
        return None
    fm, body = got
    where = path.name
    f_int(check, fm, "schema_version", where, lo=SCHEMA_VERSION, hi=SCHEMA_VERSION)
    f_str(check, fm, "reviewer", where)
    if fm.get("reviewer") != reviewer:
        check.err(f"{where}：reviewer 必须是 {reviewer}")
    f_int(check, fm, "iteration", where, lo=check.state["current_iter"], hi=check.state["current_iter"])
    f_str(check, fm, "rubric_version", where)
    if fm.get("rubric_version") != expected_version:
        check.err(f"{where}：rubric_version 必须是 {expected_version}")
    inputs = f_list(check, fm, "inputs_read", where, min_len=1)
    if inputs:
        joined = " ".join(str(x) for x in inputs)
        for leaked in ("run_report", "state.json", "iteration_summary", "review_report"):
            if leaked in joined:
                check.err(f"{where}：评审读了禁止输入 `{leaked}`（评审必须独立）")
    if f_bool(check, fm, "independence_attestation", where) is not True:
        check.err(f"{where}：independence_attestation 必须为 true")
    dims = f_list(check, fm, "dimensions", where, min_len=len(RUBRIC_V0["weights"]))
    if dims:
        for idx, item in enumerate(dims, 1):
            if not isinstance(item, dict):
                check.err(f"{where}：dimensions 第 {idx} 项必须是映射")
                continue
            name = item.get("name")
            if name not in RUBRIC_V0["weights"]:
                check.err(f"{where}：未知评分维度 `{name}`")
                continue
            if item.get("weight") != RUBRIC_V0["weights"][name]:
                check.err(f"{where}：维度 {name} 的 weight 必须是 {RUBRIC_V0['weights'][name]}")
            score = item.get("score")
            if not _is_int(score) or not (0 <= score <= 100):
                check.err(f"{where}：维度 {name} 的 score 必须是 0–100 整数")
            ev = item.get("evidence")
            if not isinstance(ev, list) or not ev:
                check.err(f"{where}：维度 {name} 必须有 evidence")
            else:
                for raw in ev:
                    if isinstance(raw, str) and raw.strip().lower().startswith(("http://", "https://")):
                        # 外部网络证据：允许 URL，不校验本地存在性。
                        continue
                    check.ref_path(raw, f"{where} {name} evidence", inside=False)
    f_list(check, fm, "gates_triggered", where)
    f_list(check, fm, "errors", where)
    f_list(check, fm, "optimizations", where)
    f_int(check, fm, "total", where, lo=0, hi=100)
    f_enum(check, fm, "verdict", where, VERDICTS)
    computed = compute_review(fm, rubric)
    for miss in computed["missing"]:
        check.err(f"{where}：缺少维度 {miss}")
    for extra in computed["extra"]:
        check.err(f"{where}：多出未知维度 {extra}")
    if isinstance(fm.get("total"), int) and fm["total"] != computed["total"]:
        check.err(
            f"{where}：total 与加权计算不一致（写的 {fm.get('total')}，应算得 {computed['total']}）"
        )
    if fm.get("verdict") != computed["verdict"]:
        check.err(
            f"{where}：verdict 与规则不一致（写的 {fm.get('verdict')}，应为 {computed['verdict']}）"
        )
    check.data.setdefault("reviews", {})[reviewer] = {
        "fm": fm,
        "computed": computed,
        "body": body,
    }
    validate_body(check, body, where)
    return fm


def load_rubric(run_dir: Path, version: str) -> dict[str, Any]:
    if version == "v0":
        return dict(RUBRIC_V0)
    path = policy_path(run_dir, version)
    if not path.exists():
        raise TeamworkError(f"找不到审核策略文件：{rel(run_dir, path)}")
    fm, _ = read_artifact(path)
    return fm


def validate_policy(check: Check, version: str) -> None:
    path = policy_path(check.run_dir, version)
    got = check.artifact(path, rel(check.run_dir, path), inside=True)
    if not got:
        return
    fm, body = got
    where = f"{version}.md"
    f_int(check, fm, "schema_version", where, lo=SCHEMA_VERSION, hi=SCHEMA_VERSION)
    if fm.get("version") != version:
        check.err(f"{where}：version 必须是 {version}")
    weights = f_dict(check, fm, "weights", where)
    if weights is not None:
        if set(weights) != set(RUBRIC_V0["weights"]):
            check.err(f"{where}：weights 必须恰好包含六个维度")
        if sum(v for v in weights.values() if isinstance(v, int)) != 100:
            check.err(f"{where}：weights 之和必须为 100")
    gates = f_list(check, fm, "gates", where, min_len=1)
    if gates is not None and set(gates) != set(RUBRIC_V0["gates"]):
        check.err(f"{where}：gates 不允许增删（只能调整文字口径）")
    f_int(check, fm, "noise_floor", where, lo=0, hi=30)
    f_int(check, fm, "max_edits_per_iteration", where, lo=1, hi=10)
    validate_body(check, body, where)


def validate_review_phase(check: Check) -> None:
    iteration = check.state["current_iter"]
    paths = run_paths(check.run_dir, iteration)
    reviewers = int(check.state.get("review", {}).get("reviewers", 1))
    version = check.state.get("review", {}).get("policy_version", "v0")
    rubric = load_rubric(check.run_dir, version)
    packet = check.artifact(paths["packet"], rel(check.run_dir, paths["packet"]), inside=True)
    if not packet:
        return
    packet_fm, _ = packet
    if packet_fm.get("rubric_version") != version:
        check.err(f"review_packet.md：rubric_version 必须是 {version}")
    for idx in range(1, reviewers + 1):
        letter = review_letter(idx)
        validate_review_report(
            check,
            review_report_path(check.run_dir, iteration, letter),
            letter,
            rubric,
            version,
        )


def validate_scores(check: Check, merged: dict[str, Any]) -> None:
    iteration = check.state["current_iter"]
    paths = run_paths(check.run_dir, iteration)
    got = check.artifact(paths["scores"], rel(check.run_dir, paths["scores"]), inside=True)
    if not got:
        return
    fm, body = got
    where = "review_scores.md"
    f_int(check, fm, "schema_version", where, lo=SCHEMA_VERSION, hi=SCHEMA_VERSION)
    f_int(check, fm, "iteration", where, lo=iteration, hi=iteration)
    f_int(check, fm, "merged_total", where, lo=0, hi=100)
    f_enum(check, fm, "merged_verdict", where, VERDICTS)
    if fm.get("merged_total") != merged["total"]:
        check.err(f"{where}：merged_total 与评审报告不一致")
    if fm.get("merged_verdict") != merged["verdict"]:
        check.err(f"{where}：merged_verdict 与规则不一致")
    validate_body(check, body, where)


def validate_dream(check: Check) -> None:
    iteration = check.state["current_iter"]
    paths = run_paths(check.run_dir, iteration)
    got = check.artifact(paths["ledger"], rel(check.run_dir, paths["ledger"]), inside=True)
    if not got:
        return
    fm, body = got
    where = "replay_ledger.md"
    f_int(check, fm, "schema_version", where, lo=SCHEMA_VERSION, hi=SCHEMA_VERSION)
    entries = f_list(check, fm, "entries", where, min_len=1)
    entry = None
    if entries:
        for item in entries:
            if isinstance(item, dict) and item.get("iteration") == iteration:
                entry = item
        if entry is None:
            check.err(f"{where}：缺少第 {iteration} 轮的 entries 记录")
    if entry:
        current_version = check.state.get("review", {}).get("policy_version", "v0")
        if entry.get("policy_before") != current_version:
            check.err(f"{where}：policy_before 必须等于当前策略 {current_version}")
        candidates = entry.get("candidates") or []
        if not isinstance(candidates, list) or not (1 <= len(candidates) <= 3):
            check.err(f"{where}：candidates 需要 1–3 个")
        decision = entry.get("decision")
        if decision not in ("promote", "keep"):
            check.err(f"{where}：decision 必须是 promote/keep")
        after = entry.get("policy_after")
        if decision == "promote":
            if not isinstance(after, str) or not POLICY_VERSION_RE.match(after):
                check.err(f"{where}：promote 时 policy_after 必须是 vN")
            elif after == current_version:
                check.err(f"{where}：promote 时 policy_after 必须不同于 policy_before")
            else:
                validate_policy(check, after)
        elif decision == "keep" and after != current_version:
            check.err(f"{where}：keep 时 policy_after 必须等于 policy_before")
        if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            check.err(f"{where}：必须写 reason")
    validate_body(check, body, where)


def validate_final_report(check: Check) -> None:
    paths = run_paths(check.run_dir, check.state["current_iter"])
    got = check.artifact(paths["final_report"], "final_report.md", inside=True)
    if not got:
        return
    fm, body = got
    where = "final_report.md"
    f_int(check, fm, "schema_version", where, lo=SCHEMA_VERSION, hi=SCHEMA_VERSION)
    f_str(check, fm, "run", where)
    f_enum(check, fm, "tier", where, tuple(TIER_RANGES))
    f_int(check, fm, "iterations", where, lo=1, hi=N_MAX)
    trajectory = f_list(check, fm, "trajectory", where, min_len=1)
    if trajectory:
        for idx, item in enumerate(trajectory, 1):
            if not isinstance(item, dict):
                check.err(f"{where}：trajectory 第 {idx} 项必须是映射")
                continue
            if not _is_int(item.get("iteration")):
                check.err(f"{where}：trajectory 第 {idx} 项缺少 iteration")
            if not _is_int(item.get("total")):
                check.err(f"{where}：trajectory 第 {idx} 项缺少 total")
            if item.get("verdict") not in VERDICTS:
                check.err(f"{where}：trajectory 第 {idx} 项 verdict 非法")
    f_str(check, fm, "outcome", where)
    validate_body(check, body, where)


def validate_phase(check: Check) -> None:
    phase = check.state["phase"]
    if phase == "INIT":
        validate_task(check)
    elif phase == "CLASSIFY":
        validate_classification(check)
    elif phase == "PLAN":
        validate_plan(check)
    elif phase == "DISPATCH":
        validate_dispatch(check)
    elif phase == "WORKERS":
        validate_worker_results(check)
    elif phase == "FINAL":
        validate_final(check)
    elif phase == "GATE":
        validate_gate(check)
    elif phase == "REVIEW":
        validate_review_phase(check)
    elif phase == "DREAM":
        validate_dream(check)
    elif phase == "DONE":
        validate_final_report(check)
    else:
        check.err(f"未知阶段：{phase}")


# --------------------------------------------------------------------------- #
# 评分合成 / review packet
# --------------------------------------------------------------------------- #
def compute_merged_review(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    iteration = state["current_iter"]
    paths = run_paths(run_dir, iteration)
    version = state.get("review", {}).get("policy_version", "v0")
    rubric = load_rubric(run_dir, version)
    reviewers = int(state.get("review", {}).get("reviewers", 1))
    reports: dict[str, dict[str, Any]] = {}
    for idx in range(1, reviewers + 1):
        reviewer = review_letter(idx)
        path = review_report_path(run_dir, iteration, reviewer)
        fm, _ = read_artifact(path)
        computed = compute_review(fm, rubric)
        reports[reviewer] = {
            "id": reviewer,
            "total": computed["total"],
            "verdict": computed["verdict"],
            "gate_failures": computed["gate_failures"],
            "dimensions": {
                d.get("name"): int(d.get("score", 0))
                for d in (fm.get("dimensions") or [])
                if isinstance(d, dict)
            },
        }
    totals = [r["total"] for r in reports.values()]
    merged_total = int(round(sum(totals) / len(totals))) if totals else 0
    if any(r["verdict"] == "FAIL" for r in reports.values()):
        merged_verdict = "FAIL"
    elif merged_total < 60:
        merged_verdict = "FAIL"
    elif merged_total < 85:
        merged_verdict = "REVISE"
    else:
        merged_verdict = "PASS"
    disagreements: list[dict[str, Any]] = []
    if len(reports) >= 2:
        for name in RUBRIC_V0["weights"]:
            scored = [
                (r["id"], r["dimensions"].get(name, 0)) for r in reports.values()
            ]
            values = [value for _, value in scored]
            delta = max(values) - min(values)
            if delta > 10:
                spread = " / ".join(f"{rid}={value}" for rid, value in scored)
                disagreements.append(
                    {"dimension": name, "delta": delta, "detail": spread}
                )
    gate_failures = sorted({g for r in reports.values() for g in r["gate_failures"]})
    return {
        "iteration": iteration,
        "rubric_version": version,
        "reviewers": [
            {"id": r["id"], "total": r["total"], "verdict": r["verdict"]}
            for r in reports.values()
        ],
        "merged_total": merged_total,
        "merged_verdict": merged_verdict,
        "gate_failures": gate_failures,
        "disagreements": disagreements,
    }


def write_scores(run_dir: Path, merged: dict[str, Any]) -> Path:
    paths = run_paths(run_dir, merged["iteration"])
    fm = {"schema_version": SCHEMA_VERSION, **merged}
    rows = "\n".join(
        f"| {r['id']} | {r['total']} | {r['verdict']} |" for r in merged["reviewers"]
    )
    body = (
        "# 评审合成\n\n"
        f"- rubric：{merged['rubric_version']}\n"
        f"- 合成总分：**{merged['merged_total']}** · 结论：**{merged['merged_verdict']}**\n"
        f"- 一票否决项：{', '.join(merged['gate_failures']) or '无'}\n"
        f"- 评审分歧：{merged['disagreements'] or '无'}\n\n"
        "| 评审 | 总分 | 结论 |\n|---|---|---|\n" + rows + "\n"
    )
    write_artifact(paths["scores"], fm, body)
    return paths["scores"]


def make_review_packet(run_dir: Path, state: dict[str, Any]) -> Path:
    iteration = state["current_iter"]
    paths = run_paths(run_dir, iteration)
    final_fm, _ = read_artifact(paths["final"])
    dispatch_fm, _ = read_artifact(paths["dispatch"])
    task_fm, _ = read_artifact(paths["task"])
    plan_fm, _ = read_artifact(paths["plan"])
    rubric_version = state.get("review", {}).get("policy_version", "v0")
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(raw_path: Path, producer: str) -> None:
        key = str(raw_path.resolve())
        if key in seen or not raw_path.is_file():
            return
        seen.add(key)
        artifacts.append(
            {
                "path": rel(run_dir, raw_path),
                "sha256": sha256_file(raw_path),
                "producer": producer,
            }
        )

    add(paths["final"], "final-agent")
    for item in final_fm.get("deliverables") or []:
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            add(run_dir / item["path"], "final-agent")
    for worker in dispatch_fm.get("workers") or []:
        wid = worker.get("id")
        if not wid:
            continue
        result_path = worker_result_path(run_dir, iteration, wid)
        if result_path.is_file():
            add(result_path, wid)
            fm_w, _ = read_artifact(result_path)
            for item in fm_w.get("deliverables") or []:
                if isinstance(item, dict) and isinstance(item.get("path"), str):
                    add(run_dir / item["path"], wid)
            # 自动纳入 worker claims 引用的证据文件（run 内的才进包，保证评审包路径合法）。
            for claim in fm_w.get("claims") or []:
                if not isinstance(claim, dict):
                    continue
                for ev in claim.get("evidence") or []:
                    if not isinstance(ev, str) or not ev.strip():
                        continue
                    candidate = Path(ev)
                    if not candidate.is_absolute():
                        candidate = run_dir / candidate
                    if is_inside(run_dir, candidate):
                        add(candidate, wid)
    fm = {
        "schema_version": SCHEMA_VERSION,
        "iteration": iteration,
        "tier": state.get("tier"),
        "task": task_fm.get("task", state.get("task", "")),
        "acceptance": plan_fm.get("accepted_criteria") or [],
        "rubric_version": rubric_version,
        "reviewers": int(state.get("review", {}).get("reviewers", 1)),
        "artifacts": artifacts,
        "forbidden": [
            "run_report.md",
            "state.json",
            "iteration_summary.md",
            "其他轮次的 review_report",
            "主 Agent 的规划与评价",
        ],
        "created_at": now_iso(),
    }
    body = (
        "# 评审包（Review Packet）\n\n"
        "> 评审 Agent 只能读本文件与 `artifacts` 中列出的文件；"
        "禁止读取 `run_report.md`、`state.json`、历次评审报告与主 Agent 的规划。\n\n"
        f"- 任务：{fm['task']}\n"
        f"- 等级：{fm['tier']} · 第 {iteration} 轮 · rubric：{rubric_version} · 评审人数：{fm['reviewers']}\n"
        f"- 验收标准：{'; '.join(str(x) for x in fm['acceptance'])}\n\n"
        "## 可读产物\n\n"
        + "\n".join(f"- `{a['path']}`（{a['producer']}）" for a in artifacts)
        + "\n"
    )
    write_artifact(paths["packet"], fm, body)
    return paths["packet"]


# --------------------------------------------------------------------------- #
# 创建 / 推进 / 收尾
# --------------------------------------------------------------------------- #
def create_run(root: Path, command: str, task: str | None = None) -> Path:
    token, rest = parse_command(command)
    task_text = (task or rest).strip()
    if not task_text:
        raise TeamworkError("命令里缺少任务描述：请写成 `teamwork, N=2 你的任务…`")
    n_mode = "auto" if token == "?" else "explicit"
    explicit_n = None if token == "?" else int(token)
    if explicit_n is not None and not (N_MIN <= explicit_n <= N_MAX):
        raise TeamworkError(f"N 必须在 {N_MIN}–{N_MAX} 之间")
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + safe_slug(task_text)
    run_dir = root / run_id
    if run_dir.exists():
        run_dir = root / f"{run_id}-{uuid.uuid4().hex[:4]}"
    for sub in ("00_intake", "01_plans", "iterations", "review_policy", ".teamwork"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    write_artifact(
        run_dir / "00_intake" / "task.md",
        {
            "schema_version": SCHEMA_VERSION,
            "command": command,
            "task": task_text,
            "n_mode": n_mode,
            "explicit_n": explicit_n,
            "created_at": now_iso(),
        },
        f"# 任务\n\n{task_text}\n",
    )
    write_artifact(
        run_dir / "review_policy" / "v0.md",
        dict(RUBRIC_V0),
        "# 审核策略 v0\n\n"
        "六个维度：正确性 30 / 完整性 20 / 证据与可验证性 20 / 鲁棒性 10 / "
        "可维护与可回滚 10 / 成本效率 10。\n\n"
        "一票否决：无证据断言、虚构证据、答非所问、未运行却声称通过。\n",
    )
    state = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "command": command,
        "task": task_text,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "n_mode": n_mode,
        "explicit_n": explicit_n,
        "n": None,
        "tier": None,
        "tier_reason": "",
        "current_iter": 1,
        "phase": "INIT",
        "finished": False,
        "aborted": False,
        "workers": {"planned": 0, "ids": [], "registry": {}, "agents": {}},
        "review": {"policy_version": "v0", "reviewers": 1, "dual_review_approved": False},
        "rework_count": 0,
        "scores": [],
        "history": [{"at": now_iso(), "event": "init", "detail": run_id}],
    }
    save_state(run_dir, state)
    render_run(run_dir)
    return run_dir


def _apply_phase_updates(
    check: Check, state: dict[str, Any], phase: str, next_phase: str
) -> None:
    paths = run_paths(check.run_dir, state["current_iter"])
    if phase == "CLASSIFY":
        fm, _ = read_artifact(paths["classification"])
        tier = fm["tier"]
        state["tier"] = tier
        state["tier_reason"] = fm.get("tier_reason", "")
        if state["n_mode"] == "explicit":
            state["n"] = state["explicit_n"]
        else:
            adjust = int(fm.get("n_adjust") or 0)
            state["n"] = max(N_MIN, min(N_MAX, TIER_DEFAULT_N[tier] + adjust))
        state["workers"]["planned"] = int(fm.get("workers_planned") or 0)
        append_history(
            state,
            "classify",
            f"tier={tier} n={state['n']} workers={state['workers']['planned']}",
        )
    elif phase == "PLAN":
        fm, _ = read_artifact(paths["plan"])
        append_history(state, "plan", f"iter={state['current_iter']}")
    elif phase == "DISPATCH":
        fm, _ = read_artifact(paths["dispatch"])
        ids = [w["id"] for w in fm.get("workers") or [] if isinstance(w, dict) and w.get("id")]
        registry = dict((state.get("workers") or {}).get("registry") or {})
        agents = dict((state.get("workers") or {}).get("agents") or {})
        reused = [wid for wid in ids if wid in registry]
        for wid in ids:
            registry.setdefault(wid, int(state["current_iter"]))
            agents.setdefault(wid, agent_name(str(state["run_id"]), wid))
        state["workers"] = {
            "planned": len(ids),
            "ids": ids,
            "registry": registry,
            "agents": agents,
            "reused": reused,
            "new_ids": [wid for wid in ids if wid not in reused],
        }
        append_history(
            state,
            "dispatch",
            ",".join(ids) + (f"（复用 {', '.join(reused)}）" if reused else ""),
        )
    elif phase == "WORKERS":
        append_history(state, "workers", f"iter={state['current_iter']}")
    elif phase == "FINAL":
        make_review_packet(check.run_dir, state)
        append_history(
            state,
            "final",
            f"iter={state['current_iter']} mode={final_agent_mode(state.get('tier'))}",
        )
    elif phase == "GATE":
        verdict = check.data.get("gate_verdict")
        if verdict == "REWORK":
            state["rework_count"] = int(state.get("rework_count", 0)) + 1
            append_history(state, "gate", "REWORK")
        else:
            state["rework_count"] = 0
            append_history(state, "gate", "PASS")
    elif phase == "REVIEW":
        merged = compute_merged_review(check.run_dir, state)
        write_scores(check.run_dir, merged)
        state.setdefault("scores", []).append(
            {
                "iteration": state["current_iter"],
                "total": merged["merged_total"],
                "verdict": merged["merged_verdict"],
                "reviewers": len(merged["reviewers"]),
                "policy_version": merged["rubric_version"],
            }
        )
        append_history(state, "review", f"{merged['merged_total']} {merged['merged_verdict']}")
    elif phase == "DREAM":
        fm, _ = read_artifact(paths["ledger"])
        entry = None
        for item in fm.get("entries") or []:
            if isinstance(item, dict) and item.get("iteration") == state["current_iter"]:
                entry = item
        if entry and entry.get("decision") == "promote":
            state["review"]["policy_version"] = entry["policy_after"]
            append_history(state, "dream", f"promote {entry['policy_after']}")
        else:
            append_history(state, "dream", "keep")
        state["current_iter"] = int(state["current_iter"]) + 1
    state["phase"] = next_phase


def advance_run(run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    if state["finished"]:
        raise TeamworkError("该 run 已结束（finished=true），不能再推进")
    phase = state["phase"]
    if phase == "DONE":
        raise TeamworkError("当前已是 DONE：请写 final_report.md 后运行 finish")
    check = Check(run_dir, state)
    validate_phase(check)
    if check.errors:
        raise ValidationFailed(check.errors, check.warnings)

    if phase == "GATE":
        verdict = check.data.get("gate_verdict")
        if verdict == "REWORK":
            if int(state.get("rework_count", 0)) >= MAX_REWORK:
                raise TeamworkError(
                    f"本轮已重做 {MAX_REWORK} 次，达到上限：请把 gate.md 改成 PASS，"
                    "或由主 Agent 决定停止并说明原因"
                )
            next_phase = "WORKERS"
        else:
            next_phase = "REVIEW"
    elif phase == "REVIEW":
        next_phase = "DREAM" if state["current_iter"] < state["n"] else "DONE"
    elif phase == "DREAM":
        next_phase = "PLAN"
    elif phase == "INIT":
        next_phase = "CLASSIFY"
    elif phase == "CLASSIFY":
        next_phase = "PLAN"
    elif phase == "PLAN":
        next_phase = "DISPATCH"
    elif phase == "DISPATCH":
        next_phase = "WORKERS"
    elif phase == "WORKERS":
        next_phase = "FINAL"
    elif phase == "FINAL":
        next_phase = "GATE"
    else:
        raise TeamworkError(f"无法从 {phase} 推进")

    _apply_phase_updates(check, state, phase, next_phase)
    save_state(run_dir, state)
    render_run(run_dir)
    return {
        "from": phase,
        "to": state["phase"],
        "iteration": state["current_iter"],
        "n": state["n"],
        "warnings": check.warnings,
    }


def render_run(run_dir: Path) -> dict[str, Any]:
    """渲染图与看板。

    - 文字产物（framework.mmd / PROGRESS.md）不依赖 matplotlib，始终生成；
    - PNG（framework.png）需要 matplotlib，缺失时降级跳过并返回 png_error，
      不阻断状态机推进。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    result: dict[str, Any] = {}
    try:
        import render_text  # noqa: WPS433

        result.update(render_text.render_text_assets(run_dir))
    except Exception as exc:  # pragma: no cover - 防御
        result["text_error"] = str(exc)
    try:
        import render_diagram  # noqa: WPS433 (lazy import: matplotlib 较重)

        result.update(render_diagram.render_png(run_dir))
    except Exception as exc:
        result.setdefault("framework_png", None)
        result["png_error"] = str(exc)
    return result


def finish_run(run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    if state["finished"]:
        raise TeamworkError("该 run 已经结束")
    if state["phase"] != "DONE":
        raise TeamworkError("只有推进到 DONE 阶段后才能 finish")
    check = Check(run_dir, state)
    validate_final_report(check)
    if check.errors:
        raise ValidationFailed(check.errors, check.warnings)
    state["finished"] = True
    append_history(state, "finish", "")
    save_state(run_dir, state)
    render_run(run_dir)
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import render_diagram

        render_diagram.render_score_trend(run_dir)
    except Exception:
        pass  # 缺 matplotlib 时跳过分数轨迹图，不阻断收尾
    return {"run_dir": str(run_dir), "final_report": rel(run_dir, run_paths(run_dir, state["current_iter"])["final_report"])}


def set_n(run_dir: Path, n: int) -> dict[str, Any]:
    state = load_state(run_dir)
    if not (N_MIN <= n <= N_MAX):
        raise TeamworkError(f"N 必须在 {N_MIN}–{N_MAX} 之间")
    old = state.get("n")
    state["n"] = n
    state["n_mode"] = "explicit"
    append_history(state, "set-n", f"{old} -> {n}")
    save_state(run_dir, state)
    render_run(run_dir)
    return {"from": old, "to": n, "state": state}


def set_tier(run_dir: Path, tier: str, reason: str) -> dict[str, Any]:
    state = load_state(run_dir)
    if tier not in TIER_RANGES:
        raise TeamworkError("tier 必须是 Small/Medium/Large")
    if state["phase"] not in ("INIT", "CLASSIFY", "PLAN"):
        raise TeamworkError("只能在 INIT/CLASSIFY/PLAN 阶段调整等级")
    old = state.get("tier")
    state["tier"] = tier
    state["tier_reason"] = reason
    if state.get("n_mode") == "auto":
        state["n"] = TIER_DEFAULT_N[tier]
    append_history(state, "set-tier", f"{old} -> {tier} ({reason})")
    save_state(run_dir, state)
    render_run(run_dir)
    return {"from": old, "to": tier, "n": state.get("n")}


def set_reviewers(run_dir: Path, count: int, *, approved: bool = True) -> dict[str, Any]:
    state = load_state(run_dir)
    if state["phase"] in ("REVIEW", "DREAM", "DONE"):
        raise TeamworkError("审核已经开始，不能再调整评审人数")
    if not (1 <= count <= MAX_REVIEWERS):
        raise TeamworkError(f"评审人数必须在 1–{MAX_REVIEWERS} 之间")
    state["review"]["reviewers"] = count
    state["review"]["dual_review_approved"] = bool(approved and count > 1)
    append_history(state, "set-reviewers", f"count={count}")
    save_state(run_dir, state)
    render_run(run_dir)
    return {
        "reviewers": count,
        "dual_review_approved": state["review"]["dual_review_approved"],
    }


def set_dual_review(run_dir: Path, enabled: bool) -> dict[str, Any]:
    return set_reviewers(run_dir, 2 if enabled else 1, approved=bool(enabled))


def stop_run(run_dir: Path, reason: str = "") -> dict[str, Any]:
    state = load_state(run_dir)
    if state["finished"]:
        raise TeamworkError("该 run 已经结束")
    state["aborted"] = True
    state["phase"] = "DONE"
    append_history(state, "stop", reason)
    save_state(run_dir, state)
    render_run(run_dir)
    return {"phase": state["phase"], "aborted": True}


# --------------------------------------------------------------------------- #
# next 指令
# --------------------------------------------------------------------------- #
def status_line(state: dict[str, Any], worker_done: int | None = None) -> str:
    n = state.get("n") or "?"
    parts = [
        f"Iteration {state['current_iter']}/{n}",
        f"Phase {PHASE_LABEL.get(state['phase'], state['phase'])}",
    ]
    if state.get("tier"):
        parts.append(f"Tier {state['tier']}")
    if worker_done is not None and state.get("workers", {}).get("planned"):
        parts.append(f"Workers {worker_done}/{state['workers']['planned']}")
    parts.append(f"Reviewers {state.get('review', {}).get('reviewers', 1)}")
    if state.get("scores"):
        last = state["scores"][-1]
        parts.append(f"Score {last['total']} {last['verdict']}")
    return " · ".join(parts)


def worker_status(run_dir: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    iteration = state["current_iter"]
    reused = set((state.get("workers") or {}).get("reused") or [])
    for wid in state.get("workers", {}).get("ids") or []:
        path = worker_result_path(run_dir, iteration, wid)
        status = "pending"
        if path.is_file():
            try:
                fm, _ = read_artifact(path)
                status = str(fm.get("status", "unknown"))
            except TeamworkError:
                status = "invalid"
        out.append({"id": wid, "status": status, "reused": wid in reused})
    return out


def build_next(run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    phase = state["phase"]
    iteration = state["current_iter"]
    paths = run_paths(run_dir, iteration)
    templates = [f"assets/templates/{name}" for name in TEMPLATES.get(phase, [])]
    common = {
        "run_dir": str(run_dir),
        "phase": phase,
        "phase_label": PHASE_LABEL.get(phase, phase),
        "role": phase_role(state, phase),
        "final_agent_mode": final_agent_mode(state.get("tier")) if phase == "FINAL" else None,
        "iteration": iteration,
        "n": state.get("n"),
        "tier": state.get("tier"),
        "status_line": status_line(
            state,
            worker_done=sum(
                1 for w in worker_status(run_dir, state) if w["status"] == "completed"
            ),
        ),
        "templates": templates,
    }
    if phase == "INIT":
        common.update(
            instruction=(
                "run 已创建（task.md、review_policy/v0.md 已生成）。直接 advance 进入分级；"
                "随后读 references/tiers.md 判断等级并写 00_intake/classification.md。"
            ),
            outputs=[rel(run_dir, paths["task"])],
            next_command="python scripts/orchestrator.py advance",
        )
    elif phase == "CLASSIFY":
        common.update(
            instruction=(
                "写 00_intake/classification.md：tier、signals（files/external/verifiable/"
                "parallel/risk/user_demand）、tier_reason、workers_planned；"
                "N=? 时用 n_adjust∈[-1,1] 调轮数并写 n_reason。然后 advance。"
            ),
            outputs=[rel(run_dir, paths["classification"])],
            next_command="python scripts/orchestrator.py advance",
        )
    elif phase == "PLAN":
        common.update(
            instruction="写计划文件（含 objective/breakdown/accepted_criteria/risks），然后 advance。",
            outputs=[rel(run_dir, paths["plan"])],
            next_command="python scripts/orchestrator.py advance",
        )
    elif phase == "DISPATCH":
        reuse_hint = ""
        if iteration > 1 and state.get("tier") in ("Small", "Medium"):
            registry = sorted((state.get("workers", {}).get("registry") or {}))
            reuse_hint = (
                f"本轮尽量复用已有 worker（{', '.join(registry) or '暂无'}），不新建全新 worker；"
                "确需新增时在 dispatch 里说明理由。"
            )
        common.update(
            instruction=(
                "把计划拆成可并行的 worker 任务，写 dispatch 文件（worker id 用 w01…）。"
                "worker 数按「本任务（本 run）」累计：L 级 5–7（+Final=8），S 1–2、M 3–4；"
                "同一对话/上下文的其它任务各自独立计数、互不占用名额。"
                + reuse_hint
                + "然后 advance。"
            ),
            outputs=[rel(run_dir, paths["dispatch"])],
            next_command="python scripts/orchestrator.py advance",
        )
        if state.get("tier"):
            lo, hi = TIER_RANGES[state["tier"]]
            used = sorted((state.get("workers") or {}).get("registry") or {})
            common["worker_range"] = {
                "min": lo,
                "max": hi,
                "scope": "人数上限只按单个任务（单个 run）计数；同一对话/上下文中的多个任务各自独立计数、互不占用名额",
                "used_this_task": used,
                "remaining_this_task": max(0, hi - len(used)),
            }
            if state["tier"] == "Large":
                common["worker_range"]["max_total_with_final"] = MAX_WORKERS_FINAL_CAP
    elif phase == "WORKERS":
        workers = state.get("workers", {}).get("ids") or []
        registry = sorted((state.get("workers", {}).get("registry") or {}))
        reuse_workers = bool(iteration > 1 and state.get("tier") in ("Small", "Medium") and registry)
        if reuse_workers:
            instruction = (
                "复用已有 worker（不新建全新子 Agent）：本轮交给 registry 中的 worker 继续执行，"
                "用 send_message 唤醒各自 teammate（名称见下方 agents 映射），只写各自己录；"
                "每个 worker 更新 result.md 后回来 advance。"
            )
        else:
            instruction = (
                "为每个 worker 启动全新子 Agent（并行），各自只写自己的目录；"
                "teammate 的物理名称必须用下方 agents 映射里的 agent_name（带本任务指纹），"
                "不要复用同一对话里其它任务已占用的名称；"
                "每个 worker 产出 result.md 后回来 advance。"
            )
        common.update(
            instruction=instruction,
            subagents={
                "role": "worker",
                "parallel": True,
                "reuse": reuse_workers,
                "registry": registry,
                "agents": {
                    wid: agent_name(str(state["run_id"]), wid) for wid in workers
                },
                "workers": [
                    {
                        "id": wid,
                        "agent_name": agent_name(str(state["run_id"]), wid),
                        "result": rel(run_dir, worker_result_path(run_dir, iteration, wid)),
                        "artifacts_dir": rel(
                            run_dir, paths["workers_dir"] / f"{wid}_artifacts"
                        ),
                    }
                    for wid in workers
                ],
                "prompt_reference": "references/protocol.md#worker",
            },
            outputs=[rel(run_dir, worker_result_path(run_dir, iteration, wid)) for wid in workers],
            next_command="python scripts/orchestrator.py advance",
        )
    elif phase == "FINAL":
        mode = final_agent_mode(state.get("tier"))
        if mode == "subagent":
            instruction = (
                "启动全新 Final Agent：读 worker 结果与证据，写 final_result.md 和 "
                "run_report.md；然后运行 make-packet 生成 review_packet，再 advance。"
            )
            subagents = {
                "role": "final",
                "agent_name": final_agent_name(str(state["run_id"])),
                "prompt_reference": "references/protocol.md#final",
                "outputs": [rel(run_dir, paths["final"]), rel(run_dir, paths["run_report"])],
            }
        else:
            instruction = (
                "你（主 Agent）直接汇总，不另开 Final Agent：读 worker 结果与证据，亲自写 "
                "final_result.md 和 run_report.md；然后运行 make-packet 生成 review_packet，再 advance。"
            )
            subagents = {
                "role": "main",
                "prompt_reference": "references/protocol.md#final",
                "outputs": [rel(run_dir, paths["final"]), rel(run_dir, paths["run_report"])],
            }
        common.update(
            instruction=instruction,
            subagents=subagents,
            outputs=[rel(run_dir, paths["final"]), rel(run_dir, paths["run_report"])],
            next_command=(
                "python scripts/orchestrator.py make-packet && "
                "python scripts/orchestrator.py advance"
            ),
        )
    elif phase == "GATE":
        common.update(
            instruction=(
                "主 Agent 验收（不写评审意见）：按 checklist 写 gate.md 的 PASS/REWORK；"
                "REWORK 要列出 rework_targets；然后 advance。"
            ),
            outputs=[rel(run_dir, paths["gate"])],
            next_command="python scripts/orchestrator.py advance",
            max_rework=MAX_REWORK,
        )
    elif phase == "REVIEW":
        reviewers = int(state.get("review", {}).get("reviewers", 1))
        letters = [review_letter(idx) for idx in range(1, reviewers + 1)]
        report_rels = [
            rel(run_dir, review_report_path(run_dir, iteration, letter))
            for letter in letters
        ]
        common.update(
            instruction=(
                "启动全新独立审核子 Agent（不得继承上下文），只准读 review_packet.md 与其中 "
                "artifacts；写 " + "、".join(f"review_report_{x}.md" for x in letters)
                + "；然后 advance（脚本会自动合成 review_scores.md）。"
            ),
            subagents={
                "role": "reviewer",
                "independent": True,
                "reviewers": reviewers,
                "packet": rel(run_dir, paths["packet"]),
                "forbidden": ["run_report.md", "state.json", "iteration_summary.md", "其他评审报告"],
                "agents": [
                    {
                        "reviewer": letter,
                        "agent_name": reviewer_agent_name(str(state["run_id"]), letter),
                        "output": rel(run_dir, review_report_path(run_dir, iteration, letter)),
                    }
                    for letter in letters
                ],
                "prompt_reference": "references/protocol.md#reviewer",
                "outputs": report_rels,
            },
            outputs=report_rels,
            next_command="python scripts/orchestrator.py advance",
        )
    elif phase == "DREAM":
        common.update(
            instruction=(
                "审核 Agent 做梦模式：用历史迭代桶重放候选 rubric，写 replay_ledger.md"
                "（含本轮 entry），promote 时写 review_policy/vN.md；然后 advance 进入下一轮。"
            ),
            subagents={
                "role": "dream",
                "agent_name": dream_agent_name(str(state["run_id"])),
                "prompt_reference": "references/protocol.md#dream",
            },
            outputs=[rel(run_dir, paths["ledger"]), rel(run_dir, paths["policy_dir"])],
            next_command="python scripts/orchestrator.py advance",
        )
    elif phase == "DONE":
        common.update(
            instruction=(
                "写 final_report.md（含分数轨迹），然后运行 finish 收尾（生成 score_trend.png）。"
            ),
            outputs=[rel(run_dir, paths["final_report"])],
            next_command="python scripts/orchestrator.py finish",
        )
    return common


def current_status(run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    workers = worker_status(run_dir, state)
    paths = run_paths(run_dir, state["current_iter"])
    return {
        "run_dir": str(run_dir),
        "run_id": state.get("run_id"),
        "phase": state["phase"],
        "phase_label": PHASE_LABEL.get(state["phase"], state["phase"]),
        "tier": state.get("tier"),
        "n": state.get("n"),
        "n_mode": state.get("n_mode"),
        "current_iter": state["current_iter"],
        "reviewers": state.get("review", {}).get("reviewers", 1),
        "policy_version": state.get("review", {}).get("policy_version", "v0"),
        "workers": workers,
        "workers_planned": state.get("workers", {}).get("planned", 0),
        "rework_count": state.get("rework_count", 0),
        "scores": state.get("scores", []),
        "status_line": status_line(state),
        "finished": state.get("finished", False),
        "aborted": state.get("aborted", False),
        "progress": rel(run_dir, paths["progress"]),
        "framework_png": rel(run_dir, paths["framework_png"]),
        "next": build_next(run_dir) if not state.get("finished") else None,
    }
