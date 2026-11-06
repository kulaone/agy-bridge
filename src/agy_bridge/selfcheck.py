"""Tool-drift self-check and cached `agy` metadata.

AGY hangs a subagent whose `tools:` list names a tool that doesn't exist, so
before starting a session we compare the agent file's list with AGY's real
tools. The real list costs a model call, so it is cached on disk per
`agy --version`. `agy models` is cached the same way, with a TTL.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

from . import paths

MODELS_TTL = 24 * 3600
# AGY versions agy-bridge has been run against. Others usually work, but AGY's CLI,
# tool names and event format are young and change between releases.
TESTED_AGY_VERSIONS = ("1.5.1", "1.5.2")


def _load_cache() -> dict[str, Any]:
    try:
        return json.loads(paths.CACHE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict[str, Any]) -> None:
    paths.ensure_dirs()
    fd, tmp = tempfile.mkstemp(dir=paths.STATE_DIR, prefix=".cache.", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, paths.CACHE_FILE)


async def _run(*args: str, timeout: float = 120, cwd: str | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        paths.agy_binary(), *args, cwd=cwd,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def agy_version() -> str:
    _, out, _ = await _run("--version", timeout=30)
    return out.strip()


def version_warning(version: str) -> str | None:
    if version in TESTED_AGY_VERSIONS:
        return None
    return (f"AGY {version} has not been tested with agy-bridge (tested: "
            f"{', '.join(TESTED_AGY_VERSIONS)}). If reviews misbehave, check for an "
            "agy-bridge update.")


async def real_tools(version: str | None = None) -> list[str]:
    version = version or await agy_version()
    cache = _load_cache()
    entry = cache.get("tools")
    if entry and entry.get("version") == version:
        return entry["tools"]

    paths.ensure_dirs()  # AGY runs in the state folder
    _, out, err = await _run("-p", "Reply with the word ok", "--output-format", "stream-json",
                             "--print-timeout", "120s", timeout=180,
                             cwd=str(paths.STATE_DIR))
    for line in out.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") == "init":
            tools = event["init"]["tools"]
            cache["tools"] = {"version": version, "tools": tools, "at": time.time()}
            _save_cache(cache)
            return tools
    raise RuntimeError(f"could not read AGY's tool list (no init event). stderr: {err[-500:]}")


async def models(refresh: bool = False) -> list[dict[str, str]]:
    cache = _load_cache()
    entry = cache.get("models")
    if entry and not refresh and time.time() - entry.get("at", 0) < MODELS_TTL:
        return entry["models"]
    _, out, _ = await _run("models", timeout=60)
    result = []
    for line in out.splitlines():
        if "\t" in line:
            slug, label = line.split("\t", 1)
            result.append({"slug": slug.strip(), "label": label.strip()})
    if result:
        cache["models"] = {"models": result, "at": time.time()}
        _save_cache(cache)
    return result


async def agents() -> list[str]:
    _, out, _ = await _run("agents", timeout=60)
    return [line.strip() for line in out.splitlines() if line.strip()]


def find_agent_file(name: str, cwd: str) -> Path | None:
    """Nearest wins: <dir>/.agents/agents from cwd upwards, then the global folder."""
    candidates = []
    for d in [Path(cwd).resolve(), *Path(cwd).resolve().parents]:
        candidates.append(d / ".agents" / "agents")
    candidates.append(paths.GLOBAL_AGENTS_DIR)
    for base in candidates:
        for f in (base / f"{name}.md", base / name / "agent.md"):
            if f.is_file():
                return f
    return None


def agent_tools(agent_file: Path) -> list[str] | None:
    text = agent_file.read_text()
    if not text.startswith("---"):
        return None
    try:
        front = yaml.safe_load(text.split("---", 2)[1]) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"{agent_file}: invalid YAML frontmatter: {e}") from e
    if not isinstance(front, dict):
        raise ValueError(f"{agent_file}: the frontmatter must be a YAML mapping")
    tools = front.get("tools")
    if tools is None:
        return None
    if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
        raise ValueError(f"{agent_file}: `tools:` must be a list of tool names")
    return tools


async def check_agent(name: str, cwd: str) -> dict[str, Any]:
    """Raise ValueError if the agent lists tools AGY doesn't have."""
    version = await agy_version()
    info: dict[str, Any] = {"agy_version": version, "version_warning": version_warning(version)}
    agent_file = find_agent_file(name, cwd)
    if agent_file is None:
        return {**info, "agent_file": None, "checked": False}
    listed = agent_tools(agent_file)
    if not listed:
        return {**info, "agent_file": str(agent_file), "checked": False}
    available = set(await real_tools(version))
    missing = [t for t in listed if t not in available]
    if missing:
        raise ValueError(
            f"Agent '{name}' ({agent_file}) lists tools AGY {version} doesn't have: "
            f"{missing}. Fix the agent's tools: list (a wrong name can hang the agent).")
    if "finish" not in listed:
        raise ValueError(f"Agent '{name}' ({agent_file}) must list the `finish` tool, "
                         "or AGY returns no structured_output.")
    return {**info, "agent_file": str(agent_file), "checked": True}
