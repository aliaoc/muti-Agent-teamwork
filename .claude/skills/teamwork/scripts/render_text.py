"""纯文本渲染：framework.mmd 与 PROGRESS.md（不依赖 matplotlib）。

PNG 渲染在 render_diagram.py；本模块保证没有 matplotlib 的环境也能拿到文本看板。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import teamwork_lib as lib  # noqa: E402


def write_mermaid(run_dir: Path, state: dict) -> Path:
    n = state.get("n") or "?"
    iteration = state.get("current_iter", 0)
    reviewers = state.get("review", {}).get("reviewers", 1)
    workers = state.get("workers", {}).get("ids") or []
    worker_label = f"Worker ×{len(workers)}" if workers else "Worker 池"
    current = state.get("phase", "INIT")
    lines = [
        "flowchart LR",
        '  M["主 Agent｜规划 · 派发 · 验收 · 收尾"]',
        f'  subgraph LOOP["第 {iteration}/{n} 轮 · 等级 {state.get("tier") or "未分级"}"]',
        '    C["分级"] --> P["规划"] --> D["派发"] --> W["' + worker_label + '"]',
        '    W --> F["Final 汇总"]',
        '    F --> G["主 Agent 验收"]',
        '    G -->|REWORK| W',
        '    G -->|PASS| R["审核 Agent ×' + str(reviewers) + '"]',
        '    R --> CO["教练复盘"]',
        '    CO -.下一轮.-> P',
        "  end",
        "  M --> C",
        "  S[(Artifact Store)] --- W",
    ]
    classes = {
        "CLASSIFY": "C",
        "PLAN": "P",
        "DISPATCH": "D",
        "WORKERS": "W",
        "FINAL": "F",
        "GATE": "G",
        "REVIEW": "R",
        "COACH": "CO",
    }
    lines.append("  classDef current fill:#F58518,stroke:#B85F00,color:#fff;")
    if current in classes:
        lines.append(f"  class {classes[current]} current;")
    path = run_dir / "framework.mmd"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_progress(run_dir: Path, state: dict) -> Path:
    n = state.get("n") or "?"
    workers = lib.worker_status(run_dir, state)
    rows = []
    for item in state.get("scores") or []:
        rows.append(
            f"| {item.get('iteration')} | {item.get('total')} | {item.get('verdict')} "
            f"| {item.get('policy_version', 'v0')} |"
        )
    if not rows:
        rows.append("| - | - | 尚未产生 | - |")
    worker_text = "、".join(
        f"{w['id']}{'（复用）' if w.get('reused') else ''}={w['status']}" for w in workers
    ) or "（尚未派发）"
    history = state.get("history") or []
    recent = "\n".join(
        f"- `{item.get('at', '')}` {item.get('event', '')} {item.get('detail', '')}".rstrip()
        for item in history[-8:]
    )
    body = f"""# teamwork 运行看板

- **run**：`{state.get('run_id', '')}`
- **任务**：{state.get('task', '')}
- **等级 / 迭代**：{state.get('tier') or '未分级'} / {n}
- **当前**：第 {state.get('current_iter')} 轮 · {lib.PHASE_LABEL.get(state.get('phase'), state.get('phase'))}
- **审核**：×{state.get('review', {}).get('reviewers', 1)}（策略 {state.get('review', {}).get('policy_version', 'v0')}）
- **Worker**：{worker_text}
- **状态行**：`{lib.status_line(state)}`

## 迭代记录

| 轮次 | 分数 | 结论 | rubric |
|---|---|---|---|
{chr(10).join(rows)}

## 最近事件

{recent}

## 产物入口

- 计划：`01_plans/plan-iter-{state.get('current_iter', 1):02d}.md`
- 派发：`01_plans/dispatch-iter-{state.get('current_iter', 1):02d}.md`
- 本轮：`iterations/iter-{state.get('current_iter', 1):02d}/`
- 策略：`review_policy/`
- 框架图：`framework.png`（同目录 `framework.mmd` 为 Mermaid 源码）

> 本文件由 `scripts/render_text.py` 自动生成，请勿手改。
"""
    path = run_dir / "PROGRESS.md"
    path.write_text(body, encoding="utf-8")
    return path


def render_text_assets(run_dir: Path) -> dict[str, str]:
    state = lib.load_state(run_dir)
    mmd = write_mermaid(run_dir, state)
    progress = write_progress(run_dir, state)
    return {
        "framework_mmd": lib.rel(run_dir, mmd),
        "progress": lib.rel(run_dir, progress),
    }
