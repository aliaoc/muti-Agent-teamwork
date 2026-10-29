"""teamwork skill 共享库。

设计原则：流程、阶段顺序、产物字段、评分合成、门禁、引用核验、教练切片、
轮次建议全部写死在这里；模型只负责在「内容槽位」里写正文，不能改流程。
所有中间产物是 Markdown + YAML frontmatter；唯一的机器账本是
<run>/.teamwork/state.json。

v2.0 的三条边界（写进代码，也写进 README）：
1. 环内只改做法（COACH），不改评分标准；rubric 演进只在环外 `dream` 发生。
2. 代码负责结构、算术、覆盖、门槛；语义真实性（这条来源是否真支持该结论、
   这条建议是否真能落地）由 Agent 判断。
3. 每条改进都要被下一轮的错误复发率考核（recurred_from → 命中率）。

本模块被 orchestrator.py / validate.py / render_*.py / selftest.py 共同引用。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def _prefer_utf8_stdio() -> None:
    """Windows 控制台/管道默认可能是 cp1252、cp936，直接 print 中文会 UnicodeEncodeError。

    这里把标准输出/错误流切到 UTF-8；被重定向到 StringIO 等无 reconfigure 的对象时跳过。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


_prefer_utf8_stdio()

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
    "COACH",
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
    "COACH": "教练复盘",
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
    "COACH": "RSI 教练（全新子 Agent，不继承评审上下文）",
    "DONE": "主 Agent",
}
# 旧版本 state 里的阶段别名：DREAM 已由 COACH 取代（环外 dream 命令另行实现）。
PHASE_ALIASES = {"DREAM": "COACH"}

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
        # v2.0：查无此文的一票否决（misattributed 走 evidence 维度封顶，不直接否决）
        "fabricated_citation",
    ],
    "noise_floor": 5,
    "max_edits_per_iteration": 3,
}
# 这四个是 v1 就有的核心门禁，任何策略版本都不许删。
CORE_GATES = (
    "unsupported_claims",
    "fabricated_evidence",
    "off_topic",
    "claimed_pass_without_run",
)
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
    "fabricated_citation": "虚构来源（查无此文）",
    "misattributed_citation": "歪曲来源（存在但结论被写反）",
}
VERDICTS = ("PASS", "REVISE", "FAIL")

# 评审角色：general（通用六维） / citation_audit（专责引用核验）
REVIEW_ROLES = ("general", "citation_audit")
CITATION_VERDICTS = ("verified", "unverifiable", "misattributed", "fabricated", "stale")
# 错误类别：用于信用分配、教练命中率、跨 run 复发率统计。
ERROR_CLASSES = (
    "unsupported_claim",
    "evidence_gap",
    "citation_unverified",
    "citation_fabricated",
    "off_topic",
    "incomplete_coverage",
    "arithmetic_error",
    "format_violation",
    "plan_gap",
    "tool_failure",
    "cost_overrun",
    # 旧格式（字符串 errors）合成时使用；统计复发率时会被忽略。
    "unclassified",
)
COACH_PRIORITIES = ("must_fix", "should_fix", "nice_to_have")
MAX_COACH_ITEMS = 8
MAX_MUST_FIX = 3
CITATION_MAX_ITEMS = 40
CITATION_MIN_VERIFIED_RATIO = 0.8
CITATION_MAX_UNVERIFIABLE_RATIO = 0.2
ADVISORY_MAX_ROUNDS = 3
PASS_THRESHOLD = 85
REVISE_THRESHOLD = 60
DISAGREEMENT_DELTA = 10

