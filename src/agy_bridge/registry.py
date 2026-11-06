"""Persistent session registry (~/.agy-bridge/sessions.json).

Several Claude Code sessions may each run their own bridge process, so every
read-modify-write happens under an exclusive file lock and the file is replaced
atomically.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from . import paths


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextlib.contextmanager
def _locked() -> Iterator[dict[str, Any]]:
    paths.ensure_dirs()
    lock_path = paths.SESSIONS_FILE.with_suffix(".lock")
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = _read()
            yield data
            _write(data)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read() -> dict[str, Any]:
    try:
        with open(paths.SESSIONS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        # Keep the corrupt file for inspection rather than silently losing it.
        paths.SESSIONS_FILE.rename(paths.SESSIONS_FILE.with_suffix(".corrupt.json"))
        return {}


def _write(data: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(dir=paths.STATE_DIR, prefix=".sessions.", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, paths.SESSIONS_FILE)


def get(session_id: str) -> dict[str, Any] | None:
    return _read().get(session_id)


def find_by_conversation(conversation_id: str) -> tuple[str, dict[str, Any]] | None:
    for sid, rec in _read().items():
        if rec.get("conversation_id") == conversation_id:
            return sid, rec
    return None


def put(session_id: str, record: dict[str, Any]) -> None:
    with _locked() as data:
        data[session_id] = record


def update(session_id: str, **fields: Any) -> dict[str, Any] | None:
    with _locked() as data:
        rec = data.get(session_id)
        if rec is None:
            return None
        rec.update(fields)
        return dict(rec)


def remove(session_id: str) -> None:
    with _locked() as data:
        data.pop(session_id, None)


def list_all() -> dict[str, dict[str, Any]]:
    return _read()


# ----- ownership: one live bridge process per session ---------------------------


class SessionInUse(RuntimeError):
    pass


def command_line(pid: int) -> list[str] | None:
    """A process's arguments, or None if they can't be read."""
    try:  # Linux: exact, NUL-separated
        raw = open(f"/proc/{pid}/cmdline", "rb").read()
        return [a.decode(errors="replace") for a in raw.split(b"\0") if a]
    except FileNotFoundError:
        if os.path.isdir("/proc/self"):
            return []  # /proc exists, so the process is gone
    except OSError:
        pass
    try:  # macOS and others; -ww: never cut long lines
        out = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "command="],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.split()


def is_live_bridge(pid: int) -> bool:
    """True if pid is a running agy-bridge process (guards against PID reuse)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    args = command_line(pid)
    if args is None:
        return True  # can't tell: assume live, the safe choice
    # Match the program, not any path: a repo folder named agy-bridge appears in the
    # command line of every tool run from its venv. A bridge runs as `.../agy-bridge`
    # (console script) or `python -m agy_bridge`.
    return any(os.path.basename(a) == "agy-bridge" or a == "agy_bridge" for a in args)


def claim(session_id: str, pid: int) -> None:
    """Mark this bridge process as the session's owner, or raise SessionInUse."""
    with _locked() as data:
        rec = data.get(session_id)
        if rec is None:
            raise KeyError(session_id)
        owner = rec.get("owner_pid")
        if owner and owner != pid and is_live_bridge(owner):
            raise SessionInUse(
                f"session {session_id} is in use by another agy-bridge process (pid {owner}), "
                "probably another Claude Code window. Finish or agy_end it there, or start "
                "a new session.")
        rec["owner_pid"] = pid


def release(session_id: str, pid: int) -> None:
    with _locked() as data:
        rec = data.get(session_id)
        if rec and rec.get("owner_pid") == pid:
            rec["owner_pid"] = None


# ----- overlapping turns on one project ------------------------------------------


def overlapping_turns(session_id: str, cwd: str, start: float, end: float) -> list[str]:
    """Other sessions on `cwd` whose latest turn overlapped [start, end].

    Each session records only its latest turn (turn_started / turn_ended / turn_pid);
    that is enough, since any earlier turn that overlapped is followed by one that
    started before `end` too. A turn left open by a crashed bridge is ignored.
    """
    found = []
    for sid, rec in _read().items():
        if sid == session_id or rec.get("cwd") != cwd:
            continue
        started, ended = rec.get("turn_started"), rec.get("turn_ended")
        if not started or started > end:
            continue
        if ended is None:
            pid = rec.get("turn_pid")
            if not pid or not is_live_bridge(pid):
                continue
        elif ended < start:
            continue
        found.append(sid)
    return found
