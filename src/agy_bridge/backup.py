"""Per-turn backup of the user's uncommitted work, taken before AGY runs.

Write safety is prompt-guided, so if AGY ever destroys work (`git reset --hard`,
`git clean`, an overwriting test) the user must be able to get it back. Before
each turn we save, without touching the repo:

  tracked.patch   `git diff HEAD --binary`: staged + unstaged changes to files in HEAD
  untracked/      copies of untracked, non-ignored files and of newly added (staged)
                  files, size-capped. Added files are copied rather than patched so that
                  `git apply` can't fail on a file that is still on disk.
  manifest.json   HEAD, branch, what was copied, skipped or excluded

Restore: `git checkout <head> && git apply --binary tracked.patch`, then copy
untracked/ back. Outside git, files are copied the same way, capped.

Storage: every file under untracked/ is a hardlink into a content-addressed store,
`backup/blobs/<sha256>`, shared by all turns and sessions. A file that hasn't
changed since any earlier backup costs one directory entry. A blob is created by
linking from the turn's copy, so it is born with two links and is never seen
half-made by another bridge process; pruning removes blobs nothing links to.
Untracked files in tool-output folders (`__pycache__/`, `node_modules/`, `build/`...)
are not backed up; staged files always are.
"""

from __future__ import annotations

import hashlib
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
BLOBS = "blobs"


def backup_dir() -> Path:
    return paths.STATE_DIR / "backup"


def backup_root(session_id: str) -> Path:
    return backup_dir() / session_id


def blobs_dir() -> Path:
    return backup_dir() / BLOBS


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=120)


def _paths(out: subprocess.CompletedProcess[bytes]) -> list[str]:
    return [p for p in out.stdout.decode(errors="replace").split("\0") if p]


def _excluded(rel: str) -> bool:
    """Untracked files in tool-output folders are not worth backing up."""
    return any(p in tree.WALK_EXCLUDES for p in rel.split("/")[:-1])


def _blob_key(src: Path, executable: bool) -> str:
    with open(src, "rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    # Hardlinks share their mode, so identical bytes with and without +x stay apart.
    return f"{digest}-x" if executable else digest


def _place(src: Path, target: Path, executable: bool) -> None:
    """Put a copy of `src` at `target`, sharing storage with identical earlier copies."""
    target.parent.mkdir(parents=True, exist_ok=True)
    blob = blobs_dir() / _blob_key(src, executable)
    try:
        os.link(blob, target)
        return
    except FileNotFoundError:
        pass
    except OSError:
        target.unlink(missing_ok=True)  # never write through an existing link
        shutil.copy2(src, target)
        return
    shutil.copy2(src, target)
    try:
        blobs_dir().mkdir(parents=True, exist_ok=True)
        os.link(target, blob)
    except OSError:  # another bridge got there first, or no hardlinks here: keep the copy
        pass


def _copy_files(root: Path, rels: list[str], dest: Path) -> tuple[list[str], list[str]]:
    copied, skipped, total = [], [], 0
    for rel in rels:
        src = root / rel
        try:
            if src.is_symlink() or not src.is_file():
                continue
            st = src.stat()
        except OSError:
            continue
        if st.st_size > MAX_FILE_BYTES or total + st.st_size > MAX_TOTAL_BYTES:
            skipped.append(rel)
            continue
        _place(src, dest / rel, bool(st.st_mode & 0o111))
        copied.append(rel)
        total += st.st_size
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
        staged, untracked = _paths(added), _paths(others)
    elif _git(cwd, "rev-parse", "--git-dir").returncode == 0:
        # Repo without commits: everything is staged or untracked.
        staged = _paths(_git(cwd, "ls-files", "-z", "--cached"))
        untracked = _paths(_git(cwd, "ls-files", "-z", "--others", "--exclude-standard"))
    else:
        staged, untracked = [], []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in tree.WALK_EXCLUDES]
            untracked += [os.path.relpath(os.path.join(dirpath, f), root) for f in filenames]

    # A file the user staged is wanted whatever folder it is in; untracked tool output isn't.
    kept = [r for r in untracked if not _excluded(r)]
    copied, skipped = _copy_files(root, staged + kept, dest / "untracked")
    manifest["untracked_copied"] = len(copied)
    if skipped:
        manifest["untracked_skipped"] = skipped[:50]
    if len(kept) < len(untracked):
        manifest["untracked_excluded"] = len(untracked) - len(kept)
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2))
    _prune(session_id)
    return manifest


def _prune(session_id: str) -> None:
    turns = sorted(p for p in backup_root(session_id).glob("turn-*") if p.is_dir())
    for old in turns[:-KEEP_PER_SESSION]:
        shutil.rmtree(old, ignore_errors=True)
    prune_blobs()


def prune_blobs() -> None:
    """Drop blobs no turn links to any more."""
    try:
        entries = list(os.scandir(blobs_dir()))
    except OSError:
        return
    for e in entries:
        try:
            if e.stat().st_nlink <= 1:
                os.unlink(e.path)
        except OSError:
            pass


def remove(session_id: str) -> None:
    shutil.rmtree(backup_root(session_id), ignore_errors=True)
    prune_blobs()


def remove_orphans(known_sessions: set[str]) -> None:
    """Remove backups of sessions that no longer exist, then unreferenced blobs."""
    try:
        dirs = [d for d in backup_dir().iterdir() if d.is_dir()]
    except OSError:
        return
    for d in dirs:
        if d.name != BLOBS and d.name not in known_sessions:
            shutil.rmtree(d, ignore_errors=True)
    prune_blobs()


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
