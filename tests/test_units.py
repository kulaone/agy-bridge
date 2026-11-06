"""Unit tests for the pieces that don't need a running AGY: registry, tree snapshots,
backups, agent lookup and JSON parsing."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import git

from agy_bridge import backup, paths, registry, selfcheck, tree
from agy_bridge.session import parse_json_response, reviewer_settings

# ----- registry ---------------------------------------------------------------------


def test_registry_roundtrip(state: Path) -> None:
    registry.put("s1", {"cwd": "/p", "turns": 0})
    assert registry.update("s1", turns=2)["turns"] == 2
    assert registry.update("missing", turns=1) is None
    assert registry.get("s1")["turns"] == 2
    registry.remove("s1")
    assert registry.get("s1") is None


def test_corrupt_registry_is_kept_aside(state: Path) -> None:
    paths.SESSIONS_FILE.write_text("{not json")
    assert registry.list_all() == {}
    assert paths.SESSIONS_FILE.with_suffix(".corrupt.json").exists()


def test_claim_and_release(state: Path) -> None:
    registry.put("s1", {"cwd": "/p"})
    registry.claim("s1", os.getpid())
    registry.claim("s1", os.getpid())  # re-claiming your own session is fine
    registry.release("s1", os.getpid())
    assert registry.get("s1")["owner_pid"] is None


def _fake_bridge() -> subprocess.Popen:
    """A process whose command line names agy_bridge, so it counts as a live bridge."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "agy_bridge"])
    # Right after the fork, Linux can still show the parent's command line for a moment.
    deadline = time.time() + 10
    while not registry.is_live_bridge(proc.pid) and time.time() < deadline:
        time.sleep(0.05)
    assert registry.is_live_bridge(proc.pid), (
        f"exit={proc.poll()} args={registry.command_line(proc.pid)} exe={sys.executable}")
    return proc


def test_claim_refused_while_another_bridge_lives(state: Path) -> None:
    other = _fake_bridge()
    try:
        registry.put("s1", {"cwd": "/p", "owner_pid": other.pid})
        with pytest.raises(registry.SessionInUse, match="in use by another agy-bridge"):
            registry.claim("s1", os.getpid())
    finally:
        other.kill()
        other.wait()
    registry.claim("s1", os.getpid())  # the owner is gone: taking over is allowed


def test_claim_ignores_unrelated_pid(state: Path) -> None:
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        registry.put("s1", {"cwd": "/p", "owner_pid": other.pid})
        registry.claim("s1", os.getpid())  # a reused PID that isn't a bridge
    finally:
        other.kill()
        other.wait()


def test_overlapping_turns(state: Path) -> None:
    bridge_proc = _fake_bridge()
    try:
        _check_overlaps(bridge_proc.pid)
    finally:
        bridge_proc.kill()
        bridge_proc.wait()


def _check_overlaps(me: int) -> None:
    now = time.time()
    registry.put("open", {"cwd": "/p", "turn_started": now - 100, "turn_ended": None,
                          "turn_pid": me})
    registry.put("before", {"cwd": "/p", "turn_started": now - 300, "turn_ended": now - 200,
                            "turn_pid": me})
    registry.put("other-project", {"cwd": "/q", "turn_started": now - 50, "turn_ended": None,
                                   "turn_pid": me})
    registry.put("crashed", {"cwd": "/p", "turn_started": now - 60, "turn_ended": None,
                             "turn_pid": 999_999})
    registry.put("ended-during", {"cwd": "/p", "turn_started": now - 400,
                                  "turn_ended": now - 90, "turn_pid": me})
    found = registry.overlapping_turns("me", "/p", now - 150, now)
    assert sorted(found) == ["ended-during", "open"]


# ----- tree snapshots ---------------------------------------------------------------


def test_tree_diff_reports_edits_and_tool_output(repo: Path) -> None:
    before = tree.snapshot(str(repo))
    time.sleep(0.01)
    with open(repo / "stats.py", "a") as f:
        f.write("# edit\n")
    (repo / "new.py").write_text("x = 1\n")
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "stats.cpython-311.pyc").write_bytes(b"\0")
    (repo / "ignored").mkdir()
    (repo / "ignored" / "cache.txt").write_text("ignored by .gitignore")
    report = tree.diff(before, tree.snapshot(str(repo)))
    assert report["files"] == {"modified": ["stats.py"], "created": ["new.py"]}
    assert report["likely_tool_output"] == ["__pycache__/stats.cpython-311.pyc"]
    assert "git" not in report


def test_tree_diff_reports_git_changes(repo: Path) -> None:
    before = tree.snapshot(str(repo))
    git(repo, "stash", "-q")
    report = tree.diff(before, tree.snapshot(str(repo)))
    assert "stash" in report["git"]
    assert report["files"]["modified"] == ["stats.py"]


def test_tree_unchanged_is_none(repo: Path) -> None:
    assert tree.diff(tree.snapshot(str(repo)), tree.snapshot(str(repo))) is None


