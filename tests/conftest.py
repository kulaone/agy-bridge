"""Shared fixtures. Nothing here touches the real home folder, AGY or Claude Code:
`agy` is tests/fake_agy.py and `claude` is tests/fake_claude.py."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from agy_bridge import paths

TESTS = Path(__file__).resolve().parent


def _wrapper(bin_dir: Path, name: str, script: Path) -> Path:
    exe = bin_dir / name
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
    exe.chmod(0o755)
    return exe


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """Environment for running agy-bridge as a subprocess in a throwaway home."""
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    home.mkdir()
    bin_dir.mkdir()
    agy = _wrapper(bin_dir, "agy", TESTS / "fake_agy.py")
    _wrapper(bin_dir, "claude", TESTS / "fake_claude.py")
    e = {k: v for k, v in os.environ.items() if not k.startswith(("AGY_", "FAKE_AGY_"))}
    e.update(HOME=str(home), AGY_BIN=str(agy), AGY_BRIDGE_HOME=str(home / ".agy-bridge"),
             FAKE_AGY_STATE=str(tmp_path / "fake-agy"),
             PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return e


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the in-process bridge modules at a throwaway state folder."""
    root = tmp_path / "state"
    for name, value in {"STATE_DIR": root, "SESSIONS_FILE": root / "sessions.json",
                        "LOG_DIR": root / "logs", "SCRATCH_DIR": root / "scratch",
                        "CACHE_FILE": root / "cache.json",
                        "INSTALL_MANIFEST": root / "install.json"}.items():
        monkeypatch.setattr(paths, name, value)
    paths.ensure_dirs()
    return root


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                           "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with one commit and an uncommitted change, like a review target."""
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / ".gitignore").write_text("ignored/\n")
    (r / "stats.py").write_text("def mean(xs):\n    return sum(xs) / len(xs)\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "init")
    with open(r / "stats.py", "a") as f:
        f.write("\ndef mode(xs):\n    return max(xs, key=xs.count)\n")
    return r


def run_cli(env: dict[str, str], *args: str,
            cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "agy_bridge", *args], env=env, cwd=cwd,
                          capture_output=True, text=True, timeout=120)


@pytest.fixture
def installed(env: dict[str, str]) -> dict[str, str]:
    """The throwaway home with the example agent and skills installed."""
    out = run_cli(env, "install", "--no-register")
    assert out.returncode == 0, out.stdout + out.stderr
    return env


class Bridge:
    def __init__(self, session: ClientSession):
        self.session = session

    async def call(self, tool: str, **args: Any) -> Any:
        """Call a tool; returns its JSON result, or {"error": message} on a tool error.
        A list result (agy_sessions) arrives as one text block per item."""
        res = await self.session.call_tool(tool, args)
        texts = [getattr(c, "text", "") for c in res.content]
        if res.is_error:
            return {"error": "".join(texts)}
        items = [json.loads(t) for t in texts]
        return items if tool == "agy_sessions" else items[0]


@contextlib.asynccontextmanager
async def bridge(env: dict[str, str]) -> AsyncIterator[Bridge]:
    """One agy-bridge server process, driven over stdio like Claude Code does."""
    params = StdioServerParameters(command=sys.executable, args=["-m", "agy_bridge"], env=env)
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        yield Bridge(s)


def fake_argv(env: dict[str, str]) -> list[list[str]]:
    """Every argv the fake agy was started with in stream-json mode, oldest first."""
    log = Path(env["FAKE_AGY_STATE"]) / "argv.ndjson"
    if not log.exists():
        return []
    return [json.loads(line)["argv"] for line in log.read_text().splitlines()]
