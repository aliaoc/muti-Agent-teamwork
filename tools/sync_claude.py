#!/usr/bin/env python3
"""把「源技能」同步到仓库内的 Claude Code 项目技能目录。

源（唯一事实来源）：
    skills/teamwork/
目标（Claude Code 在项目内自动发现的技能）：
    .claude/skills/teamwork/

为什么需要同步而不是软链接：
    - Claude Code 的项目技能要求是真实目录（Windows 上软链接还需要开发者模式）；
    - 但插件形态（`.claude-plugin/plugin.json`）读的又是 `skills/`，两处不能各改一半。

用法：
    python3 tools/sync_claude.py            # 同步（会重建目标目录）
    python3 tools/sync_claude.py --check    # 只校验是否一致；不一致 exit 2（CI 用）
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = REPO_ROOT / "skills" / "teamwork"
DEFAULT_DST = REPO_ROOT / ".claude" / "skills" / "teamwork"

# 这些内容不应该被复制/校验
IGNORE_DIR_PARTS = {"__pycache__", ".pytest_cache", "teamwork-runs", ".git"}
IGNORE_SUFFIXES = {".pyc", ".pyo"}
IGNORE_NAMES = {".DS_Store", "Thumbs.db", ".env"}


def _should_skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in IGNORE_DIR_PARTS for part in rel.parts):
        return True
    if path.suffix.lower() in IGNORE_SUFFIXES:
        return True
    if path.name in IGNORE_NAMES:
        return True
    return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(root: Path) -> dict[str, str]:
    """返回 {相对路径: sha256}。"""
    result: dict[str, str] = {}
    if not root.is_dir():
        return result
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if _should_skip(path, root):
            continue
        result[path.relative_to(root).as_posix()] = sha256_file(path)
    return result


def diff_snapshots(src: dict[str, str], dst: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for rel in sorted(set(src) | set(dst)):
        if rel not in dst:
            problems.append(f"  缺少: {rel}")
        elif rel not in src:
            problems.append(f"  多余: {rel}")
        elif src[rel] != dst[rel]:
            problems.append(f"  内容不同: {rel}")
    return problems


def sync(src: Path, dst: Path) -> int:
    if not src.is_dir():
        print(f"[错误] 源技能目录不存在: {src}", file=sys.stderr)
        return 2
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    src_snap, dst_snap = snapshot(src), snapshot(dst)
    problems = diff_snapshots(src_snap, dst_snap)
    if problems:
        print("[错误] 同步后校验不一致：", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
        return 2
    print(f"[ok] 已同步 {len(src_snap)} 个文件：{src} -> {dst}")
    return 0


def check(src: Path, dst: Path) -> int:
    src_snap, dst_snap = snapshot(src), snapshot(dst)
    problems = diff_snapshots(src_snap, dst_snap)
    if problems:
        print("[失败] .claude/skills 与 skills/ 不一致，请运行 `python3 tools/sync_claude.py`：", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
        return 2
    print(f"[ok] .claude/skills/teamwork 与 skills/teamwork 一致（{len(src_snap)} 个文件）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="同步/校验 skills/teamwork 与 .claude/skills/teamwork")
    parser.add_argument("--check", action="store_true",
                        help="只检查，不改动；不一致时 exit 2")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC, help="源技能目录")
    parser.add_argument("--dst", type=Path, default=DEFAULT_DST, help="Claude Code 项目技能目录")
    args = parser.parse_args()
    return check(args.src, args.dst) if args.check else sync(args.src, args.dst)


if __name__ == "__main__":
    raise SystemExit(main())
