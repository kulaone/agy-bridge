"""Per-turn backup of the user's uncommitted work, taken before AGY runs.

Write safety is prompt-guided, so if AGY ever destroys work (`git reset --hard`,
`git clean`, an overwriting test) the user must be able to get it back. Before
each turn we save, without touching the repo:

  tracked.patch   `git diff HEAD --binary`: staged + unstaged changes to files in HEAD
  untracked/      copies of untracked, non-ignored files and of newly added (staged)
                  files, size-capped. Added files are copied rather than patched so that
                  `git apply` can't fail on a file that is still on disk.
  manifest.json   HEAD, branch, a `git stash create` commit, what was copied/skipped

Restore: `git checkout <head> && git apply --binary tracked.patch`, then copy
untracked/ back. Outside git, files are copied the same way, capped.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from . import paths, tree

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
KEEP_PER_SESSION = 5


def backup_root(session_id: str) -> Path:
    return paths.STATE_DIR / "backup" / session_id


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=120)


def _copy_files(root: Path, rels: list[str], dest: Path) -> tuple[list[str], list[str]]:
    copied, skipped, total = [], [], 0
    for rel in rels:
        src = root / rel
        try:
            if src.is_symlink() or not src.is_file():
                continue
            size = src.stat().st_size
        except OSError:
            continue
        if size > MAX_FILE_BYTES or total + size > MAX_TOTAL_BYTES:
            skipped.append(rel)
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        copied.append(rel)
        total += size
    return copied, skipped


def take(session_id: str, turn: int, cwd: str) -> dict[str, Any]:
    """Back up the working tree for `turn`. Returns the manifest (with its folder path)."""
    dest = backup_root(session_id) / f"turn-{turn:03d}"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    root = Path(cwd)
    manifest: dict[str, Any] = {"cwd": cwd, "turn": turn, "created": time.time(), "dir": str(dest)}

    head = _git(cwd, "rev-parse", "HEAD")
    if head.returncode == 0:
        manifest["head"] = head.stdout.decode().strip()
        manifest["branch"] = _git(cwd, "branch", "--show-current").stdout.decode().strip()
        stash = _git(cwd, "stash", "create")
        manifest["stash_commit"] = stash.stdout.decode().strip() or None
        # Only cwd's part of the repo. The patch keeps repo-root paths, which is what
        # `git apply` expects even when run from a subfolder; the copies use cwd paths.
        diff = _git(cwd, "diff", "HEAD", "--no-renames", "--binary", "--diff-filter=a",
                    "--", ".")
        if diff.returncode == 0 and diff.stdout:
            (dest / "tracked.patch").write_bytes(diff.stdout)
            manifest["tracked_patch"] = "tracked.patch"
        added = _git(cwd, "diff", "HEAD", "--no-renames", "--relative", "--name-only", "-z",
                     "--diff-filter=A")
        others = _git(cwd, "ls-files", "-z", "--others", "--exclude-standard")
        rels = [p for out in (added, others)
                for p in out.stdout.decode(errors="replace").split("\0") if p]
    elif _git(cwd, "rev-parse", "--git-dir").returncode == 0:
        # Repo without commits: everything is untracked.
        others = _git(cwd, "ls-files", "-z", "--others", "--cached", "--exclude-standard")
        rels = [p for p in others.stdout.decode(errors="replace").split("\0") if p]
    else:
        rels = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in tree.WALK_EXCLUDES]
            rels += [os.path.relpath(os.path.join(dirpath, f), root) for f in filenames]

    copied, skipped = _copy_files(root, rels, dest / "untracked")
    manifest["untracked_copied"] = len(copied)
    if skipped:
        manifest["untracked_skipped"] = skipped[:50]
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2))
    _prune(session_id)
    return manifest


def _prune(session_id: str) -> None:
    turns = sorted(p for p in backup_root(session_id).glob("turn-*") if p.is_dir())
    for old in turns[:-KEEP_PER_SESSION]:
        shutil.rmtree(old, ignore_errors=True)


def remove(session_id: str) -> None:
    shutil.rmtree(backup_root(session_id), ignore_errors=True)


def restore_hint(manifest: dict[str, Any]) -> str:
    d = manifest["dir"]
    parts = []
    if manifest.get("head"):
        parts.append(f"tracked files: `git checkout {manifest['head'][:12]} -- . && "
                     f"git apply --binary {d}/tracked.patch`" if manifest.get("tracked_patch")
                     else f"tracked files: `git checkout {manifest['head'][:12]} -- .`")
    if manifest.get("untracked_copied"):
        parts.append(f"untracked and newly added files: copy back from {d}/untracked/")
    return "; ".join(parts) or f"see {d}"
