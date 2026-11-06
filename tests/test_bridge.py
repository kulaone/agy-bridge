"""End-to-end tests: the real server over stdio, as Claude Code drives it, with the fake
agy standing in for AGY."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from conftest import bridge, fake_argv


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 120))


def start(b, repo: Path, message: str = "Review my change.", **kw):
    return b.call("agy_start", agent="code-reviewer", cwd=str(repo), message=message, **kw)


def test_review_roundtrip(installed: dict, repo: Path) -> None:
    async def go():
        async with bridge(installed) as b:
            listing = await b.call("agy_list_agents")
            assert "code-reviewer" in listing["agents"]
            assert listing["agy_version"] == "1.5.2" and "version_warning" not in listing
            first = await start(b, repo)
            assert first["status"] == "SUCCESS", first
            assert first["review"]["verdict"] == "approve"
            assert "message 1 of conversation" in first["review"]["summary"]
            assert "notes" not in first  # no changes, no denials
            second = await b.call("agy_say", session_id=first["session_id"], message="Thanks.")
            assert "message 2 of" in second["review"]["summary"]
            rows = await b.call("agy_sessions", cwd=str(repo))
            return first, rows

    first, rows = run(go())
    assert len(fake_argv(installed)) == 1  # one AGY process served both turns
    argv = fake_argv(installed)[0]
    assert argv[argv.index("--agent") + 1] == "code-reviewer"
    assert "--dangerously-skip-permissions" not in argv
    assert "--disable-slash-commands" in argv


def test_first_message_names_project_and_scratch(installed: dict, repo: Path) -> None:
    async def go():
        async with bridge(installed) as b:
            return await start(b, repo)

    out = run(go())
    history = json.loads((Path(installed["FAKE_AGY_STATE"]) /
                          f"{out['conversation_id']}.json").read_text())
    assert f"Project directory: {repo}" in history[0]
    assert "Do not modify files in the project directory." in history[0]


def test_long_turn_returns_running_then_wait_collects(installed: dict, repo: Path) -> None:
    async def go():
        async with bridge(installed) as b:
            first = await start(b, repo, "Review. [[sleep 4]]", wait_seconds=1)
            assert first["status"] == "RUNNING", first
            sid = first["session_id"]
            status = await b.call("agy_status", session_id=sid)
            assert status["state"] == "working"
            assert status["current_turn"]["last_steps"] == ["read_file stats.py"]
            busy = await b.call("agy_say", session_id=sid, message="more")
            assert "still working" in busy["error"]
            done = await b.call("agy_wait", session_id=sid, wait_seconds=30)
            assert done["status"] == "SUCCESS" and done["looked_at"] == ["read_file stats.py"]
            assert (await b.call("agy_status", session_id=sid))["state"] == "idle"

    run(go())


def test_denied_action_gets_one_followup(installed: dict, repo: Path) -> None:
    async def go():
        async with bridge(installed) as b:
            return await start(b, repo, "Review. [[deny]]")

    out = run(go())
    assert out["status"] == "SUCCESS" and out["review"]["verdict"] == "approve"
    assert out["notes"]["denied_actions"] == [{"action": "command", "display_name": "RunCommand"}]
    assert "auto_followup" in out["notes"]


def test_every_denial_gets_its_followup(installed: dict, repo: Path) -> None:
    async def go():
        async with bridge(installed) as b:
            first = await start(b, repo, "Review. [[deny]]")
            again = await b.call("agy_say", session_id=first["session_id"],
                                 message="Check again. [[deny]]")
            return first, again

    first, again = run(go())
    for out in (first, again):  # AGY repeats an identical entry; it is still new
        assert out["review"]["verdict"] == "approve", out
        assert len(out["notes"]["denied_actions"]) == 1 and "auto_followup" in out["notes"]


def test_crash_mid_turn_is_reported(installed: dict, repo: Path) -> None:
    async def go():
        async with bridge(installed) as b:
            out = await start(b, repo, "Review. [[crash]]")
            # The next message restarts AGY on the same conversation.
            again = await b.call("agy_say", session_id=out["session_id"], message="Again.")
            return out, again

    out, again = run(go())
    assert out["status"] == "ERROR" and "exited with code 3" in out["error"]
    assert again["status"] == "SUCCESS"
    assert "--conversation" in fake_argv(installed)[1]


def test_text_answer_is_parsed(installed: dict, repo: Path) -> None:
    async def go():
        async with bridge(installed) as b:
            return await start(b, repo, "Review. [[text]]")

    out = run(go())
    assert out["review"]["verdict"] == "approve" and out["review_parsed_from_text"]


def test_agy_error_and_model_hint(installed: dict, repo: Path) -> None:
    async def go():
        async with bridge(installed) as b:
            err = await start(b, repo, "Review. [[error quota exceeded]]")
            bad = await start(b, repo, model="bad-model")
            return err, bad

    err, bad = run(go())
    assert err["status"] == "ERROR" and err["error"] == "quota exceeded"
    assert "unknown model" in bad["error"]
    assert "gemini-fake-pro" in bad["available_models"]


def test_project_edit_is_reported_with_backup(installed: dict, repo: Path) -> None:
    async def go():
        async with bridge(installed) as b:
            return await start(b, repo, "Review. [[write stats.py]]")

    out = run(go())
    notes = out["notes"]
    assert notes["tree_changed"]["files"] == {"modified": ["stats.py"]}
    backup_dir = Path(notes["backup"]["dir"])
    assert (backup_dir / "tracked.patch").exists()
    assert "git apply" in notes["backup"]["restore"]


def test_model_change_restarts_on_same_conversation(installed: dict, repo: Path) -> None:
    async def go():
        async with bridge(installed) as b:
            first = await start(b, repo, model="gemini-fake-pro")
            sid = first["session_id"]
            same = await b.call("agy_say", session_id=sid, message="Keep model.")
            changed = await b.call("agy_say", session_id=sid, message="Switch.",
                                   model="gemini-fake-flash-low", effort="high")
            return first, same, changed

    first, same, changed = run(go())
    assert "model=gemini-fake-pro" in same["review"]["summary"]
    assert "model=gemini-fake-flash-low; effort=high" in changed["review"]["summary"]
    assert "message 3 of" in changed["review"]["summary"]
    argvs = fake_argv(installed)
    assert len(argvs) == 2
    assert argvs[1][argvs[1].index("--conversation") + 1] == first["conversation_id"]


def test_new_model_starts_without_the_old_effort(installed: dict, repo: Path) -> None:
    async def go():
        async with bridge(installed) as b:
            first = await start(b, repo, model="gemini-fake-pro", effort="high")
            sid = first["session_id"]
            same = await b.call("agy_say", session_id=sid, message="Again.")
            other = await b.call("agy_say", session_id=sid, message="Switch.",
                                 model="gemini-fake-flash-low")
            return same, other

    same, other = run(go())
    assert "model=gemini-fake-pro; effort=high" in same["review"]["summary"]
    assert "model=gemini-fake-flash-low; effort=None" in other["review"]["summary"]


def test_resume_from_a_new_bridge(installed: dict, repo: Path) -> None:
    async def first_bridge():
        async with bridge(installed) as b:
            out = await start(b, repo)
            await b.call("agy_end", session_id=out["session_id"])
            return out

    async def second_bridge(sid):
        async with bridge(installed) as b:
            rows = await b.call("agy_sessions", cwd=str(repo))
            again = await b.call("agy_say", session_id=sid, message="Where were we?")
            return rows, again

    out = run(first_bridge())
    rows, again = run(second_bridge(out["session_id"]))
    assert [r["session_id"] for r in rows] == [out["session_id"]]
    assert rows[0]["process"] == "stopped" and rows[0]["turns"] == 1
    assert again["status"] == "SUCCESS" and "message 2 of" in again["review"]["summary"]
    assert again["conversation_id"] == out["conversation_id"]


def test_second_bridge_cannot_drive_a_busy_session(installed: dict, repo: Path) -> None:
    async def go():
        async with bridge(installed) as a, bridge(installed) as b:
            first = await start(a, repo, "Review. [[sleep 3]]", wait_seconds=1)
            sid = first["session_id"]
            refused = await b.call("agy_say", session_id=sid, message="mine now")
            status = await b.call("agy_status", session_id=sid)
            end = await b.call("agy_end", session_id=sid, forget=True)
            done = await a.call("agy_wait", session_id=sid, wait_seconds=30)
            await a.call("agy_end", session_id=sid)
            taken = await b.call("agy_say", session_id=sid, message="mine now")
            return refused, status, end, done, taken

    refused, status, end, done, taken = run(go())
    assert "in use by another agy-bridge process" in refused["error"]
    assert "another agy-bridge" in status["process"]
    assert "running in another agy-bridge" in end["error"]
    assert done["status"] == "SUCCESS"
    assert taken["status"] == "SUCCESS"


def test_overlapping_reviews_are_flagged(installed: dict, repo: Path) -> None:
    async def go():
        async with bridge(installed) as b:
            slow = await start(b, repo, "Review. [[sleep 3]]", wait_seconds=0.5)
            fast = await start(b, repo, "Review. [[write stats.py]]")
            slow_done = await b.call("agy_wait", session_id=slow["session_id"], wait_seconds=30)
            alone = await start(b, repo, "Review. [[write stats.py]]")
            return slow, fast, slow_done, alone

    slow, fast, slow_done, alone = run(go())
    assert fast["notes"]["other_reviews_running"]["sessions"] == [slow["session_id"]]
    # The slow turn saw the fast review's edit, and is told another review was running.
    assert slow_done["notes"]["tree_changed"]["files"] == {"modified": ["stats.py"]}
    assert fast["session_id"] in slow_done["notes"]["other_reviews_running"]["sessions"]
    # Overlap only counts while turns actually overlap.
    assert "other_reviews_running" not in alone["notes"]


def test_untested_agy_version_is_noted(installed: dict, repo: Path) -> None:
    env = {**installed, "FAKE_AGY_VERSION": "9.9.9"}

    async def go():
        async with bridge(env) as b:
            return await b.call("agy_list_agents"), await start(b, repo)

    listing, out = run(go())
    assert "9.9.9 has not been tested" in listing["version_warning"]
    assert "9.9.9 has not been tested" in out["notes"]["agy_version"]


def test_errors_reach_claude_with_their_message(installed: dict, repo: Path) -> None:
    async def go():
        async with bridge(installed) as b:
            return (await b.call("agy_say", session_id="nope", message="hi"),
                    await start(b, repo / "missing"),
                    await b.call("agy_resume"))

    unknown, bad_cwd, no_args = run(go())
    assert "unknown session_id 'nope'" in unknown["error"]
    assert "cwd is not a directory" in bad_cwd["error"]
    assert "pass session_id or conversation_id" in no_args["error"]


def test_agent_with_unknown_tool_is_refused(installed: dict, repo: Path) -> None:
    agent = Path(installed["HOME"]) / ".gemini/config/agents/code-reviewer.md"
    agent.write_text(agent.read_text().replace("finish]", "finish, edit_file]"))

    async def go():
        async with bridge(installed) as b:
            return await start(b, repo)

    out = run(go())
    assert "doesn't have: ['edit_file']" in out["error"]


def test_logging_is_opt_in_and_forget_cleans_up(installed: dict, repo: Path) -> None:
    state = Path(installed["AGY_BRIDGE_HOME"])

    async def session(env, forget):
        async with bridge(env) as b:
            out = await start(b, repo, "Review. [[write stats.py]]")
            sid = out["session_id"]
            existed = {name: (state / name / sid).exists() for name in ("scratch", "backup")}
            existed["log"] = (state / "logs" / f"{sid}.ndjson").exists()
            if forget:
                await b.call("agy_end", session_id=sid, forget=True)
            return sid, existed

    sid, existed = run(session(installed, forget=False))
    assert existed == {"scratch": True, "backup": True, "log": False}
    assert not (state / "logs").exists()

    sid, existed = run(session({**installed, "AGY_BRIDGE_LOG": "1"}, forget=True))
    assert existed == {"scratch": True, "backup": True, "log": True}
    assert not (state / "scratch" / sid).exists()
    assert not (state / "backup" / sid).exists()
    assert not (state / "logs" / f"{sid}.ndjson").exists()
    assert sid not in json.loads((state / "sessions.json").read_text())
