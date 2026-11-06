"""Working-tree snapshots, used to detect (never block) changes AGY makes.

In a git repo we stat every tracked file plus untracked files that aren't
ignored, and record HEAD, stashes and worktrees. Ignored files (most caches and
build output) are skipped. Outside git we walk the tree with a fixed exclude list.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

MAX_FILES = 100_000
WALK_EXCLUDES = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
                 ".mypy_cache", ".ruff_cache", ".tox", "dist", "build", ".next", ".cache"}
# Paths that test runners, linters and builds commonly create. Changes here are
# reported separately as probable tool output rather than edits.
TOOL_OUTPUT_MARKERS = ("__pycache__/", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/",
                       ".tox/", ".coverage", "coverage/", "htmlcov/", ".nyc_output/",
                       "node_modules/", ".next/", "dist/", "build/", ".cache/", ".gradle/",
                       "target/", ".build/", "DerivedData/")


@dataclass
class Snapshot:
    files: dict[str, tuple[int, int]]  # path -> (size, mtime_ns)
    git: dict[str, str] = field(default_factory=dict)
    truncated: bool = False


def _git(cwd: str, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.decode(errors="replace") if out.returncode == 0 else None


def _stat_all(root: Path, rel_paths: list[str]) -> dict[str, tuple[int, int]]:
    files = {}
    for rel in rel_paths:
        try:
            st = (root / rel).lstat()
        except OSError:
            continue
        files[rel] = (st.st_size, st.st_mtime_ns)
    return files


def snapshot(cwd: str) -> Snapshot:
    root = Path(cwd)
    listing = _git(cwd, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if listing is not None:
        rels = [p for p in listing.split("\0") if p][:MAX_FILES + 1]
        git = {
            "head": (_git(cwd, "rev-parse", "HEAD") or "").strip(),
            "branch": (_git(cwd, "branch", "--show-current") or "").strip(),
            "stash": _git(cwd, "stash", "list") or "",
            "worktrees": _git(cwd, "worktree", "list", "--porcelain") or "",
        }
        return Snapshot(_stat_all(root, rels[:MAX_FILES]), git, len(rels) > MAX_FILES)

    rels: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in WALK_EXCLUDES]
        for name in filenames:
            rels.append(os.path.relpath(os.path.join(dirpath, name), root))
        if len(rels) > MAX_FILES:
            break
    return Snapshot(_stat_all(root, rels[:MAX_FILES]), {}, len(rels) > MAX_FILES)


def _is_tool_output(path: str) -> bool:
    slashed = "/" + path
    name = os.path.basename(path)
    for m in TOOL_OUTPUT_MARKERS:
        if m.endswith("/") and "/" + m in slashed:
            return True
        if not m.endswith("/") and name.startswith(m):
            return True
    return False


def diff(before: Snapshot, after: Snapshot) -> dict | None:
    """Return a change report, or None if nothing changed."""
    b, a = before.files, after.files
    created = sorted(set(a) - set(b))
    deleted = sorted(set(b) - set(a))
    modified = sorted(p for p in set(a) & set(b) if a[p] != b[p])

    report: dict = {}
    edits = {"modified": [p for p in modified if not _is_tool_output(p)],
             "created": [p for p in created if not _is_tool_output(p)],
             "deleted": [p for p in deleted if not _is_tool_output(p)]}
    edits = {k: v for k, v in edits.items() if v}
    if edits:
        report["files"] = edits
    tool_output = sorted(p for p in created + modified + deleted if _is_tool_output(p))
    if tool_output:
        report["likely_tool_output"] = tool_output[:50] + (["…"] if len(tool_output) > 50 else [])

    git_changes = {k: {"before": before.git.get(k), "after": after.git.get(k)}
                   for k in ("head", "branch", "stash", "worktrees")
                   if before.git.get(k) != after.git.get(k)}
    if git_changes:
        report["git"] = git_changes
    if before.truncated or after.truncated:
        report["note"] = f"tree larger than {MAX_FILES} files; snapshot was partial"
    return report or None
