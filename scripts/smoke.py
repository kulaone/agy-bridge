"""End-to-end smoke test: drive agy-bridge over stdio like Claude Code would.

Usage: uv run python scripts/smoke.py <git repo with an uncommitted change> [model] [agent]

Needs a working, logged-in `agy`. The repo must contain stats.py with an uncommitted
change (the default prompt reviews an added mode() function). agent defaults to
code-reviewer, model to AGY's default.

Exercises agy_start (with a short wait so it returns RUNNING), agy_status, agy_wait,
agy_say while a tracked file is edited by hand (must show up in notes.tree_changed),
then restarts the bridge and checks that agy_sessions + agy_say resume the conversation.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent
SERVER = StdioServerParameters(command=str(ROOT / ".venv" / "bin" / "agy-bridge"))


def show(label: str, result) -> dict:
    text = "".join(getattr(c, "text", "") for c in result.content)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {"raw": text}
    print(f"\n=== {label}{' (ERROR)' if result.is_error else ''}")
    print(json.dumps(data, indent=2)[:3000])
    return data


async def progress(p, total, message):
    print(f"  progress {p}: {message}")


async def call(s: ClientSession, name: str, args: dict, label: str | None = None) -> dict:
    res = await s.call_tool(name, args, progress_callback=progress)
    return show(label or name, res)


async def phase1(repo: str, model: str | None, agent: str) -> str:
    async with stdio_client(SERVER) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        tools = await s.list_tools()
        print("tools:", [t.name for t in tools.tools])
        await call(s, "agy_list_agents", {})

        start = await call(s, "agy_start", {
            "agent": agent, "cwd": repo, "wait_seconds": 15, **({"model": model} if model else {}),
            "message": "Review my uncommitted change. Intent: add mode() to stats.py. "
                       "Tests: python3 -m pytest -q"})
        sid = start["session_id"]
        assert start["status"] == "RUNNING", "expected a short wait to return RUNNING"
        await call(s, "agy_status", {"session_id": sid})
        first = await call(s, "agy_wait", {"session_id": sid, "wait_seconds": 900})
        assert first["status"] == "SUCCESS" and "review" in first, "first turn failed"

        # Edit a tracked file by hand mid-turn: the bridge must report it.
        say = asyncio.create_task(s.call_tool("agy_say", {
            "session_id": sid, "wait_seconds": 900,
            "message": "I disagree with your performance finding: inputs are always under "
                       "100 items. Do you still consider it a problem? Keep the rest."},
            progress_callback=progress))
        await asyncio.sleep(8)
        stats = Path(repo, "stats.py")
        stats.write_text(stats.read_text() + "\n# touched by smoke test\n")
        second = show("agy_say (with manual edit)", await say)
        changed = second.get("notes", {}).get("tree_changed", {})
        assert "stats.py" in changed.get("files", {}).get("modified", []), \
            "manual edit not reported in notes.tree_changed"
        print("\nOK: manual edit reported:", changed)
        await call(s, "agy_end", {"session_id": sid})
        return sid


async def phase2(sid: str, repo: str) -> None:
    async with stdio_client(SERVER) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        rows = await call(s, "agy_sessions", {"cwd": repo})
        assert any(row["session_id"] == sid for row in rows if isinstance(row, dict)) or \
            sid in json.dumps(rows), "session not listed after restart"
        third = await call(s, "agy_say", {
            "session_id": sid, "wait_seconds": 900,
            "message": "New bridge process. In one sentence in `summary`: which function "
                       "were we reviewing and what was my argument about performance?"})
        assert third["status"] == "SUCCESS", "resumed turn failed"
        await call(s, "agy_end", {"session_id": sid, "forget": True})


async def main() -> None:
    repo = str(Path(sys.argv[1]).resolve())
    model = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
    agent = sys.argv[3] if len(sys.argv) > 3 else "code-reviewer"
    sid = await phase1(repo, model, agent)
    await phase2(sid, repo)
    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())