def test_tree_outside_git(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("x")
    snap = tree.snapshot(str(tmp_path))
    assert list(snap.files) == ["a.txt"]


# ----- backup -----------------------------------------------------------------------


def test_backup_restores_destroyed_work(state: Path, repo: Path) -> None:
    git(repo, "add", "stats.py")  # staged ...
    with open(repo / "stats.py", "a") as f:  # ... plus unstaged
        f.write("# unstaged\n")
    (repo / "notes.txt").write_text("untracked\n")
    (repo / "ignored").mkdir()
    (repo / "ignored" / "big.bin").write_text("ignored")
    expected = {p: (repo / p).read_text() for p in ("stats.py", "notes.txt")}

    manifest = backup.take("s1", 1, str(repo))
    assert manifest["untracked_copied"] == 1
    git(repo, "reset", "-q", "--hard")
    git(repo, "clean", "-qfd")
    assert not (repo / "notes.txt").exists()

    d = Path(manifest["dir"])
    git(repo, "checkout", "-q", manifest["head"], "--", ".")
    git(repo, "apply", "--binary", str(d / "tracked.patch"))
    shutil.copytree(d / "untracked", repo, dirs_exist_ok=True)
    assert {p: (repo / p).read_text() for p in expected} == expected
    assert "tracked.patch" in backup.restore_hint(manifest)


def test_backup_restores_with_a_staged_new_file_still_there(state: Path, repo: Path) -> None:
    (repo / "pkg").mkdir()
    (repo / "pkg" / "__init__.py").write_text("")
    git(repo, "add", "pkg/__init__.py")
    git(repo, "commit", "-q", "-m", "pkg")
    (repo / "pkg" / "new.py").write_text("added\n")
    git(repo, "add", "pkg/new.py")
    expected = {p: (repo / p).read_text() for p in ("stats.py", "pkg/new.py")}

    # From the subfolder too: the patch must still apply there.
    for cwd in (repo, repo / "pkg"):
        manifest = backup.take("s3", 1, str(cwd))
        for p in expected:
            with open(repo / p, "a") as f:
                f.write("# damage\n")
        d = Path(manifest["dir"])
        git(cwd, "checkout", "-q", manifest["head"], "--", ".")
        if (d / "tracked.patch").exists():
            git(cwd, "apply", "--binary", str(d / "tracked.patch"))
        shutil.copytree(d / "untracked", cwd, dirs_exist_ok=True)
        restored = expected if cwd == repo else {"pkg/new.py": expected["pkg/new.py"]}
        assert {p: (repo / p).read_text() for p in restored} == restored
        (repo / "stats.py").write_text(expected["stats.py"])


def test_backup_keeps_last_five(state: Path, repo: Path) -> None:
    for turn in range(1, 8):
        backup.take("s1", turn, str(repo))
    kept = sorted(p.name for p in backup.backup_root("s1").iterdir())
    assert kept == [f"turn-{n:03d}" for n in range(3, 8)]
    backup.remove("s1")
    assert not backup.backup_root("s1").exists()


def test_backup_outside_git(state: Path, tmp_path: Path) -> None:
    proj = tmp_path / "plain"
    proj.mkdir()
    (proj / "doc.md").write_text("hello")
    manifest = backup.take("s2", 1, str(proj))
    assert (Path(manifest["dir"]) / "untracked" / "doc.md").read_text() == "hello"


# ----- agents and parsing -----------------------------------------------------------


def test_nearest_agent_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "code-reviewer.md").write_text("---\nname: code-reviewer\n---\n")
    monkeypatch.setattr(paths, "GLOBAL_AGENTS_DIR", global_dir)
    proj = tmp_path / "proj" / "sub"
    proj.mkdir(parents=True)
    assert selfcheck.find_agent_file("code-reviewer", str(proj)) == global_dir / "code-reviewer.md"
    local = tmp_path / "proj" / ".agents" / "agents"
    local.mkdir(parents=True)
    (local / "code-reviewer.md").write_text("---\nname: code-reviewer\n---\n")
    assert selfcheck.find_agent_file("code-reviewer", str(proj)) == local / "code-reviewer.md"
    assert selfcheck.find_agent_file("nobody", str(proj)) is None


def test_agent_tools_bad_yaml(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    f.write_text("---\ntools: [unclosed\n---\n")
    with pytest.raises(ValueError, match="invalid YAML"):
        selfcheck.agent_tools(f)


def test_agent_tools_must_be_a_list(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    f.write_text("---\ntools: finish\n---\n")
    with pytest.raises(ValueError, match="must be a list"):
        selfcheck.agent_tools(f)


def test_version_warning() -> None:
    assert selfcheck.version_warning("1.5.2") is None
    assert "not been tested" in selfcheck.version_warning("9.0.0")


@pytest.mark.parametrize("text", [
    '{"verdict": "approve"}',
    'Sure:\n```json\n{"verdict": "approve"}\n```\nDone.',
    'Result {"verdict": "approve"} trailing words',
])
def test_parse_json_response(text: str) -> None:
    assert parse_json_response(text) == {"verdict": "approve"}


def test_parse_json_response_none() -> None:
    assert parse_json_response("no json here") is None


def test_reviewer_settings_scope_writes_to_scratch(state: Path) -> None:
    allow = __import__("json").loads(reviewer_settings("abc"))["permissions"]["allow"]
    assert allow == ["command(regex:.*)", f"write_file({paths.SCRATCH_DIR / 'abc'}/)"]