TEMPLATES = {
    "INIT": [],
    "CLASSIFY": ["classification.md"],
    "PLAN": ["plan.md"],
    "DISPATCH": ["dispatch.md"],
    "WORKERS": ["worker_result.md"],
    "FINAL": ["final_result.md", "run_report.md"],
    "GATE": ["gate.md"],
    "REVIEW": ["review_report.md"],
    "COACH": ["rsi_report.md"],
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


def coach_agent_name(run_id: str) -> str:
    digest = hashlib.sha1(run_id.encode("utf-8")).hexdigest()[:6]
    return f"tw-{digest}-coach"


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
    """原子写 JSON：唯一临时名 + 重试 + 兜底直写。

    Windows 上杀软/索引器可能短暂持有句柄（WinError 5），固定 `.tmp` 名在并发下
    还会互相覆盖。这里每次用随机临时名，`os.replace` 失败重试 3 次，
    最后一次退化为直接写入（牺牲原子性，换取不丢状态）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    last_error: OSError | None = None
    for attempt in range(3):
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
            return
        except PermissionError as exc:  # Windows 文件占用
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        if last_error is not None:
            raise last_error
        raise


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
        "rsi": iter_dir / "rsi_report.md",
        "advisory": iter_dir / "iteration_advisory.md",
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
    state = read_json(path)
    return migrate_state(state)


def migrate_state(state: dict[str, Any]) -> dict[str, Any]:
    """读取时做向后兼容迁移（不写盘，避免只读命令产生副作用）。

    - v1 的 `phase: DREAM` 按 `COACH` 处理，老 run 可继续 resume；
    - 补齐 v2.0 新增字段的默认值，缺字段一律按默认处理，不报错。
    """
    phase = state.get("phase")
    if phase in PHASE_ALIASES:
        state["phase"] = PHASE_ALIASES[phase]
    review = state.setdefault("review", {})
    review.setdefault("policy_version", "v0")
    review.setdefault("reviewers", 1)
    review.setdefault("dual_review_approved", False)
    roles = review.get("roles")
    if not isinstance(roles, dict) or not roles:
        count = int(review.get("reviewers", 1) or 1)
        review["roles"] = {
            review_letter(idx): "general" for idx in range(1, count + 1)
        }
    else:
        normalized = {str(k).upper(): str(v) for k, v in roles.items()}
        review["roles"] = normalized
    review.setdefault("citation_audit", "auto")
    state.setdefault("coach", {"entries": [], "stuck_classes": [], "ineffective": []})
    coach = state["coach"]
    coach.setdefault("entries", [])
    coach.setdefault("stuck_classes", [])
    coach.setdefault("ineffective", [])
    state.setdefault("advisory", None)
    state.setdefault("advisory_mode", "auto")
    return state


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
    # 教练升级：连续两轮复发的错误类别，必须由计划层正面处理（不能再只靠 worker 自觉）。
    stuck = set((check.state.get("coach") or {}).get("stuck_classes") or [])
    if stuck:
        addressed = f_list(check, fm, "addresses_errors", where, min_len=len(stuck)) or []
        covered: set[str] = set()
        for idx, item in enumerate(addressed, 1):
            if not isinstance(item, dict):
                check.err(f"{where}：addresses_errors 第 {idx} 项必须是映射")
                continue
            klass = item.get("class")
            if klass not in ERROR_CLASSES:
                check.err(f"{where}：addresses_errors 第 {idx} 项 class 非法（{klass}）")
                continue
            covered.add(str(klass))
            mitigation = item.get("mitigation")
            if not isinstance(mitigation, str) or not mitigation.strip():
                check.err(f"{where}：addresses_errors {klass} 缺少 mitigation（计划层怎么改）")
        missing = sorted(stuck - covered)
        if missing:
            check.err(
                f"{where}：以下错误类别连续两轮复发，计划必须写 addresses_errors："
                f"{', '.join(missing)}"
            )
    validate_body(check, body, where)


WORKER_TOKEN_RE = re.compile(r"(?<![0-9A-Za-z])w\d{2}(?![0-9])")


def validate_coach_slicing(
    check: Check, fm: dict[str, Any], where: str, worker_ids: list[str]
) -> None:
    """DISPATCH 的切片锁：教练条目不许被删、不许越权下发、不许串到别人产物。"""
    iteration = check.state["current_iter"]
    if iteration <= 1:
        return
    prev_rsi = run_paths(check.run_dir, iteration - 1)["rsi"]
    if not prev_rsi.exists():
        return
    try:
        rfm, _ = read_artifact(prev_rsi)
    except TeamworkError:
        return
    items = [
        item for item in (rfm.get("items") or []) if isinstance(item, dict) and item.get("id")
    ]
    if not items:
        return
    by_id = {str(item["id"]): item for item in items}
    applied = fm.get("coach_applied")
    deferred = fm.get("coach_deferred")
    if applied is None:
        check.err(f"{where}：上一轮有 {len(items)} 条教练条目，必须写 coach_applied（可为空）")
        applied = []
    if not isinstance(applied, list):
        check.err(f"{where}：coach_applied 必须是列表")
        applied = []
    if deferred is None:
        deferred = []
    if not isinstance(deferred, list):
        check.err(f"{where}：coach_deferred 必须是列表")
        deferred = []
    deferred_ids: dict[str, str] = {}
    for idx, item in enumerate(deferred, 1):
        if not isinstance(item, dict):
            check.err(f"{where}：coach_deferred 第 {idx} 项必须是映射")
            continue
        did = item.get("id")
        reason = item.get("reason")
        if did not in by_id:
            check.err(f"{where}：coach_deferred 出现未知条目 {did}")
            continue
        if not isinstance(reason, str) or len(reason.strip()) < 5:
            check.err(f"{where}：coach_deferred {did} 必须写 reason（至少 5 字）")
            continue
        deferred_ids[str(did)] = reason.strip()
    applied_ids = {str(x) for x in applied}
    unknown_applied = sorted(applied_ids - set(by_id))
    if unknown_applied:
        check.err(f"{where}：coach_applied 出现未知条目 {', '.join(unknown_applied)}")
    missing = sorted(set(by_id) - applied_ids - set(deferred_ids))
    if missing:
        check.err(
            f"{where}：以下教练条目既未下发也未标 deferred：{', '.join(missing)}"
            "（主 Agent 只能延期并写理由，不能删除）"
        )
    both = applied_ids & set(deferred_ids)
    if both:
        check.err(f"{where}：条目同时出现在 coach_applied 与 deferred：{', '.join(sorted(both))}")

    workers = [w for w in fm.get("workers") or [] if isinstance(w, dict) and w.get("id")]
    for worker in workers:
        wid = str(worker["id"])
        entries = worker.get("coach_items")
        if entries is None:
            entries = []
        if not isinstance(entries, list):
            check.err(f"{where}：{wid} 的 coach_items 必须是列表")
            continue
        seen: set[str] = set()
        for idx, entry in enumerate(entries, 1):
            if not isinstance(entry, dict):
                check.err(f"{where}：{wid} 的 coach_items 第 {idx} 项必须是映射")
                continue
            cid = entry.get("id")
            if cid not in applied_ids:
                check.err(f"{where}：{wid} 的 coach_items 出现未 applied 的条目 {cid}")
                continue
            if cid in seen:
                check.err(f"{where}：{wid} 的 coach_items 重复条目 {cid}")
            seen.add(cid)
            applies = by_id[str(cid)].get("applies_to") or []
            if "all" not in applies and wid not in applies:
                check.err(f"{where}：条目 {cid} 的 applies_to={applies} 不包含 {wid}（越权下发）")
            text = f"{entry.get('action') or ''} {entry.get('verification') or ''}"
            foreign = sorted({tok for tok in WORKER_TOKEN_RE.findall(text) if tok != wid})
            if foreign:
                check.err(
                    f"{where}：{wid} 的条目 {cid} 提到了其他 worker 的产物/名称"
                    f"（{', '.join(foreign)}），破坏隔离"
                )
        for cid in sorted(applied_ids):
            applies = by_id[cid].get("applies_to") or []
            if "all" in applies or wid in applies:
                if cid not in seen:
                    check.err(
                        f"{where}：条目 {cid} 要求下发给 {wid}，但该 worker 的 coach_items 里没有"
                    )


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
        validate_coach_slicing(check, fm, where, ids)
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
                sources = claim.get("sources")
                if sources is not None:
                    if not isinstance(sources, list):
                        check.err(f"{where}：claim {idx} 的 sources 必须是列表")
                    else:
                        for sidx, source in enumerate(sources, 1):
                            validate_source(
                                check,
                                source,
                                f"{where} claim {idx} source {sidx}",
                                require_id=True,
                            )
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
        sources = fm.get("sources")
        if sources is not None:
            if not isinstance(sources, list):
                check.err(f"{where}：sources 必须是列表")
            else:
                dispatch_fm = None
                try:
                    dispatch_fm, _ = read_artifact(paths["dispatch"])
                except TeamworkError:
                    pass
                subscribers = {
                    str(w.get("id"))
                    for w in (dispatch_fm or {}).get("workers") or []
                    if isinstance(w, dict) and w.get("id")
                }
                ids: set[str] = set()
                for idx, item in enumerate(sources, 1):
                    record = validate_source(
                        check,
                        item,
                        f"{where} sources[{idx}]",
                        require_id=True,
                        require_contributor=True,
                        subscribers=subscribers or None,
                    )
                    if record is not None:
                        sid = str(record.get("id"))
                        if sid in ids:
                            check.err(f"{where}：来源 id 重复：{sid}")
                        ids.add(sid)
                if not sources and check.state.get("tier") == "Large":
                    check.warn(f"{where}：L 级任务没有登记 sources；若结论依赖外部资料，引用核验会空转")
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
        citations = fm.get("citations")
        if citations is not None:
            if not isinstance(citations, list):
                check.err(f"{where}：citations 必须是列表（由脚本生成）")
            else:
                packet_keys = {
                    (str(c.get("id")), str(c.get("locator_hash")))
                    for c in citations
                    if isinstance(c, dict)
                }
                try:
                    final_fm, _ = read_artifact(paths["final"])
                except TeamworkError:
                    final_fm = {}
                expected = normalise_sources(
                    final_fm.get("sources") if isinstance(final_fm.get("sources"), list) else []
                )
                expected_keys = {(c["id"], c["locator_hash"]) for c in expected}
                if not packet_keys == expected_keys:
                    check.err(
                        f"{where}：citations 与 final_result.sources 不一致"
                        "（评审包生成后不得再改来源；请重新运行 make-packet）"
                    )
            policy = fm.get("citation_policy")
            if not isinstance(policy, dict):
                check.err(f"{where}：缺少 citation_policy（由脚本生成）")
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


# --------------------------------------------------------------------------- #
# 来源 / 错误的结构化辅助
# --------------------------------------------------------------------------- #
URL_RE = re.compile(r"https?://[^\s<>\"'`\)\]]+")
ERROR_ID_RE = re.compile(r"^E\d+$")
SOURCE_ID_RE = re.compile(r"^S\d+$")
COACH_ID_RE = re.compile(r"^C\d+$")


def normalise_url(url: str) -> str:
    return url.strip().rstrip(".,;，。；、）)")


def locator_hash(url: str, locator: str) -> str:
    raw = f"{normalise_url(url)}#{locator.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def validate_source(
    check: Check,
    item: Any,
    where: str,
    *,
    require_id: bool = False,
    require_contributor: bool = False,
    subscribers: set[str] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        check.err(f"{where}：来源必须是映射（url/title/locator）")
        return None
    url = item.get("url")
    if not isinstance(url, str) or not url.strip().lower().startswith(("http://", "https://")):
        check.err(f"{where}：来源 url 必须是 http(s) 链接")
        url = None
    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        check.err(f"{where}：来源缺少 title")
    locator = item.get("locator")
    if not isinstance(locator, str) or not locator.strip():
        check.err(f"{where}：来源缺少 locator（摘要/页码/章节/命令行位置）")
    if require_id:
        sid = item.get("id")
        if not isinstance(sid, str) or not SOURCE_ID_RE.match(sid):
            check.err(f"{where}：来源 id 必须是 S01 形式")
    if require_contributor:
        who = item.get("contributed_by")
        if not isinstance(who, str) or not who.strip():
            check.err(f"{where}：来源缺少 contributed_by（哪个 worker 提供）")
        elif subscribers is not None and who not in subscribers:
            check.err(f"{where}：contributed_by 必须是本轮 worker（当前 {who}）")
    return item if url else None


def normalise_sources(raw: list[Any]) -> list[dict[str, Any]]:
    """把 final_result.sources 归一成评审包里的 citations（补 id、去重、算 locator_hash）。"""
    out: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    next_index = 1
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        locator = item.get("locator")
        if not isinstance(url, str) or not isinstance(locator, str):
            continue
        key = locator_hash(url, locator)
        if key in seen:
            # 同一处来源被多个 claim 引用：保留首条，合并 claim_ref。
            first = seen[key]
            ref = item.get("claim_ref")
            if ref and ref not in (first.get("claim_refs") or []):
                first.setdefault("claim_refs", [first.get("claim_ref")]).append(ref)
            continue
        sid = item.get("id")
        if not isinstance(sid, str) or not SOURCE_ID_RE.match(sid):
            sid = f"S{next_index:02d}"
        next_index = max(next_index, int(sid[1:]) + 1)
        record = {
            "id": sid,
            "claim_ref": item.get("claim_ref") or "",
            "url": normalise_url(url),
            "title": str(item.get("title") or ""),
            "publisher": str(item.get("publisher") or ""),
            "published_at": str(item.get("published_at") or ""),
            "quote": str(item.get("quote") or ""),
            "locator": str(locator).strip(),
            "contributed_by": str(item.get("contributed_by") or ""),
            "locator_hash": key,
        }
        seen[key] = record
        out.append(record)
    return out


def normalise_errors(check: Check, errors: list[Any], where: str) -> list[dict[str, Any]]:
    """把 errors 统一成对象数组。

    旧格式（字符串数组）仍接受：合成 E1..，class=unclassified。
    新格式必须是 {id, class, located, recurred_from}。
    """
    out: list[dict[str, Any]] = []
    ids: set[str] = set()
    for idx, item in enumerate(errors, 1):
        if isinstance(item, str):
            if not item.strip():
                check.err(f"{where}：errors 第 {idx} 项为空字符串")
                continue
            record = {
                "id": f"E{idx}",
                "class": "unclassified",
                "located": "",
                "recurred_from": None,
                "text": item.strip(),
            }
        elif isinstance(item, dict):
            eid = item.get("id")
            if not isinstance(eid, str) or not ERROR_ID_RE.match(eid):
                check.err(f"{where}：errors 第 {idx} 项 id 必须是 E1 形式")
                eid = f"E{idx}"
            klass = item.get("class")
            if klass not in ERROR_CLASSES:
                check.err(
                    f"{where}：errors {eid} 的 class 必须是 {len(ERROR_CLASSES)} 类之一"
                    f"（当前 `{klass}`）"
                )
            located = item.get("located")
            if not isinstance(located, str) or not located.strip():
                check.err(f"{where}：errors {eid} 缺少 located（文件+行/章节）")
            recurred = item.get("recurred_from")
            if recurred is not None and not isinstance(recurred, str):
                check.err(f"{where}：errors {eid} 的 recurred_from 必须是字符串或 null")
                recurred = None
            record = {
                "id": eid,
                "class": str(klass or "unclassified"),
                "located": str(located or ""),
                "recurred_from": recurred,
                "text": str(item.get("text") or item.get("detail") or ""),
            }
        else:
            check.err(f"{where}：errors 第 {idx} 项必须是字符串或映射")
            continue
        if record["id"] in ids:
            check.err(f"{where}：error id 重复：{record['id']}")
        ids.add(record["id"])
        out.append(record)
    return out


def build_error_index(
    reviews: dict[str, dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    """返回 (复合 id → 错误, 裸 id → 复合 id 列表)。

    多评审时各人都会写 E1，因此内部一律用 `A:E1` 复合 id；
    教练报告里写裸 `E1` 只有在该 id 唯一时才被接受，否则要求写 `A:E1`。
    """
    index: dict[str, dict[str, Any]] = {}
    alias: dict[str, list[str]] = {}
    for letter, payload in reviews.items():
        for err in payload.get("errors") or []:
            composite = f"{letter}:{err['id']}"
            index[composite] = err
            alias.setdefault(err["id"], []).append(composite)
    return index, alias


def resolve_error_ref(ref: str, index: dict[str, Any], alias: dict[str, list[str]]) -> str | None:
    if ref in index:
        return ref
    candidates = alias.get(ref) or []
    if len(candidates) == 1:
        return candidates[0]
    return None


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
    check: Check,
    path: Path,
    reviewer: str,
    rubric: dict[str, Any],
    expected_version: str,
    packet_fm: dict[str, Any] | None = None,
    expected_role: str = "general",
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
    role = f_enum(check, fm, "role", where, REVIEW_ROLES, required=False) or "general"
    if expected_role == "citation_audit":
        if role != "citation_audit":
            check.err(f"{where}：当前 role 配置为 citation_audit，报告必须写 `role: citation_audit`")
    elif role != "general":
        check.err(f"{where}：当前 role 配置为 general，报告不得写成 {role}")
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
    # C1：权重唯一事实来源是当前 rubric，而不是常量 RUBRIC_V0。
    weights = rubric["weights"]
    dims = f_list(check, fm, "dimensions", where, min_len=len(weights))
    dim_scores: dict[str, int] = {}
    evidence_pool: list[str] = []
    evidence_off_packet = 0
    packet_rel = rel(check.run_dir, run_paths(check.run_dir, check.state["current_iter"])["packet"])
    if dims:
        for idx, item in enumerate(dims, 1):
            if not isinstance(item, dict):
                check.err(f"{where}：dimensions 第 {idx} 项必须是映射")
                continue
            name = item.get("name")
            if name not in weights:
                check.err(f"{where}：未知评分维度 `{name}`")
                continue
            if item.get("weight") != weights[name]:
                check.err(f"{where}：维度 {name} 的 weight 必须是 {weights[name]}")
            score = item.get("score")
            if not _is_int(score) or not (0 <= score <= 100):
                check.err(f"{where}：维度 {name} 的 score 必须是 0–100 整数")
            else:
                dim_scores[name] = score
            ev = item.get("evidence")
            if not isinstance(ev, list) or not ev:
                check.err(f"{where}：维度 {name} 必须有 evidence")
            else:
                for raw in ev:
                    if not isinstance(raw, str):
                        check.err(f"{where}：{name} 的 evidence 必须是路径字符串")
                        continue
                    evidence_pool.append(raw)
                    if packet_rel not in raw:
                        evidence_off_packet += 1
                    if raw.strip().lower().startswith(("http://", "https://")):
                        # 外部网络证据：允许 URL，不校验本地存在性。
                        continue
                    check.ref_path(raw, f"{where} {name} evidence", inside=False)
    gates = f_list(check, fm, "gates_triggered", where)
    raw_errors = f_list(check, fm, "errors", where, min_len=0)
    f_list(check, fm, "optimizations", where)
    f_int(check, fm, "total", where, lo=0, hi=100)
    verdict = f_enum(check, fm, "verdict", where, VERDICTS)
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
    errors = normalise_errors(check, raw_errors or [], where)

    # C4：PASS 的证据密度下限（防"全 85 + 空 errors"糊过去）
    if computed["verdict"] == "PASS":
        if errors:
            check.err(f"{where}：PASS 报告不允许有 errors（当前 {len(errors)} 条）；请改判 REVISE")
        for name in weights:
            dim = next(
                (d for d in dims or [] if isinstance(d, dict) and d.get("name") == name), {}
            )
            ev = dim.get("evidence") or []
            if len(ev) < 2:
                check.err(f"{where}：PASS 时维度 {name} 至少需要 2 条 evidence（当前 {len(ev)}）")
        if evidence_off_packet < 3:
            check.err(
                f"{where}：PASS 时至少 3 条 evidence 必须指向实质产物，"
                "不能全部指向 review_packet.md 自身（自指漏洞）"
            )

    # 引用核验（仅 citation_audit 角色）
    if role == "citation_audit":
        validate_citation_audit(check, fm, where, packet_fm or {}, gates or [], dim_scores)
    elif "citation_audit" in fm:
        check.err(f"{where}：只有 citation_audit 角色可以写 citation_audit 段")

    check.data.setdefault("reviews", {})[reviewer] = {
        "fm": fm,
        "computed": computed,
        "body": body,
        "role": role,
        "errors": errors,
    }
    validate_body(check, body, where)
    return fm


def validate_citation_audit(
    check: Check,
    fm: dict[str, Any],
    where: str,
    packet_fm: dict[str, Any],
    gates: list[Any],
    dim_scores: dict[str, int],
) -> None:
    """引用核验包的三把锁：结构锁、算术锁、清单锁（抽样锁在 GATE 后由主 Agent 执行）。"""
    audit = f_dict(check, fm, "citation_audit", where)
    if audit is None:
        return
    mode = f_enum(check, audit, "mode", f"{where} citation_audit", ("online", "offline"))
    coverage = f_dict(check, audit, "coverage", f"{where} citation_audit")
    items = f_list(check, audit, "items", f"{where} citation_audit", min_len=1)
    if not items:
        return
    packet_citations = [c for c in (packet_fm.get("citations") or []) if isinstance(c, dict)]
    packet_ids = {str(c.get("id")) for c in packet_citations}
    seen: set[str] = set()
    counts = {v: 0 for v in CITATION_VERDICTS}
    for idx, item in enumerate(items, 1):
        if not isinstance(item, dict):
            check.err(f"{where}：citation_audit.items 第 {idx} 项必须是映射")
            continue
        sid = item.get("id")
        if not isinstance(sid, str) or not SOURCE_ID_RE.match(sid):
            check.err(f"{where}：citation_audit 第 {idx} 项 id 必须是 S01 形式")
            continue
        if sid in seen:
            check.err(f"{where}：citation_audit 重复核验 {sid}")
        seen.add(sid)
        verdict = item.get("verdict")
        if verdict not in CITATION_VERDICTS:
            check.err(f"{where}：{sid} 的 verdict 必须是 {'/'.join(CITATION_VERDICTS)} 之一")
            continue
        counts[verdict] += 1
        if verdict == "verified":
            if mode == "offline":
                check.err(f"{where}：离线模式禁止判 verified（{sid}）；无网络只能记 unverifiable")
            for key in ("method", "checked_at", "locator"):
                value = item.get(key)
                if not isinstance(value, str) or not value.strip():
                    check.err(f"{where}：verified 的 {sid} 必须给出 {key}（结构锁）")
    if packet_ids and seen != packet_ids:
        missing = sorted(packet_ids - seen)
        extra = sorted(seen - packet_ids)
        if missing:
            check.err(f"{where}：引用核验漏项 {', '.join(missing)}（覆盖率必须 100%）")
        if extra:
            check.err(f"{where}：引用核验多出清单外 id：{', '.join(extra)}")
    if coverage is not None:
        expected = {
            "total": len(items),
            "audited": len(items),
            "verified": counts["verified"],
            "unverifiable": counts["unverifiable"],
            "misattributed": counts["misattributed"],
            "fabricated": counts["fabricated"],
        }
        for key, value in expected.items():
            got = coverage.get(key)
            if not _is_int(got):
                check.err(f"{where}：citation_audit.coverage.{key} 必须是整数")
            elif got != value:
                check.err(
                    f"{where}：citation_audit.coverage.{key}={got} 与明细不一致（应为 {value}）"
                    "（算术锁）"
                )
        stale = coverage.get("stale")
        if stale is not None and (not _is_int(stale) or stale != counts["stale"]):
            check.err(f"{where}：citation_audit.coverage.stale 与明细不一致")
    if counts["fabricated"] and "fabricated_citation" not in [str(g) for g in gates]:
        check.err(f"{where}：存在虚构来源但未触发 fabricated_citation 一票否决")
    if counts["misattributed"]:
        score = dim_scores.get("evidence")
        if isinstance(score, int) and score > 60:
            check.err(
                f"{where}：存在 {counts['misattributed']} 条 misattributed，"
                f"evidence 维度必须封顶 60（当前 {score}）"
            )
    if mode == "offline":
        policy = packet_fm.get("citation_policy") or {}
        if policy.get("required"):
            check.warn(f"{where}：离线核验无法满足 min_verified_ratio，合并结论不得 PASS")


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
        total = 0
        for name, base in RUBRIC_V0["weights"].items():
            value = weights.get(name)
            if not _is_int(value):
                check.err(f"{where}：weights.{name} 必须是整数")
                continue
            total += value
            if abs(value - base) > 10:
                check.err(
                    f"{where}：weights.{name} 相对 v0 变化不得超过 ±10（v0={base}，当前 {value}）"
                )
        if total != 100:
            check.err(f"{where}：weights 之和必须为 100（当前 {total}）")
    gates = f_list(check, fm, "gates", where, min_len=1)
    if gates is not None:
        gate_set = {str(g) for g in gates}
        missing_core = [g for g in CORE_GATES if g not in gate_set]
        if missing_core:
            check.err(f"{where}：核心门禁不允许删除（缺 {', '.join(missing_core)}）")
        unknown = sorted(gate_set - set(RUBRIC_V0["gates"]))
        if unknown:
            check.err(f"{where}：出现未定义门禁 {', '.join(unknown)}")
    f_int(check, fm, "noise_floor", where, lo=0, hi=30)
    f_int(check, fm, "max_edits_per_iteration", where, lo=1, hi=10)
    validate_body(check, body, where)


def validate_review_phase(check: Check) -> None:
    iteration = check.state["current_iter"]
    paths = run_paths(check.run_dir, iteration)
    review_cfg = check.state.get("review", {})
    reviewers = int(review_cfg.get("reviewers", 1))
    version = review_cfg.get("policy_version", "v0")
    rubric = load_rubric(check.run_dir, version)
    packet = check.artifact(paths["packet"], rel(check.run_dir, paths["packet"]), inside=True)
    if not packet:
        return
    packet_fm, _ = packet
    if packet_fm.get("rubric_version") != version:
        check.err(f"review_packet.md：rubric_version 必须是 {version}")
    roles = review_cfg.get("roles") or {}
    for idx in range(1, reviewers + 1):
        letter = review_letter(idx)
        validate_review_report(
            check,
            review_report_path(check.run_dir, iteration, letter),
            letter,
            rubric,
            version,
            packet_fm=packet_fm,
            expected_role=str(roles.get(letter, "general")),
        )
    # 多评审：PASS 但存在 >10 分歧时，在合并阶段会被降级（C3）；这里提前提示。
    reviews = check.data.get("reviews") or {}
    if len(reviews) >= 2:
        for name in rubric["weights"]:
            values = []
            for payload in reviews.values():
                for dim in payload["fm"].get("dimensions") or []:
                    if isinstance(dim, dict) and dim.get("name") == name:
                        values.append(int(dim.get("score") or 0))
            if values and max(values) - min(values) > DISAGREEMENT_DELTA:
                check.warn(
                    f"review_packet.md：维度 {name} 分歧 {max(values) - min(values)} 分（>10），"
                    "合并结论将被强制降级为 REVISE"
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
    # C3：分歧导致的降级必须留痕，不能悄悄改判。
    if merged.get("downgrade_reason"):
        reason = fm.get("downgrade_reason")
        if not isinstance(reason, str) or not reason.strip():
            check.err(f"{where}：合并结论被降级时必须写 downgrade_reason")
    merged_dims = fm.get("merged_dimensions")
    if merged_dims is not None and not isinstance(merged_dims, dict):
        check.err(f"{where}：merged_dimensions 必须是映射")
    validate_body(check, body, where)


def _collect_round_errors(
    run_dir: Path, state: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    """读取本轮全部评审报告里的 errors，返回 (复合索引, 裸 id 别名)。"""
    iteration = state["current_iter"]
    reviewers = int(state.get("review", {}).get("reviewers", 1))
    scratch = Check(run_dir, state)
    reviews: dict[str, dict[str, Any]] = {}
    for idx in range(1, reviewers + 1):
        letter = review_letter(idx)
        path = review_report_path(run_dir, iteration, letter)
        if not path.exists():
            continue
        try:
            fm, _ = read_artifact(path)
        except TeamworkError:
            continue
        reviews[letter] = {
            "errors": normalise_errors(scratch, fm.get("errors") or [], path.name)
        }
    return build_error_index(reviews)


def _packet_url_whitelist(run_dir: Path, state: dict[str, Any]) -> set[str]:
    path = run_paths(run_dir, state["current_iter"])["packet"]
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8")
    urls = {normalise_url(u) for u in URL_RE.findall(text)}
    try:
        fm, _ = read_artifact(path)
    except TeamworkError:
        return urls
    for citation in fm.get("citations") or []:
        if isinstance(citation, dict) and isinstance(citation.get("url"), str):
            urls.add(normalise_url(citation["url"]))
    return urls


def validate_coach(check: Check) -> None:
    """COACH 阶段：结构锁 + 越权锁 + 事实锁 + 旧版兼容。"""
    state = check.state
    iteration = state["current_iter"]
    paths = run_paths(check.run_dir, iteration)
    if not paths["rsi"].exists():
        ledger = paths["ledger"]
        if ledger.exists():
            try:
                ledger_fm, _ = read_artifact(ledger)
            except TeamworkError:
                ledger_fm = {}
            entries = ledger_fm.get("entries") or []
            if any(isinstance(e, dict) and e.get("iteration") == iteration for e in entries):
                check.warn(
                    "检测到 v1 的 replay_ledger：按旧 DREAM 记录兼容处理；"
                    "新 run 请使用 COACH + rsi_report.md"
                )
                check.data["coach_legacy"] = True
                return
        check.err("缺少产物：iterations/iter-NN/rsi_report.md（COACH 阶段必须产出教练报告）")
        return

    got = check.artifact(paths["rsi"], rel(check.run_dir, paths["rsi"]), inside=True)
    if not got:
        return
    fm, body = got
    where = "rsi_report.md"
    f_int(check, fm, "schema_version", where, lo=SCHEMA_VERSION, hi=SCHEMA_VERSION)
    f_int(check, fm, "iteration", where, lo=iteration, hi=iteration)
    tier = f_enum(check, fm, "tier", where, tuple(TIER_RANGES))
    if state.get("tier") and tier and tier != state["tier"]:
        check.err(f"{where}：tier 必须等于本 run 的等级 {state['tier']}")
    scores = state.get("scores") or []
    last = scores[-1] if scores else {}
    verdict_in = f_enum(check, fm, "verdict_in", where, VERDICTS)
    if last and verdict_in and verdict_in != last.get("verdict"):
        check.err(f"{where}：verdict_in 必须等于本轮合并结论 {last.get('verdict')}")
    score_in = f_int(check, fm, "score_in", where, lo=0, hi=100)
    if last and score_in is not None and score_in != last.get("total"):
        check.err(f"{where}：score_in 必须等于本轮合并总分 {last.get('total')}")

    worker_ids = set((state.get("workers") or {}).get("ids") or [])
    valid_targets = worker_ids | {"all", "final", "main"}
    taxonomy = f_list(check, fm, "error_taxonomy", where, min_len=0) or []
    taxonomy_classes: set[str] = set()
    for idx, item in enumerate(taxonomy, 1):
        if not isinstance(item, dict):
            check.err(f"{where}：error_taxonomy 第 {idx} 项必须是映射")
            continue
        klass = item.get("class")
        if klass not in ERROR_CLASSES:
            check.err(f"{where}：error_taxonomy 第 {idx} 项 class 非法（{klass}）")
        else:
            taxonomy_classes.add(str(klass))
        count = item.get("count")
        if not _is_int(count) or count < 1:
            check.err(f"{where}：error_taxonomy 第 {idx} 项 count 必须是正整数")
        targets = item.get("attributed_to")
        if not isinstance(targets, list) or not targets:
            check.err(f"{where}：error_taxonomy 第 {idx} 项缺少 attributed_to（信用分配）")
        else:
            for target in targets:
                if not isinstance(target, str) or not target.strip():
                    check.err(f"{where}：attributed_to 必须是非空字符串")
                    continue
                if target.startswith("plan.step-") or target.startswith("plan:"):
                    continue
                if target not in valid_targets:
                    check.err(
                        f"{where}：attributed_to 出现未知归属 `{target}`"
                        f"（可用：{', '.join(sorted(valid_targets))} 或 plan.step-N）"
                    )

    index, alias = _collect_round_errors(check.run_dir, state)
    items = f_list(check, fm, "items", where, min_len=0) or []
    if len(items) > MAX_COACH_ITEMS:
        check.err(f"{where}：items 不得超过 {MAX_COACH_ITEMS} 条（当前 {len(items)}）")
    must_fix = 0
    whitelist = _packet_url_whitelist(check.run_dir, state)
    item_ids: set[str] = set()
    normalized_items: list[dict[str, Any]] = []
    is_final = iteration >= int(state.get("n") or iteration)
    for idx, item in enumerate(items, 1):
        if not isinstance(item, dict):
            check.err(f"{where}：items 第 {idx} 项必须是映射")
            continue
        cid = item.get("id")
        if not isinstance(cid, str) or not COACH_ID_RE.match(cid):
            check.err(f"{where}：items 第 {idx} 项 id 必须是 C1 形式")
            cid = f"C{idx}"
        if cid in item_ids:
            check.err(f"{where}：教练条目 id 重复：{cid}")
        item_ids.add(cid)
        from_error = item.get("from_error")
        if not isinstance(from_error, list) or not from_error:
            check.err(f"{where}：{cid} 必须给 from_error（指向本轮真实 error id）")
            from_error = []
        resolved: list[str] = []
        for ref in from_error:
            if not isinstance(ref, str):
                check.err(f"{where}：{cid} 的 from_error 必须是字符串")
                continue
            composite = resolve_error_ref(ref, index, alias)
            if composite is None:
                if ref in alias and len(alias[ref]) > 1:
                    check.err(
                        f"{where}：{cid} 引用的 `{ref}` 在多位评审中有歧义，请写成 `A:{ref}`"
                    )
                else:
                    check.err(f"{where}：{cid} 的 from_error 指向不存在的 error `{ref}`")
            else:
                resolved.append(composite)
        for key in ("root_cause", "action", "verification"):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip():
                check.err(f"{where}：{cid} 缺少 {key}（教练条目必须可执行、可核对）")
        applies = item.get("applies_to")
        if not isinstance(applies, list) or not applies:
            check.err(f"{where}：{cid} 缺少 applies_to")
            applies = []
        for target in applies:
            if target not in valid_targets:
                check.err(f"{where}：{cid} 的 applies_to 出现未知目标 `{target}`")
        priority = item.get("priority")
        if priority not in COACH_PRIORITIES:
            check.err(f"{where}：{cid} 的 priority 必须是 {'/'.join(COACH_PRIORITIES)}")
        elif priority == "must_fix":
            must_fix += 1
        normalized_items.append(
            {
                "id": cid,
                "from_error": resolved,
                "applies_to": [str(a) for a in applies],
                "priority": str(priority or ""),
                "root_cause": str(item.get("root_cause") or ""),
                "action": str(item.get("action") or ""),
                "verification": str(item.get("verification") or ""),
            }
        )
    if must_fix > MAX_MUST_FIX:
        check.err(f"{where}：must_fix 不得超过 {MAX_MUST_FIX} 条（当前 {must_fix}）")

    # 事实锁：不得引入 packet 之外的 URL（防止教练变成第二个 Final Agent）
    body_urls = {normalise_url(u) for u in URL_RE.findall(body)} | {
        normalise_url(u)
        for item in items
        if isinstance(item, dict)
        for u in URL_RE.findall(" ".join(str(v) for v in item.values()))
    }
    extra_urls = sorted(u for u in body_urls if u not in whitelist)
    if extra_urls:
        check.err(f"{where}：出现评审包之外的 URL（教练不得引入新事实）：{', '.join(extra_urls)}")

    skipped = fm.get("rsi_skipped")
    if not is_final and verdict_in in ("REVISE", "FAIL"):
        if not items and not (isinstance(skipped, str) and skipped.strip()):
            check.err(f"{where}：{verdict_in} 轮必须给出 items，或写明 rsi_skipped 理由")
    if not is_final and verdict_in == "PASS":
        if not items and not (isinstance(skipped, str) and skipped.strip()):
            check.err(f"{where}：PASS 轮可跳过教练，但必须写 rsi_skipped 说明")

    stuck = set((state.get("coach") or {}).get("stuck_classes") or [])
    escalations = f_list(check, fm, "escalations", where, min_len=0) or []
    escalated: set[str] = set()
    for idx, item in enumerate(escalations, 1):
        if not isinstance(item, dict):
            check.err(f"{where}：escalations 第 {idx} 项必须是映射")
            continue
        klass = item.get("class")
        reason = item.get("reason")
        if klass not in ERROR_CLASSES:
            check.err(f"{where}：escalations 第 {idx} 项 class 非法")
        else:
            escalated.add(str(klass))
        if not isinstance(reason, str) or not reason.strip():
            check.err(f"{where}：escalations 第 {idx} 项缺少 reason")
    missing_escalation = sorted(stuck - escalated)
    if missing_escalation:
        check.err(
            f"{where}：以下错误类别已连续两轮复发，必须在本报告 escalations 中升级给 PLAN："
            f"{', '.join(missing_escalation)}"
        )
    suggest = {str(h) for h in (fm.get("dream_hints") or []) if isinstance(h, str)}
    if any(not s.strip() for s in suggest):
        check.warn(f"{where}：dream_hints 存在空条目")

    advisory_input = None
    if is_final:
        advisory_input = f_dict(check, fm, "advisory_input", where)
        if advisory_input is not None:
            gain = advisory_input.get("estimated_gain_next_round")
            if not _is_int(gain) or not (0 <= gain <= 30):
                check.err(f"{where}：advisory_input.estimated_gain_next_round 必须是 0–30 整数")
            f_list(check, advisory_input, "remaining_gaps", f"{where} advisory_input", min_len=0)
            f_bool(check, advisory_input, "diminishing", f"{where} advisory_input")
            rationale = advisory_input.get("rationale")
            if not isinstance(rationale, str) or len(rationale.strip()) < 10:
                check.err(f"{where}：advisory_input.rationale 至少 10 字（理由由教练写）")
    check.data["coach"] = {
        "iteration": iteration,
        "verdict_in": verdict_in,
        "score_in": score_in,
        "items": normalized_items,
        "taxonomy_classes": taxonomy_classes,
        "advisory_input": advisory_input,
        "escalations": sorted(escalated),
        "skipped": isinstance(skipped, str) and bool(skipped.strip()),
    }
    validate_body(check, body, where)


def validate_advisory(check: Check) -> None:
    """末轮建议由代码计算生成；这里只校验文件未被手改、字段自洽。"""
    state = check.state
    iteration = state["current_iter"]
    paths = run_paths(check.run_dir, iteration)
    expected = state.get("advisory")
    path = paths["advisory"]
    if not path.exists():
        if expected:
            check.err("缺少产物：iterations/iter-NN/iteration_advisory.md（应由脚本生成）")
        return
    got = check.artifact(path, rel(check.run_dir, path), inside=True)
    if not got:
        return
    fm, body = got
    where = "iteration_advisory.md"
    f_int(check, fm, "schema_version", where, lo=SCHEMA_VERSION, hi=SCHEMA_VERSION)
    f_int(check, fm, "iteration", where, lo=iteration, hi=iteration)
    f_enum(check, fm, "verdict", where, VERDICTS)
    f_int(check, fm, "score", where, lo=0, hi=100)
    f_enum(check, fm, "recommendation", where, ("continue", "stop"))
    f_int(check, fm, "recommended_rounds", where, lo=0, hi=ADVISORY_MAX_ROUNDS)
    f_enum(check, fm, "trend", where, ("improving", "flat", "declining"))
    rationale = fm.get("rationale")
    if not isinstance(rationale, str) or len(rationale.strip()) < 10:
        check.err(f"{where}：rationale 至少 10 字（由教练在 rsi_report 的 advisory_input 提供）")
    if expected:
        for key in (
            "score",
            "verdict",
            "delta",
            "recommendation",
            "recommended_rounds",
            "gap_to_pass",
            "trend",
        ):
            if fm.get(key) != expected.get(key):
                check.err(
                    f"{where}：`{key}` 与脚本计算不一致（写 {fm.get(key)}，应为 {expected.get(key)}）"
                    "——该文件由脚本生成，不要手改"
                )


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
    validate_advisory(check)
    # 留痕门禁：建议续跑时，必须记录用户选择。
    advisory = check.state.get("advisory") or {}
    if advisory.get("recommendation") == "continue":
        response = fm.get("advisory_response")
        if response not in ("accept", "decline"):
            check.err(
                f"{where}：上轮建议续跑 {advisory.get('recommended_rounds')} 轮，"
                "必须先向用户播报并写 `advisory_response: accept|decline`"
            )
        elif response == "decline":
            reason = fm.get("advisory_reason")
            if not isinstance(reason, str) or len(reason.strip()) < 10:
                check.err(f"{where}：decline 时必须写 advisory_reason（至少 10 字）")
        elif not check.state.get("extended"):
            check.warn(
                f"{where}：advisory_response=accept 但未 extend；"
                "如需继续迭代请先运行 `orchestrator.py extend --rounds N`"
            )
    elif advisory:
        response = fm.get("advisory_response")
        if response not in (None, "accept", "decline"):
            check.err(f"{where}：advisory_response 只能是 accept/decline")
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
    elif phase == "COACH":
        validate_coach(check)
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
    review_cfg = state.get("review", {})
    version = review_cfg.get("policy_version", "v0")
    rubric = load_rubric(run_dir, version)
    reviewers = int(review_cfg.get("reviewers", 1))
    roles = review_cfg.get("roles") or {}
    reports: dict[str, dict[str, Any]] = {}
    for idx in range(1, reviewers + 1):
        reviewer = review_letter(idx)
        path = review_report_path(run_dir, iteration, reviewer)
        fm, _ = read_artifact(path)
        computed = compute_review(fm, rubric)
        audit = fm.get("citation_audit") if isinstance(fm.get("citation_audit"), dict) else {}
        coverage = audit.get("coverage") if isinstance(audit.get("coverage"), dict) else {}
        reports[reviewer] = {
            "id": reviewer,
            "role": str(fm.get("role") or roles.get(reviewer, "general")),
            "total": computed["total"],
            "verdict": computed["verdict"],
            "gate_failures": computed["gate_failures"],
            "dimensions": {
                d.get("name"): int(d.get("score", 0))
                for d in (fm.get("dimensions") or [])
                if isinstance(d, dict) and _is_int(d.get("score"))
            },
            "citation_coverage": coverage,
        }
    totals = [r["total"] for r in reports.values()]
    merged_total = int(round(sum(totals) / len(totals))) if totals else 0
    if any(r["verdict"] == "FAIL" for r in reports.values()):
        merged_verdict = "FAIL"
    elif merged_total < REVISE_THRESHOLD:
        merged_verdict = "FAIL"
    elif merged_total < PASS_THRESHOLD:
        merged_verdict = "REVISE"
    else:
        merged_verdict = "PASS"
    # C3：分歧超过阈值不得 PASS（会被平均值吞掉）。
    disagreements: list[dict[str, Any]] = []
    if len(reports) >= 2:
        for name in rubric["weights"]:  # C1b：跟随当前策略的维度集合
            scored = [
                (r["id"], r["dimensions"].get(name, 0)) for r in reports.values()
            ]
            values = [value for _, value in scored]
            delta = max(values) - min(values)
            if delta > DISAGREEMENT_DELTA:
                spread = " / ".join(f"{rid}={value}" for rid, value in scored)
                disagreements.append(
                    {"dimension": name, "delta": delta, "detail": spread}
                )
    downgrade_reason = None
    if disagreements and merged_verdict == "PASS":
        merged_verdict = "REVISE"
        downgrade_reason = (
            "维度分歧超过 10 分，禁止 PASS，需第三人复核或重审："
            + "；".join(f"{d['dimension']}（{d['detail']}）" for d in disagreements)
        )
    # 引用核验的合并口径：unverifiable 超 20% 不得 PASS。
    citation_notes: list[str] = []
    for report in reports.values():
        coverage = report.get("citation_coverage") or {}
        total = coverage.get("total")
        unverifiable = coverage.get("unverifiable")
        if _is_int(total) and total > 0 and _is_int(unverifiable):
            ratio = unverifiable / total
            if ratio > CITATION_MAX_UNVERIFIABLE_RATIO and merged_verdict == "PASS":
                merged_verdict = "REVISE"
                downgrade_reason = (
                    downgrade_reason
                    or f"引用不可核实比例 {ratio:.0%} 超过 {CITATION_MAX_UNVERIFIABLE_RATIO:.0%}，禁止 PASS"
                )
            citation_notes.append(
                f"{report['id']}: {coverage.get('verified', 0)}/{total} verified"
            )
    merged_dimensions: dict[str, int] = {}
    if reports:
        for name in rubric["weights"]:
            values = [r["dimensions"].get(name, 0) for r in reports.values()]
            merged_dimensions[name] = int(round(sum(values) / len(values)))
    gate_failures = sorted({g for r in reports.values() for g in r["gate_failures"]})
    return {
        "iteration": iteration,
        "rubric_version": version,
        "reviewers": [
            {
                "id": r["id"],
                "role": r["role"],
                "total": r["total"],
                "verdict": r["verdict"],
            }
            for r in reports.values()
        ],
        "merged_total": merged_total,
        "merged_verdict": merged_verdict,
        "merged_dimensions": merged_dimensions,
        "gate_failures": gate_failures,
        "disagreements": disagreements,
        "downgrade_reason": downgrade_reason,
        "citation_audit": citation_notes,
    }


def write_scores(run_dir: Path, merged: dict[str, Any]) -> Path:
    paths = run_paths(run_dir, merged["iteration"])
    fm = {"schema_version": SCHEMA_VERSION, **merged}
    rows = "\n".join(
        f"| {r['id']} | {r.get('role', 'general')} | {r['total']} | {r['verdict']} |"
        for r in merged["reviewers"]
    )
    dims = merged.get("merged_dimensions") or {}
    dim_rows = "\n".join(
        f"| {DIM_LABELS.get(name, name)} | {score} |" for name, score in dims.items()
    )
    body = (
        "# 评审合成\n\n"
        f"- rubric：{merged['rubric_version']}\n"
        f"- 合成总分：**{merged['merged_total']}** · 结论：**{merged['merged_verdict']}**\n"
        f"- 一票否决项：{', '.join(merged['gate_failures']) or '无'}\n"
        f"- 评审分歧：{merged['disagreements'] or '无'}\n"
        + (f"- **降级原因**：{merged['downgrade_reason']}\n" if merged.get("downgrade_reason") else "")
        + (f"- 引用核验：{'；'.join(merged.get('citation_audit') or [])}\n" if merged.get("citation_audit") else "")
        + "\n| 评审 | 角色 | 总分 | 结论 |\n|---|---|---|---|\n" + rows + "\n"
        + ("\n## 合并维度均分\n\n| 维度 | 均分 |\n|---|---|\n" + dim_rows + "\n" if dim_rows else "")
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
    final_sources = final_fm.get("sources") or []
    citations = normalise_sources(final_sources if isinstance(final_sources, list) else [])
    truncated = False
    if len(citations) > CITATION_MAX_ITEMS:
        citations = citations[:CITATION_MAX_ITEMS]
        truncated = True
    review_cfg = state.get("review", {})
    audit_required = (
        state.get("tier") == "Large" and str(review_cfg.get("citation_audit", "auto")) != "off"
    )
    fm = {
        "schema_version": SCHEMA_VERSION,
        "iteration": iteration,
        "tier": state.get("tier"),
        "task": task_fm.get("task", state.get("task", "")),
        "acceptance": plan_fm.get("accepted_criteria") or [],
        "rubric_version": rubric_version,
        "reviewers": int(review_cfg.get("reviewers", 1)),
        "roles": review_cfg.get("roles") or {},
        "citations": citations,
        "citations_truncated": truncated,
        "citation_policy": {
            "required": audit_required,
            "min_verified_ratio": CITATION_MIN_VERIFIED_RATIO,
            "max_unverifiable_ratio": CITATION_MAX_UNVERIFIABLE_RATIO,
            "gate_on": ["fabricated", "misattributed"],
        },
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
        f"- 验收标准：{'; '.join(str(x) for x in fm['acceptance'])}\n"
        f"- 评审角色：{json.dumps(fm['roles'], ensure_ascii=False)}\n"
        f"- 引用核验：{'必须（B 专责，逐条 100% 覆盖）' if audit_required else '不需要'}"
        f" · 来源 {len(citations)} 条{'（已截断到前 40 条）' if truncated else ''}\n\n"
        "## 可读产物\n\n"
        + "\n".join(f"- `{a['path']}`（{a['producer']}）" for a in artifacts)
        + "\n"
        + (
            "\n## 引用清单（核验对象）\n\n"
            "| id | 标题 | 位置 | URL |\n|---|---|---|---|\n"
            + "\n".join(
                f"| {c['id']} | {c['title'][:40]} | {c['locator']} | {c['url']} |"
                for c in citations
            )
            + "\n"
            if citations
            else "\n## 引用清单\n\n（final_result.sources 为空：本轮无可核验的外部来源）\n"
        )
    )
    write_artifact(paths["packet"], fm, body)
    return paths["packet"]


# --------------------------------------------------------------------------- #
# 教练考核 / 末轮建议 / 续跑
# --------------------------------------------------------------------------- #
def _collect_errors_for(
    run_dir: Path, state: dict[str, Any], iteration: int
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    reviewers = int(state.get("review", {}).get("reviewers", 1))
    scratch = Check(run_dir, state)
    reviews: dict[str, dict[str, Any]] = {}
    for idx in range(1, reviewers + 1):
        letter = review_letter(idx)
        path = run_paths(run_dir, iteration)["iter_dir"] / f"review_report_{letter}.md"
        if not path.exists():
            continue
        try:
            fm, _ = read_artifact(path)
        except TeamworkError:
            continue
        reviews[letter] = {
            "errors": normalise_errors(scratch, fm.get("errors") or [], path.name)
        }
    return build_error_index(reviews)


def _record_coach_progress(
    run_dir: Path, state: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    """把本轮教练条目与上一轮错误对上账，算出命中率与"卡住"的类别。

    命中率衡量的是**上一轮**的教练条目：本轮的错误里有几条是它想消灭的老问题。
    因此第 1 轮没有命中率（没有"上一轮条目"可考核）。
    """
    iteration = int(state["current_iter"])
    coach = state.setdefault("coach", {"entries": [], "stuck_classes": [], "ineffective": []})
    entries: list[dict[str, Any]] = coach.setdefault("entries", [])
    items = payload.get("items") or []
    own_errors: set[str] = set()
    for item in items:
        own_errors |= {str(x) for x in item.get("from_error") or []}
    prev_entry = entries[-1] if entries else None
    covered: set[str] = {str(x) for x in (prev_entry or {}).get("item_errors") or []}

    current_index, _ = _collect_errors_for(run_dir, state, iteration)
    prev_index, prev_alias = _collect_errors_for(run_dir, state, iteration - 1)
    recurred: set[str] = set()
    recurred_classes: set[str] = set()
    for composite, err in current_index.items():
        ref = err.get("recurred_from")
        if not ref:
            continue
        prev_composite = resolve_error_ref(str(ref), prev_index, prev_alias)
        if prev_composite and prev_composite in covered:
            recurred.add(prev_composite)
            recurred_classes.add(str(err.get("class") or "unclassified"))

    hit_rate = None
    if prev_entry is not None and covered:
        hit_rate = round(1 - len(recurred) / len(covered), 3)

    prev_classes = set((prev_entry or {}).get("taxonomy_classes") or [])
    current_classes = set(payload.get("taxonomy_classes") or [])
    stuck = (prev_classes & recurred_classes) | (
        set(coach.get("stuck_classes") or []) & current_classes
    )
    coach["stuck_classes"] = sorted(stuck)
    ineffective = sorted(set(coach.get("ineffective") or []) | stuck)
    coach["ineffective"] = ineffective

    entry = {
        "iteration": iteration,
        "evaluates": (prev_entry or {}).get("iteration"),
        "items": [item["id"] for item in items],
        "item_errors": sorted(own_errors),
        "covered": sorted(covered),
        "recurred": sorted(recurred),
        "hit_rate": hit_rate,
        "taxonomy_classes": sorted(current_classes),
        "stuck_classes": sorted(stuck),
        "escalations": payload.get("escalations") or [],
        "at": now_iso(),
    }
    entries.append(entry)
    return {**entry, "items": items}


def should_emit_advisory(state: dict[str, Any]) -> bool:
    if state.get("aborted"):
        return False
    return state.get("n_mode") == "explicit" or state.get("advisory_mode") == "always"


def compute_advisory(
    run_dir: Path, state: dict[str, Any], coach_payload: dict[str, Any]
) -> dict[str, Any]:
    """数字全部由代码算，理由由教练写（advisory_input.rationale）。"""
    scores = [s for s in (state.get("scores") or []) if isinstance(s, dict)]
    last = scores[-1] if scores else {"total": 0, "verdict": "FAIL", "dimensions": {}}
    score = int(last.get("total") or 0)
    verdict = str(last.get("verdict") or "FAIL")
    prev = int(scores[-2]["total"]) if len(scores) >= 2 else None
    delta = None if prev is None else score - prev
    if delta is None or delta == 0:
        trend = "flat"
    elif delta > 0:
        trend = "improving"
    else:
        trend = "declining"
    dims = last.get("dimensions") or {}
    if dims:
        name, value = min(dims.items(), key=lambda kv: int(kv[1]))
        weakest = {"name": str(name), "score": int(value)}
    else:
        weakest = {"name": "", "score": 0}
    gap = max(0, PASS_THRESHOLD - score)
    deltas = [
        int(b["total"]) - int(a["total"]) for a, b in zip(scores, scores[1:])
    ]
    history_max = max([d for d in deltas if d > 0], default=0)
    rubric = load_rubric(run_dir, state.get("review", {}).get("policy_version", "v0"))
    noise = int(rubric.get("noise_floor") or 5)
    advisory_input = coach_payload.get("advisory_input") or {}
    expected_gain = int(advisory_input.get("estimated_gain_next_round") or 0)
    if expected_gain <= 0:
        expected_gain = max(1, history_max or 1)

    if verdict == "FAIL":
        recommendation = "continue"
        rounds = 2 if gap > 20 else 1
    elif verdict == "REVISE":
        if (delta is not None and delta <= 0) and history_max <= 2:
            recommendation, rounds = "stop", 0
        else:
            gain = max(1, min(expected_gain, history_max or expected_gain))
            recommendation = "continue"
            rounds = 1 if gap <= gain else 2
    else:  # PASS
        if delta is not None and delta < noise:
            recommendation, rounds = "stop", 0
        elif int(weakest["score"]) < 80:
            recommendation, rounds = "continue", 1
        else:
            recommendation, rounds = "stop", 0
    cap = min(ADVISORY_MAX_ROUNDS, max(0, N_MAX - int(state.get("n") or 0)))
    rounds = max(0, min(int(rounds), cap))
    if rounds == 0:
        recommendation = "stop"

    rationale = str(advisory_input.get("rationale") or "").strip()
    if not rationale:
        rationale = (
            f"本轮 {score} 分 {verdict}，较上轮 {delta if delta is not None else '无'}；"
            f"短板 {DIM_LABELS.get(weakest['name'], weakest['name'])} {weakest['score']}，"
            f"距 PASS 差 {gap} 分。"
        )
    return {
        "iteration": int(state["current_iter"]),
        "n_mode": state.get("n_mode"),
        "score": score,
        "verdict": verdict,
        "prev_score": prev,
        "delta": delta,
        "trend": trend,
        "weakest_dimension": weakest,
        "gap_to_pass": gap,
        "recommendation": recommendation,
        "recommended_rounds": rounds,
        "expected_gain": expected_gain,
        "rationale": rationale,
        "generated_at": now_iso(),
    }


def write_advisory(run_dir: Path, state: dict[str, Any], advisory: dict[str, Any]) -> Path:
    path = run_paths(run_dir, int(state["current_iter"]))["advisory"]
    body = (
        "# 末轮建议（脚本计算，教练写理由）\n\n"
        f"- 本轮：**{advisory['score']} 分 / {advisory['verdict']}**"
        f"（上轮 {advisory['prev_score'] if advisory['prev_score'] is not None else '—'}，"
        f"变化 {advisory['delta'] if advisory['delta'] is not None else '—'}）\n"
        f"- 趋势：{advisory['trend']}；短板："
        f"{DIM_LABELS.get(advisory['weakest_dimension']['name'], advisory['weakest_dimension']['name'])}"
        f" {advisory['weakest_dimension']['score']}；距 PASS 差 {advisory['gap_to_pass']} 分\n"
        f"- 建议：**{advisory['recommendation']}**"
        + (
            f"，再迭代 {advisory['recommended_rounds']} 轮"
            if advisory["recommendation"] == "continue"
            else "，收尾"
        )
        + f"（预计单轮增益 {advisory['expected_gain']} 分）\n\n"
        f"## 理由\n\n{advisory['rationale']}\n\n"
        "## 告知用户（主 Agent 必做）\n\n"
        f"> 本轮 **{advisory['score']} 分 / {advisory['verdict']}**"
        f"（较上轮 {advisory['delta'] if advisory['delta'] is not None else '—'}，"
        f"短板：{DIM_LABELS.get(advisory['weakest_dimension']['name'], '—')}"
        f" {advisory['weakest_dimension']['score']}）。"
        + (
            f"**建议再迭代 {advisory['recommended_rounds']} 轮**："
            if advisory["recommendation"] == "continue"
            else "**建议就此收尾**："
        )
        + f"{advisory['rationale']}"
        + (
            f"若就此收尾，以下遗留会写入最终报告："
            f"{'; '.join(str(g) for g in (advisory.get('remaining_gaps') or [])) or '无'}。"
            if advisory["recommendation"] == "stop"
            else "如需继续，运行 `orchestrator.py extend --rounds "
            f"{advisory['recommended_rounds']}`。"
        )
        + "\n"
    )
    write_artifact(path, {"schema_version": SCHEMA_VERSION, **advisory}, body)
    return path


def extend_run(
    run_dir: Path, rounds: int, reason: str = "", *, force: bool = False
) -> dict[str, Any]:
    state = load_state(run_dir)
    if state["finished"]:
        raise TeamworkError("该 run 已收尾（finished=true），不能再追加轮次")
    if state.get("aborted"):
        raise TeamworkError("该 run 已 stop，不能追加轮次")
    if state["phase"] != "DONE":
        raise TeamworkError("只有 DONE 阶段才能 extend（先在当前轮完成 COACH）")
    if not (1 <= rounds <= ADVISORY_MAX_ROUNDS):
        raise TeamworkError(f"--rounds 必须在 1–{ADVISORY_MAX_ROUNDS}")
    old_iter = int(state["current_iter"])
    old_n = int(state.get("n") or old_iter)
    new_iter = old_iter + 1
    new_n = old_iter + rounds
    if new_n > N_MAX:
        raise TeamworkError(f"延长后总轮数 {new_n} 超过上限 {N_MAX}")
    final_report = run_paths(run_dir, old_iter)["final_report"]
    if final_report.exists():
        if not force:
            raise TeamworkError(
                "final_report.md 已存在；追加轮次会作废它，请加 --force 归档后再延长"
            )
        archive = final_report.with_name(f"final_report.iter-{old_iter:02d}.md")
        final_report.replace(archive)
    state["current_iter"] = new_iter
    state["n"] = new_n
    state["n_mode"] = "explicit"
    state["phase"] = "PLAN"
    state["advisory"] = None
    state["extended"] = int(state.get("extended") or 0) + 1
    append_history(
        state,
        "extend",
        f"{old_iter} -> {new_iter}（n {old_n} -> {new_n}，+{rounds} 轮）{('：' + reason) if reason else ''}",
    )
    save_state(run_dir, state)
    render_run(run_dir)
    return {
        "from_iteration": old_iter,
        "to_iteration": new_iter,
        "n": new_n,
        "phase": state["phase"],
    }


def set_citation_audit(run_dir: Path, enabled: bool, reason: str = "") -> dict[str, Any]:
    state = load_state(run_dir)
    if state["phase"] not in ("INIT", "CLASSIFY", "PLAN"):
        raise TeamworkError("引用核验只能在 INIT/CLASSIFY/PLAN 阶段开关（审核开始后锁定）")
    state["review"]["citation_audit"] = "on" if enabled else "off"
    if enabled and state.get("tier") == "Large":
        state["review"]["reviewers"] = max(2, int(state["review"].get("reviewers", 1)))
    append_history(state, "citation-audit", f"{'on' if enabled else 'off'} {reason}".strip())
    save_state(run_dir, state)
    render_run(run_dir)
    return {
        "citation_audit": state["review"]["citation_audit"],
        "reviewers": state["review"].get("reviewers", 1),
    }


def coach_show(run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    coach = state.get("coach") or {}
    entries = coach.get("entries") or []
    return {
        "iteration": state["current_iter"],
        "stuck_classes": coach.get("stuck_classes") or [],
        "ineffective": coach.get("ineffective") or [],
        "entries": entries[-3:],
        "advisory": state.get("advisory"),
    }


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
        "review": {
            "policy_version": "v0",
            "reviewers": 1,
            "dual_review_approved": False,
            "roles": {"A": "general"},
            "citation_audit": "auto",
        },
        "rework_count": 0,
        "scores": [],
        "coach": {"entries": [], "stuck_classes": [], "ineffective": []},
        "advisory": None,
        "advisory_mode": "auto",
        "extended": 0,
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
        # 引用核验：L 级默认 2 位评审（A 通用 / B 引用核验）。
        review_cfg = state.setdefault("review", {})
        audit = str(review_cfg.get("citation_audit", "auto"))
        if tier == "Large" and audit != "off":
            if not review_cfg.get("reviewers_explicit"):
                review_cfg["reviewers"] = max(2, int(review_cfg.get("reviewers", 1)))
            if int(review_cfg.get("reviewers", 1)) < 2:
                # 用户显式只设了 1 位评审：尊重用户，等价于关闭引用核验。
                review_cfg["citation_audit"] = "off"
                audit = "off"
            else:
                roles = {"A": "general", "B": "citation_audit"}
                for idx in range(3, int(review_cfg.get("reviewers", 2)) + 1):
                    roles.setdefault(review_letter(idx), "general")
                review_cfg["roles"] = roles
        append_history(
            state,
            "classify",
            f"tier={tier} n={state['n']} workers={state['workers']['planned']}"
            f" reviewers={review_cfg.get('reviewers', 1)}"
            f" audit={'on' if tier == 'Large' and audit != 'off' else 'off'}",
        )
    elif phase == "PLAN":
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
                "dimensions": merged.get("merged_dimensions") or {},
            }
        )
        append_history(state, "review", f"{merged['merged_total']} {merged['merged_verdict']}")
    elif phase == "COACH":
        coach_data = _record_coach_progress(
            check.run_dir, state, check.data.get("coach") or {}
        )
        skipped = bool((check.data.get("coach") or {}).get("skipped"))
        if skipped:
            append_history(state, "coach", "skipped (PASS)")
        else:
            append_history(
                state,
                "coach",
                f"items={len(coach_data['items'])} hit_rate={coach_data.get('hit_rate')}",
            )
        is_final = int(state["current_iter"]) >= int(state.get("n") or 0)
        if is_final and should_emit_advisory(state):
            advisory = compute_advisory(check.run_dir, state, check.data.get("coach") or {})
            write_advisory(check.run_dir, state, advisory)
            state["advisory"] = advisory
            state.setdefault("advisory_history", []).append(advisory)
            append_history(
                state,
                "advisory",
                f"{advisory['recommendation']} +{advisory['recommended_rounds']} "
                f"({advisory['score']} {advisory['verdict']})",
            )
        if not is_final:
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
        next_phase = "COACH"
    elif phase == "COACH":
        next_phase = "PLAN" if int(state["current_iter"]) < int(state.get("n") or 0) else "DONE"
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
        "advisory": state.get("advisory"),
        "coach": ((state.get("coach") or {}).get("entries") or [{}])[-1],
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
    experience: dict[str, Any] | None = None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import rsi_store  # noqa: WPS433

        experience = rsi_store.record_run(run_dir)
    except Exception as exc:  # 经验库失败不回滚收尾，但必须如实返回
        experience = {"error": str(exc)}
    return {
        "run_dir": str(run_dir),
        "final_report": rel(
            run_dir, run_paths(run_dir, state["current_iter"])["final_report"]
        ),
        "advisory": state.get("advisory"),
        "experience": experience,
    }


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
    if state["phase"] in ("REVIEW", "COACH", "DONE"):
        raise TeamworkError("审核已经开始，不能再调整评审人数")
    if not (1 <= count <= MAX_REVIEWERS):
        raise TeamworkError(f"评审人数必须在 1–{MAX_REVIEWERS} 之间")
    state["review"]["reviewers"] = count
    state["review"]["reviewers_explicit"] = True
    state["review"]["dual_review_approved"] = bool(approved and count > 1)
    roles = {"A": "general"}
    if count >= 2 and state.get("tier") == "Large" and state["review"].get("citation_audit") != "off":
        roles["B"] = "citation_audit"
    for idx in range(1, count + 1):
        letter = review_letter(idx)
        roles.setdefault(letter, "general")
    state["review"]["roles"] = {k: v for k, v in roles.items() if k in {review_letter(i) for i in range(1, count + 1)}}
    append_history(state, "set-reviewers", f"count={count}")
    save_state(run_dir, state)
    render_run(run_dir)
    return {
        "reviewers": count,
        "roles": state["review"]["roles"],
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
    roles = state.get("review", {}).get("roles") or {}
    audit = state.get("review", {}).get("citation_audit", "auto")
    parts.append(f"Reviewers {state.get('review', {}).get('reviewers', 1)}")
    if state.get("tier") == "Large" and audit != "off" and len(roles) >= 2:
        parts.append("Audit " + "/".join(f"{k}:{v}" for k, v in sorted(roles.items())))
    if state.get("scores"):
        last = state["scores"][-1]
        parts.append(f"Score {last['total']} {last['verdict']}")
    advisory = state.get("advisory") or {}
    if advisory.get("recommendation") == "continue":
        parts.append(f"建议 +{advisory.get('recommended_rounds')} 轮")
    elif advisory.get("recommendation") == "stop":
        parts.append("建议收尾")
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
        coach_items: list[dict[str, Any]] = []
        if iteration > 1:
            prev_rsi = run_paths(run_dir, iteration - 1)["rsi"]
            if prev_rsi.exists():
                try:
                    rfm, _ = read_artifact(prev_rsi)
                except TeamworkError:
                    rfm = {}
                coach_items = [
                    {
                        "id": item.get("id"),
                        "applies_to": item.get("applies_to") or [],
                        "action": item.get("action"),
                        "verification": item.get("verification"),
                        "priority": item.get("priority"),
                    }
                    for item in (rfm.get("items") or [])
                    if isinstance(item, dict) and item.get("id")
                ]
        lessons: list[dict[str, Any]] = []
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import rsi_store  # noqa: WPS433

            lessons = rsi_store.retrieve_lessons(
                state=state,
                error_classes=(state.get("coach") or {}).get("ineffective") or [],
                limit=5,
            )
        except Exception:  # 经验库是可选增强，缺失不应阻断派发
            lessons = []
        coach_hint = ""
        if coach_items:
            coach_hint = (
                f"上一轮教练有 {len(coach_items)} 条条目：必须逐条编译进 worker 的 coach_items"
                "（按 applies_to 切片；不能下发的写 coach_deferred + reason，不能删除）。"
            )
        common.update(
            instruction=(
                "把计划拆成可并行的 worker 任务，写 dispatch 文件（worker id 用 w01…）。"
                "worker 数按「本任务（本 run）」累计：L 级 5–7（+Final=8），S 1–2、M 3–4；"
                "同一对话/上下文的其它任务各自独立计数、互不占用名额。"
                + coach_hint
                + reuse_hint
                + "然后 advance。"
            ),
            outputs=[rel(run_dir, paths["dispatch"])],
            next_command="python scripts/orchestrator.py advance",
            coach_items=coach_items,
            lessons=lessons,
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
        roles = state.get("review", {}).get("roles") or {}
        report_rels = [
            rel(run_dir, review_report_path(run_dir, iteration, letter))
            for letter in letters
        ]
        role_text = "、".join(
            f"{letter}={roles.get(letter, 'general')}" for letter in letters
        )
        common.update(
            instruction=(
                "启动全新独立审核子 Agent（不得继承上下文），只准读 review_packet.md 与其中 "
                "artifacts；角色：" + role_text + "。"
                "citation_audit 角色必须逐条核验 packet.citations 并交出 citation_audit 台账"
                "（100% 覆盖，verified 需 method+checked_at+locator）。"
                "errors 用对象格式 {id, class, located, recurred_from}，老问题要标 recurred_from。"
                "写 " + "、".join(f"review_report_{x}.md" for x in letters)
                + "；然后 advance（脚本会自动合成 review_scores.md）。"
            ),
            subagents={
                "role": "reviewer",
                "independent": True,
                "reviewers": reviewers,
                "roles": {letter: roles.get(letter, "general") for letter in letters},
                "packet": rel(run_dir, paths["packet"]),
                "forbidden": ["run_report.md", "state.json", "iteration_summary.md", "其他评审报告"],
                "agents": [
                    {
                        "reviewer": letter,
                        "role": roles.get(letter, "general"),
                        "agent_name": reviewer_agent_name(str(state["run_id"]), letter),
                        "output": rel(run_dir, review_report_path(run_dir, iteration, letter)),
                        "prompt_reference": (
                            "references/protocol.md#reviewer-b"
                            if roles.get(letter) == "citation_audit"
                            else "references/protocol.md#reviewer"
                        ),
                    }
                    for letter in letters
                ],
                "prompt_reference": "references/protocol.md#reviewer",
                "outputs": report_rels,
            },
            outputs=report_rels,
            next_command="python scripts/orchestrator.py advance",
        )
    elif phase == "COACH":
        is_final = int(state["current_iter"]) >= int(state.get("n") or 0)
        if is_final:
            instruction = (
                "启动全新 RSI 教练（与评审不同实例，不继承评审上下文）：读本轮 review_report_*、"
                "review_scores.md、final_result.md、plan/dispatch、artifacts；禁读 run_report.md、"
                "state.json、历史轮评审。这是最后一轮：items 可留空，但必须写 advisory_input"
                "（estimated_gain_next_round / remaining_gaps / diminishing / rationale ≥10 字）。"
                "写 iterations/iter-NN/rsi_report.md；advisory 由脚本生成，不要手写。"
            )
        else:
            instruction = (
                "启动全新 RSI 教练（与评审不同实例，不继承评审上下文）：读本轮 review_report_*、"
                "review_scores.md、final_result.md、plan/dispatch、artifacts；禁读 run_report.md、"
                "state.json、历史轮评审。产出 ≤8 条 items（must_fix ≤3），每条必须给 "
                "from_error / root_cause / action / applies_to / verification；不合规的条目会被 "
                "validate_coach 拒绝。写 iterations/iter-NN/rsi_report.md 后 advance。"
            )
        common.update(
            instruction=instruction,
            subagents={
                "role": "coach",
                "independent": True,
                "agent_name": coach_agent_name(str(state["run_id"])),
                "prompt_reference": "references/protocol.md#coach",
                "forbidden": ["run_report.md", "state.json", "历史轮 review_report", "其他 worker 产物"],
                "outputs": [rel(run_dir, paths["rsi"])],
            },
            outputs=[rel(run_dir, paths["rsi"])],
            next_command="python scripts/orchestrator.py advance",
            coach_history=(state.get("coach") or {}).get("entries") or [],
            stuck_classes=(state.get("coach") or {}).get("stuck_classes") or [],
        )
    elif phase == "DONE":
        advisory = state.get("advisory") or {}
        instruction = (
            "写 final_report.md（含分数轨迹）；建议续跑时必须写 advisory_response: accept|decline"
            "（decline 要写 advisory_reason ≥10 字），然后运行 finish 收尾（生成 score_trend.png）。"
        )
        if advisory:
            instruction = (
                "先把下面三句话原样播报给用户，并记录其决定；再写 final_report.md"
                "（含 advisory_response），最后 finish。"
            )
        common.update(
            instruction=instruction,
            outputs=[rel(run_dir, paths["final_report"])],
            next_command="python scripts/orchestrator.py finish",
            advisory=advisory or None,
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
        "coach": {
            "entries": (state.get("coach") or {}).get("entries") or [],
            "stuck_classes": (state.get("coach") or {}).get("stuck_classes") or [],
        },
        "advisory": state.get("advisory"),
        "finished": state.get("finished", False),
        "aborted": state.get("aborted", False),
        "progress": rel(run_dir, paths["progress"]),
        "framework_png": rel(run_dir, paths["framework_png"]),
        "next": build_next(run_dir) if not state.get("finished") else None,
    }
