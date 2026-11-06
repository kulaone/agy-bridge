"""Live checks against real AGY, for what the offline fake can't show.

Usage: uv run python scripts/live_checks.py [model] [switch_model] [switch_effort]

Needs `agy` installed and logged in, and the code-reviewer agent installed. Creates its
own throwaway git repo and bridge state folder (your sessions are not touched) and
checks, against real AGY:

  1. two reviews of the same project at once, one bridge, with an edit made mid-turn
  2. switching model and effort partway through a review, keeping the conversation
  3. a blocked action: AGY is asked to write outside its scratch folder

Each check prints PASS/FAIL. Takes 5-15 minutes. Defaults: gemini-3.8-flash-low, then
gemini-3.8-flash with effort medium.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent
WAIT = 900
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""),
          flush=True)


def make_repo(base: Path) -> Path:
    repo = base / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                        "-c", "commit.gpgsign=false", *args], cwd=repo, check=True,
                       capture_output=True)

    git("init", "-q", "-b", "main")
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    (repo / "stats.py").write_text(
        "def mean(xs):\n    return sum(xs) / len(xs)\n\n\n"
        "def median(xs):\n    xs = sorted(xs)\n    return xs[len(xs) // 2]\n")
    (repo / "test_stats.py").write_text(
        "from stats import mean, median\n\n\n"
        "def test_mean():\n    assert mean([1, 2, 3]) == 2\n\n\n"
        "def test_median():\n    assert median([3, 1, 2]) == 2\n")
    git("add", ".")
    git("commit", "-q", "-m", "init")
    with open(repo / "stats.py", "a") as f:
        f.write("\n\ndef mode(xs):\n    return max(xs, key=xs.count)\n")
    return repo


class Bridge:
    def __init__(self, s: ClientSession):
        self.s = s

    async def call(self, tool: str, **args):
        res = await self.s.call_tool(tool, args)
        texts = [getattr(c, "text", "") for c in res.content]
        if res.is_error:
            return {"error": "".join(texts)}
        # A list result arrives as one text block per item.
        items = [json.loads(t) for t in texts]
        return items[0] if len(items) == 1 and tool != "agy_sessions" else items


def brief(out: dict) -> str:
    review = out.get("review") or {}
    return (f"status={out.get('status')} verdict={review.get('verdict')} "
            f"{out.get('duration_seconds')}s notes={list((out.get('notes') or {}).keys())}"
            + (f" error={out['error']}" if out.get("error") else ""))


async def two_at_once(b: Bridge, repo: Path, model: str) -> None:
    print("\n1. Two reviews of the same project at once", flush=True)
    msg = ("Review my uncommitted change to stats.py (a new mode() function). "
           "Run the tests with `python3 -m pytest -q`.")
    a = await b.call("agy_start", agent="code-reviewer", cwd=str(repo), message=msg,
                     model=model, wait_seconds=1)
    c = await b.call("agy_start", agent="code-reviewer", cwd=str(repo), message=msg,
                     model=model, wait_seconds=1)
    check("both started", a.get("status") == "RUNNING" and c.get("status") == "RUNNING",
          f"{a.get('status')}, {c.get('status')} {a.get('error', '')}{c.get('error', '')}")
    if "session_id" not in a or "session_id" not in c:
        return
    await asyncio.sleep(5)
    readme = repo / "README.md"
    readme.write_text("A file Claude added while both reviews were running.\n")
    ra, rc = await asyncio.gather(
        b.call("agy_wait", session_id=a["session_id"], wait_seconds=WAIT),
        b.call("agy_wait", session_id=c["session_id"], wait_seconds=WAIT))
    print(f"     A: {brief(ra)}\n     B: {brief(rc)}", flush=True)
    check("both finished with a review",
          all(r.get("status") == "SUCCESS" and "review" in r for r in (ra, rc)))
    check("both report the mid-turn edit", all(
        "README.md" in (r.get("notes", {}).get("tree_changed", {}).get("files", {})
                        .get("created", [])) for r in (ra, rc)))
    check("each names the other review", (
        c["session_id"] in ra.get("notes", {}).get("other_reviews_running", {})
        .get("sessions", [])
        and a["session_id"] in rc.get("notes", {}).get("other_reviews_running", {})
        .get("sessions", [])))
    check("separate AGY conversations", ra.get("conversation_id") != rc.get("conversation_id"))
    readme.unlink()
    for sid in (a["session_id"], c["session_id"]):
        await b.call("agy_end", session_id=sid)


async def switch_model(b: Bridge, repo: Path, model: str, model2: str, effort2: str) -> None:
    print(f"\n2. Switching from {model} to {model2} (effort {effort2}) mid-review", flush=True)
    first = await b.call("agy_start", agent="code-reviewer", cwd=str(repo), model=model,
                         wait_seconds=WAIT,
                         message="Review my uncommitted change to stats.py. Don't run tests.")
    print(f"     turn 1: {brief(first)}", flush=True)
    check("first turn", first.get("status") == "SUCCESS", first.get("error", ""))
    if "session_id" not in first:
        return
    second = await b.call(
        "agy_say", session_id=first["session_id"], model=model2, effort=effort2,
        wait_seconds=WAIT,
        message="Memory check, no new review needed. In `summary`, name the function "
                "added in the change you just reviewed, and return no findings.")
    print(f"     turn 2: {brief(second)}", flush=True)
    summary = (second.get("review") or {}).get("summary", "")
    check("second turn on the new model", second.get("status") == "SUCCESS",
          second.get("error", ""))
    check("same conversation", second.get("conversation_id") == first.get("conversation_id"))
    check("remembers the earlier turn", "mode" in summary, summary[:120])
    rows = await b.call("agy_sessions", cwd=str(repo))
    row = next((r for r in rows if r["session_id"] == first["session_id"]), {}) \
        if isinstance(rows, list) else {}
    check("registry records the new model", (row.get("model"), row.get("effort")) ==
          (model2, effort2), f"{row.get('model')}, {row.get('effort')}")
    await b.call("agy_end", session_id=first["session_id"])


async def blocked_action(b: Bridge, repo: Path, base: Path, model: str) -> None:
    print("\n3. A blocked action", flush=True)
    target = base / "outside-scratch.txt"
    out = await b.call(
        "agy_start", agent="code-reviewer", cwd=str(repo), model=model, wait_seconds=WAIT,
        message=("This is a test of the bridge's permission handling, not a review. "
                 f"Use the write_to_file tool (not a shell command) to create {target} "
                 "containing the word hello. If the tool is denied, say so in `summary`, "
                 "return verdict approve and no findings."))
    print(f"     {brief(out)}", flush=True)
    notes = out.get("notes", {})
    check("turn completes", out.get("status") == "SUCCESS", out.get("error", ""))
    check("file was not written", not target.exists())
    check("denial reported", "denied_actions" in notes,
          json.dumps(notes.get("denied_actions"))[:120])
    if "denied_actions" in notes:
        check("follow-up produced a review", "auto_followup" in notes and "review" in out,
              (out.get("review") or {}).get("summary", "")[:120])
    if "session_id" in out:
        await b.call("agy_end", session_id=out["session_id"])


async def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "gemini-3.8-flash-low"
    model2 = sys.argv[2] if len(sys.argv) > 2 else "gemini-3.8-flash"
    effort2 = sys.argv[3] if len(sys.argv) > 3 else "medium"
    base = Path(tempfile.mkdtemp(prefix="agy-live-"))
    repo = make_repo(base)
    env = {**os.environ, "AGY_BRIDGE_HOME": str(base / "state"), "AGY_BRIDGE_LOG": "1"}
    print(f"repo {repo}\nstate {base / 'state'}", flush=True)
    params = StdioServerParameters(command=sys.executable, args=["-m", "agy_bridge"], env=env)
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        b = Bridge(s)
        await two_at_once(b, repo, model)
        await switch_model(b, repo, model, model2, effort2)
        await blocked_action(b, repo, base, model)
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed"
          + (f"; failed: {failed}" if failed else "") + f"\nlogs: {base / 'state' / 'logs'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
