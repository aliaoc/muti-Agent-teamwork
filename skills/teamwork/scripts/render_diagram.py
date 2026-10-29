"""渲染 teamwork 运行图：framework.png / framework.mmd / PROGRESS.md / score_trend.png。

图布局是写死的（不随每轮重排），当前阶段高亮，角标显示 迭代 i/N。
本模块只读 state 与产物是否存在，不修改任何结论。
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import teamwork_lib as lib  # noqa: E402

MAIN_COLOR = "#4C78A8"
CURRENT_COLOR = "#F58518"
DONE_COLOR = "#72B7B2"
FUTURE_COLOR = "#DCDCDC"
FINAL_COLOR = "#B279A2"
REVIEW_COLOR = "#E45756"
STORE_COLOR = "#9D755D"
TEXT_DARK = "#333333"
TEXT_LIGHT = "#FFFFFF"

BOX_PHASES = [
    ("CLASSIFY", "分级", "CLASSIFY"),
    ("PLAN", "规划", "PLAN"),
    ("DISPATCH", "派发", "DISPATCH"),
    ("WORKERS", "执行", "WORKERS"),
    ("FINAL", "汇总", "FINAL"),
    ("GATE", "验收", "GATE"),
    ("REVIEW", "审核", "REVIEW"),
    ("COACH", "教练复盘", "COACH"),
]
BOX_INDEX = {name: idx for idx, (name, _, _) in enumerate(BOX_PHASES)}
ROW1 = [(0.14 + idx * 0.24, 0.705) for idx in range(4)]
ROW2 = [(0.14 + idx * 0.24, 0.520) for idx in range(4)]
BOX_W, BOX_H = 0.195, 0.088

WORKER_STATUS = {
    "completed": ("完成", "#54A24B"),
    "failed": ("失败", "#E45756"),
    "blocked": ("受阻", "#F5A623"),
    "invalid": ("异常", "#E45756"),
    "pending": ("待派", "#BDBDBD"),
}


def _setup_font() -> None:
    """跨平台中文字体：找到第一个可用字体就注册，找不到就用系统字体栈兜底。"""
    candidates = [
        Path.home() / ".fonts/NotoSansCJK-Regular.ttc",
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            font_manager.fontManager.addfont(str(candidate))
            name = font_manager.FontProperties(fname=str(candidate)).get_name()
            plt.rcParams["font.family"] = name
            break
    else:
        plt.rcParams["font.family"] = [
            "Noto Sans CJK SC",
            "WenQuanYi Micro Hei",
            "Microsoft YaHei",
            "PingFang SC",
            "DejaVu Sans",
            "sans-serif",
        ]
    plt.rcParams["axes.unicode_minus"] = False


_setup_font()


def _box(ax, x, y, w, h, fc, ec, text, *, fontsize=10, sub=None, bold=False, text_color=TEXT_LIGHT):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.008,rounding_size=0.012",
        linewidth=1.4,
        facecolor=fc,
        edgecolor=ec,
        zorder=3,
    )
    ax.add_patch(patch)
    if sub:
        ax.text(
            x + w / 2,
            y + h * 0.62,
            text,
            ha="center",
            va="center",
            fontsize=fontsize,
            color=text_color,
            fontweight="bold" if bold else "normal",
            zorder=4,
        )
        ax.text(
            x + w / 2,
            y + h * 0.26,
            sub,
            ha="center",
            va="center",
            fontsize=max(6.0, fontsize - 3),
            color=text_color,
            alpha=0.85,
            zorder=4,
        )
    else:
        ax.text(
            x + w / 2,
            y + h / 2,
            text,
            ha="center",
            va="center",
            fontsize=fontsize,
            color=text_color,
            fontweight="bold" if bold else "normal",
            zorder=4,
        )


def _arrow(ax, start, end, *, style="-|>", color="#666666", lw=1.2, dashed=False, rad=0.0, zorder=2):
    connection = "arc3,rad=0" if rad == 0 else f"arc3,rad={rad}"
    patch = FancyArrowPatch(
        start,
        end,
        arrowstyle=style,
        connectionstyle=connection,
        color=color,
        linewidth=lw,
        linestyle="--" if dashed else "-",
        mutation_scale=11,
        zorder=zorder,
        shrinkA=1,
        shrinkB=1,
    )
    ax.add_patch(patch)


def _phase_state(state: dict) -> tuple[int, int]:
    phase = state.get("phase", "INIT")
    current = BOX_INDEX.get(phase, -1)
    if phase == "DONE":
        current = len(BOX_PHASES)
    return current, len(BOX_PHASES)


def _draw(state: dict, run_dir: Path):
    fig = plt.figure(figsize=(12.8, 7.6), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_facecolor("#FAFAFA")
    fig.patch.set_facecolor("#FAFAFA")

    current, total_boxes = _phase_state(state)
    n = state.get("n") or "?"
    iteration = state.get("current_iter", 0)
    tier = state.get("tier") or "未分级"
    reviewers = state.get("review", {}).get("reviewers", 1)

    # 标题
    ax.text(
        0.5,
        0.990,
        "teamwork · 多子 Agent 协作运行图",
        ha="center",
        va="top",
        fontsize=15,
        fontweight="bold",
        color=TEXT_DARK,
    )
    task_full = str(state.get("task", "")).strip().replace("\n", " ")
    task_excerpt = task_full[:56] + ("…" if len(task_full) > 56 else "")
    ax.text(
        0.5,
        0.958,
        f"{state.get('run_id', '')} ｜ {task_excerpt}",
        ha="center",
        va="top",
        fontsize=8.5,
        color="#666666",
    )

    # 主 Agent
    _box(
        ax,
        0.29,
        0.850,
        0.42,
        0.080,
        MAIN_COLOR,
        "#2F5C86",
        "主 Agent｜规划 · 派发 · 验收 · 收尾",
        fontsize=11.5,
        bold=True,
    )
    # 主 Agent 到各阶段的连线
    ax.plot([0.5, 0.5], [0.850, 0.815], color="#888888", lw=1.2, zorder=1)
    ax.plot([0.14, 0.86], [0.815, 0.815], color="#888888", lw=1.2, zorder=1)
    for idx, (cx, top_y) in enumerate(ROW1):
        _arrow(ax, (cx, 0.815), (cx, top_y + BOX_H), color="#888888", lw=1.0)

    # 阶段方框（蛇形：row1 左→右，row2 右→左）
    def draw_phase_box(idx: int, cx: float, cy: float, name: str, label: str) -> None:
        if idx < current:
            fc, ec, color = DONE_COLOR, "#4C8C88", TEXT_DARK
        elif idx == current:
            fc, ec, color = CURRENT_COLOR, "#B85F00", TEXT_LIGHT
        else:
            fc, ec, color = FUTURE_COLOR, "#B0B0B0", "#777777"
        _box(ax, cx - BOX_W / 2, cy, BOX_W, BOX_H, fc, ec, label, fontsize=11, sub=name, bold=True, text_color=color)

    for idx, (name, label, _) in enumerate(BOX_PHASES[:4]):
        draw_phase_box(idx, *ROW1[idx], name, label)
    # row2 顺序：FINAL, GATE, REVIEW, COACH，但视觉从右到左，故 index 4..7 对应 cx
    for offset, idx in enumerate(range(4, 8)):
        cx = ROW1[3 - offset][0]
        cy = ROW2[offset][1]
        name, label, _ = BOX_PHASES[idx]
        draw_phase_box(idx, cx, cy, name, label)

    # row1 横向箭头
    for idx in range(3):
        x1 = ROW1[idx][0] + BOX_W / 2
        x2 = ROW1[idx + 1][0] - BOX_W / 2
        _arrow(ax, (x1, 0.749), (x2, 0.749))
    # WORKERS → FINAL（垂直下折）
    _arrow(ax, (ROW1[3][0], 0.705), (ROW1[3][0], ROW2[0][1] + BOX_H), color="#666666")
    # row2 横向箭头（从右到左）
    for offset in range(3):
        x1 = ROW1[3 - offset][0] - BOX_W / 2
        x2 = ROW1[3 - offset - 1][0] + BOX_W / 2
        _arrow(ax, (x1, 0.564), (x2, 0.564))
    # GATE → WORKERS 打回（虚线，显式短线，避免横穿 FINAL）
    _arrow(
        ax,
        (0.700, 0.608),
        (0.790, 0.705),
        dashed=True,
        color="#C0392B",
        lw=1.2,
        rad=0,
    )
    ax.text(
        0.720,
        0.645,
        "REWORK 打回",
        ha="right",
        va="center",
        fontsize=7.5,
        color="#C0392B",
    )
    # COACH → CLASSIFY 下一轮（左侧边距折线）
    ax.plot([0.0425, 0.016, 0.016], [0.564, 0.564, 0.742], color="#8E44AD", lw=1.2, ls="--", zorder=1)
    _arrow(ax, (0.016, 0.742), (0.0425, 0.749), dashed=True, color="#8E44AD", lw=1.2, rad=0)
    ax.text(
        0.034,
        0.655,
        "下一轮",
        ha="left",
        va="center",
        fontsize=7.5,
        color="#8E44AD",
    )

    # Worker 池（n 个时自动压缩 chip 宽度，避免与右侧面板重叠）
    workers = lib.worker_status(run_dir, state)
    ax.text(0.035, 0.415, "Worker 池", fontsize=9.5, fontweight="bold", color=TEXT_DARK)
    if workers:
        gap = 0.010
        max_w = 0.105
        avail = 0.530  # 0.035 起，右侧信息面板从 0.585 开始
        chip_w = min(max_w, (avail - gap * (len(workers) - 1)) / len(workers))
        chip_font = 8.5 if chip_w >= 0.095 else 8.0
        start_x = 0.035
        for idx, worker in enumerate(workers):
            x = start_x + idx * (chip_w + gap)
            label, color = WORKER_STATUS.get(worker["status"], ("未知", "#BDBDBD"))
            _box(
                ax,
                x,
                0.325,
                chip_w,
                0.055,
                color,
                color,
                f"{worker['id']}{'·复用' if worker.get('reused') else ''} {label}",
                fontsize=chip_font,
                bold=True,
            )
    else:
        ax.text(0.035, 0.345, "（尚未派发）", fontsize=9, color="#888888")

    # Artifact Store
    _box(
        ax,
        0.035,
        0.075,
        0.49,
        0.125,
        STORE_COLOR,
        "#6E5340",
        "Artifact Store（文件即接口 · append-only）",
        fontsize=9.5,
        sub="iterations/iter-XX/ · review_policy/ · state.json · manifests",
        bold=True,
    )

    # 右侧信息面板
    _box(
        ax,
        0.585,
        0.075,
        0.38,
        0.375,
        "#FFFFFF",
        "#BBBBBB",
        "",
        fontsize=9,
        text_color=TEXT_DARK,
    )
    ax.text(
        0.775,
        0.415,
        f"第 {iteration} / {n} 轮",
        ha="center",
        va="center",
        fontsize=20,
        fontweight="bold",
        color=MAIN_COLOR,
    )
    ax.text(
        0.775,
        0.375,
        f"等级 {tier} ｜ 当前阶段 {lib.PHASE_LABEL.get(state.get('phase'), state.get('phase'))}",
        ha="center",
        va="center",
        fontsize=9.5,
        color=TEXT_DARK,
    )
    ax.text(
        0.775,
        0.345,
        f"审核 ×{reviewers} ｜ 策略 {state.get('review', {}).get('policy_version', 'v0')}"
        f" ｜ 重做 {state.get('rework_count', 0)} 次",
        ha="center",
        va="center",
        fontsize=9,
        color=TEXT_DARK,
    )
    scores = state.get("scores") or []
    if scores:
        lines = [
            f"第 {item.get('iteration')} 轮：{item.get('total')} 分 · {item.get('verdict')}"
            for item in scores[-4:]
        ]
        ax.text(
            0.775,
            0.295,
            "分数轨迹\n" + "\n".join(lines),
            ha="center",
            va="top",
            fontsize=9,
            color=TEXT_DARK,
            linespacing=1.5,
        )
    else:
        ax.text(0.775, 0.285, "分数轨迹：尚未产生", ha="center", va="center", fontsize=9, color="#999999")
    # 状态行
    ax.text(
        0.035,
        0.028,
        lib.status_line(state),
        ha="left",
        va="center",
        fontsize=8.5,
        color="#555555",
    )
    ax.text(
        0.965,
        0.028,
        f"更新于 {state.get('updated_at', '')}",
        ha="right",
        va="center",
        fontsize=7.5,
        color="#888888",
    )
    return fig


from render_text import write_mermaid as _write_mermaid, write_progress as _write_progress
import render_text as _render_text


def render_png(run_dir: Path) -> dict[str, str]:
    """只渲染 framework.png；需要 matplotlib，由调用方决定是否降级。"""
    state = lib.load_state(run_dir)
    fig = _draw(state, run_dir)
    png = run_dir / "framework.png"
    fig.savefig(png, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    return {"framework_png": lib.rel(run_dir, png)}


def render_run(run_dir: Path) -> dict[str, str]:
    """渲染 PNG + 文本资产（文本部分不依赖 matplotlib）。"""
    result = render_png(run_dir)
    result.update(_render_text.render_text_assets(run_dir))
    return result


def render_score_trend(run_dir: Path) -> dict[str, str]:
    state = lib.load_state(run_dir)
    scores = state.get("scores") or []
    fig = plt.figure(figsize=(7.2, 4.2), dpi=150)
    ax = fig.add_subplot(111)
    if scores:
        xs = [item["iteration"] for item in scores]
        ys = [item["total"] for item in scores]
        ax.plot(xs, ys, marker="o", color=MAIN_COLOR, linewidth=2)
        for x, y, item in zip(xs, ys, scores):
            above = y >= 83
            ax.annotate(
                f"{y} {item['verdict']}",
                (x, y),
                textcoords="offset points",
                xytext=(0, 12 if above else -12),
                ha="center",
                va="bottom" if above else "top",
                fontsize=8,
                color="#444444",
            )
        ax.set_xticks(xs)
        ax.set_ylim(0, 105)
        ax.axhline(85, color="#54A24B", linestyle="--", linewidth=0.8)
        ax.axhline(60, color="#E45756", linestyle="--", linewidth=0.8)
        ax.text(
            0.012,
            84.6,
            "PASS 线 85",
            fontsize=7,
            color="#54A24B",
            transform=ax.get_yaxis_transform(),
            va="top",
        )
        ax.text(
            0.012,
            59.4,
            "FAIL 线 60",
            fontsize=7,
            color="#E45756",
            transform=ax.get_yaxis_transform(),
            va="top",
        )
    else:
        ax.text(0.5, 0.5, "尚无评分", ha="center", va="center", transform=ax.transAxes)
    ax.set_xlabel("迭代轮次")
    ax.set_ylabel("总分")
    ax.set_title(f"分数轨迹 · {state.get('run_id', '')}", fontsize=10)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    path = run_dir / "score_trend.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return {"score_png": lib.rel(run_dir, path)}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("用法: python render_diagram.py <run_dir>")
        return 2
    run_dir = Path(argv[0]).resolve()
    try:
        result = render_run(run_dir)
    except lib.TeamworkError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2
    print(f"已渲染：{result['framework_png']} / {result['framework_mmd']} / {result['progress']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
