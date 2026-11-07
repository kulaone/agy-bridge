"""MCP server exposing AGY (Google Antigravity CLI) reviewer agents to Claude Code."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import os
import shutil
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from importlib import resources
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import backup, paths, registry, selfcheck
from .session import Session, Turn, build_turn_payload, new_session_id, scratch_dir

DEFAULT_WAIT = 600
PROGRESS_POLL = 2.0
IDLE_DAYS = 30  # after this, a session's scratch and backups are removed (it stays resumable)

def _load_schema(name: str) -> dict[str, Any]:
    return json.loads(resources.files("agy_bridge").joinpath(f"data/{name}.schema.json")
                      .read_text())


# The answer formats Claude can ask for; `schema` replaces them with a custom one.
FORMATS = {"review": _load_schema("review"), "brainstorm": _load_schema("brainstorm")}
REVIEW_SCHEMA = FORMATS["review"]


def _answer_schema(format: str | None, schema: dict[str, Any] | None) -> dict[str, Any] | None:
    if schema is not None:
        return schema
    if format is None:
        return None
    if format not in FORMATS:
        raise ValueError(f"unknown format {format!r}: use one of {sorted(FORMATS)}")
    return FORMATS[format]

SESSIONS: dict[str, Session] = {}


@contextlib.asynccontextmanager
async def lifespan(_server: MCPServer) -> AsyncIterator[None]:
    paths.ensure_dirs()
    _prune_orphans()
    _prune_idle_sessions()
    try:
        yield
    finally:
        await asyncio.gather(*(s.stop_process(grace=5) for s in SESSIONS.values()),
                             return_exceptions=True)


mcp = MCPServer(
    "agy",
    instructions=(
        "Run Google Antigravity (AGY) reviewer agents and converse with them. Start with "
        "agy_start, continue with agy_say, and use agy_wait if a turn is still running. "
        "Reviews take minutes. AGY reads the project and may run tests, but must not edit "
        "files under review; notes.tree_changed reports any change it made."),
    lifespan=lifespan,
)


def _prune_orphans() -> None:
    """Remove scratch folders and backups of sessions that are no longer in the registry."""
    known = set(registry.list_all())
    for d in paths.SCRATCH_DIR.glob("*"):
        if d.is_dir() and d.name not in known:
            shutil.rmtree(d, ignore_errors=True)
    backup.remove_orphans(known)


def _prune_idle_sessions() -> None:
    """Free the disk space of sessions unused for IDLE_DAYS: their scratch folder and
    backups go, their record stays, so they can still be resumed."""
    cutoff = datetime.now(UTC) - timedelta(days=IDLE_DAYS)
    for sid, rec in registry.list_all().items():
        try:
            last_used = datetime.fromisoformat(rec.get("last_used") or "")
        except ValueError:
            continue
        if last_used < cutoff and not _owned_elsewhere(rec):
            shutil.rmtree(scratch_dir(sid), ignore_errors=True)
            backup.remove(sid)


def tool(fn):
    """Register an MCP tool whose expected failures reach Claude with their message.

    MCPServer replaces the message of any exception other than ToolError with a bare
    "Error executing tool", so the errors we raise on purpose are converted.
    """
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except (ValueError, RuntimeError, KeyError, OSError) as e:
            raise ToolError(str(e)) from e
    return mcp.tool()(wrapper)


def _owned_elsewhere(rec: dict[str, Any]) -> int | None:
    """PID of another live bridge process that owns this session, if any."""
    owner = rec.get("owner_pid")
    if owner and owner != os.getpid() and registry.is_live_bridge(owner):
        return owner
    return None


def _session(session_id: str) -> Session:
    if session_id in SESSIONS:
        return SESSIONS[session_id]
    rec = registry.get(session_id)
    if rec is None:
        raise ValueError(f"unknown session_id {session_id!r}; see agy_sessions")
    s = Session(session_id, rec)
    SESSIONS[session_id] = s
    return s


async def _wait_turn(session: Session, turn: Turn, wait_seconds: float,
                     ctx: Context | None) -> dict[str, Any]:
    deadline = time.time() + max(1.0, wait_seconds)
    reported = -1
    while not turn.done.is_set():
        remaining = deadline - time.time()
        if remaining <= 0:
            return {
                "session_id": session.id,
                "turn": turn.number,
                "status": "RUNNING",
                "elapsed_seconds": round(time.time() - turn.started, 1),
                "last_steps": turn.steps[-8:],
                "hint": "AGY is still working. Call agy_wait to keep waiting or agy_status "
                        "to check progress.",
            }
        if ctx is not None and len(turn.steps) != reported:
            reported = len(turn.steps)
            msg = turn.steps[-1] if turn.steps else "AGY is thinking…"
            with contextlib.suppress(Exception):
                await ctx.report_progress(reported, None, f"turn {turn.number}: {msg}")
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(turn.done.wait(), min(PROGRESS_POLL, remaining))
    payload = build_turn_payload(session, turn)
    if payload["status"] != "SUCCESS" and "model" in (payload.get("error") or "").lower():
        with contextlib.suppress(Exception):
            payload["available_models"] = [m["slug"] for m in await selfcheck.models()]
        # Don't keep a model AGY rejected as the session's default for the next message.
        model, effort = turn.previous_settings
        if (model, effort) != (session.record.get("model"), session.record.get("effort")):
            session.record.update(model=model, effort=effort)
            registry.update(session.id, model=model, effort=effort)
            payload["model_reverted_to"] = {"model": model, "effort": effort}
    if isinstance(payload.get("review"), dict):
        registry.update(session.id, last_verdict=payload["review"].get("verdict"))
    return payload


def _first_message(message: str, session_id: str, cwd: str) -> str:
    return (f"{message}\n\n---\nProject directory: {cwd}\n"
            f"Your scratch directory for experiments: {scratch_dir(session_id)}\n"
            "Do not modify files in the project directory.")


@tool
async def agy_list_agents(refresh_models: bool = False) -> dict[str, Any]:
    """List AGY agents available to agy_start and the model slugs AGY offers.

    Model slugs may carry an effort level (e.g. "-high"); pass either a full slug, or a base
    slug plus `effort`. Never assume a fixed list: always read it here.
    """
    agents, models, version = await asyncio.gather(
        selfcheck.agents(), selfcheck.models(refresh_models), selfcheck.agy_version())
    out = {"agents": agents, "models": models,
           "efforts": ["low", "medium", "high", "xhigh", "max"], "agy_version": version}
    if warning := selfcheck.version_warning(version):
        out["version_warning"] = warning
    return out


@tool
async def agy_start(agent: str, cwd: str, message: str, ctx: Context,
                    model: str | None = None, effort: str | None = None,
                    format: str = "review", schema: dict[str, Any] | None = None,
                    wait_seconds: float = DEFAULT_WAIT) -> dict[str, Any]:
    """Open a new AGY review session and send the first message.

    agent: an AGY agent, e.g. code-reviewer; agy_list_agents lists those installed.
    cwd: absolute path of the project to review (AGY runs there).
    message: what to review and why: diff or file/doc paths, intent, how to run tests.
    model / effort: optional; omit to use AGY's default. See agy_list_agents.
    format: the answer format. "review" (default): verdict, summary, findings,
      questions_for_claude. "brainstorm", for planning and ideas: verdict
      (needs_discussion | ready), summary, stage, techniques_used, reframed_problem,
      assumptions (with their source), options (idea, gains, costs), recommendation,
      next_step, questions_for_claude.
    schema: optional custom JSON schema for the answer, instead of a format.
    wait_seconds: how long to wait for the answer before returning status RUNNING
      (the turn keeps going; collect it with agy_wait).
    Returns the session_id, the review, and notes (denied actions, files AGY changed).
    """
    project = Path(cwd).expanduser().resolve()
    if not project.is_dir():
        raise ValueError(f"cwd is not a directory: {cwd}")
    answer_schema = _answer_schema(format or "review", schema)
    check = await selfcheck.check_agent(agent, str(project))

    session_id = new_session_id()
    record = {
        "agent": agent, "cwd": str(project), "model": model, "effort": effort,
        "schema": answer_schema, "format": "custom" if schema else format or "review",
        "conversation_id": None,
        "created": registry.now_iso(), "last_used": registry.now_iso(), "turns": 0,
        "agent_file": check.get("agent_file"),
    }
    registry.put(session_id, record)
    session = Session(session_id, record)
    SESSIONS[session_id] = session
    turn = await session.send(_first_message(message, session_id, str(project)), model, effort)
    payload = await _wait_turn(session, turn, wait_seconds, ctx)
    if check.get("version_warning"):
        payload.setdefault("notes", {})["agy_version"] = check["version_warning"]
    agent_file = check.get("agent_file")
    if agent_file and paths.GLOBAL_AGENTS_DIR not in Path(agent_file).parents:
        payload.setdefault("notes", {})["agent_file"] = (
            f"{agent_file}: AGY is using this local agent, not the global "
            f"'{agent}'. It defines how this review works; check it if you don't trust "
            "the project.")
    return payload


@tool
async def agy_say(session_id: str, message: str, ctx: Context,
                  model: str | None = None, effort: str | None = None,
                  format: str | None = None,
                  wait_seconds: float = DEFAULT_WAIT) -> dict[str, Any]:
    """Send the next message in an AGY session: fixes made (with the new diff), answers to
    AGY's questions, or arguments against a finding. Resumes the conversation automatically
    if its process has ended (e.g. in a later Claude session). model/effort default to the
    session's previous choice, except that a new model starts with no effort unless one is
    given. format ("review" or "brainstorm") switches the answer format, e.g. from
    brainstorming a plan to reviewing the result. Changing any of them restarts the
    process on the same conversation.
    """
    session = _session(session_id)
    new_schema = _answer_schema(format, None)
    if new_schema is not None and new_schema != session.record.get("schema"):
        session.record.update(schema=new_schema, format=format)
        registry.update(session.id, schema=new_schema, format=format)
    previous_model = session.record.get("model")
    if effort is None and (model is None or model == previous_model):
        effort = session.record.get("effort")  # a new model doesn't inherit the old effort
    model = model if model is not None else previous_model
    turn = await session.send(message, model, effort or None)
    return await _wait_turn(session, turn, wait_seconds, ctx)


@tool
async def agy_wait(session_id: str, ctx: Context,
                   wait_seconds: float = DEFAULT_WAIT) -> dict[str, Any]:
    """Keep waiting for a turn that agy_start/agy_say returned as RUNNING, and return its
    result when done. Returns the last result again if no turn is running."""
    session = _session(session_id)
    if session.turn is None:
        owner = _owned_elsewhere(session.record)
        if owner:
            raise ValueError(
                f"session {session_id} is running in another agy-bridge process (pid "
                f"{owner}); collect its result from the Claude Code window that owns it.")
        # Typically Claude Code (and with it this bridge) restarted while a turn ran.
        raise ValueError(
            f"session {session_id} has no turn in this agy-bridge process, so there is "
            "nothing to wait for. If a turn was running when Claude Code or the bridge "
            "restarted, its result was lost here, but AGY's conversation kept it: use "
            "agy_say to ask AGY to repeat its last answer.")
    return await _wait_turn(session, session.turn, wait_seconds, ctx)


@tool
async def agy_status(session_id: str) -> dict[str, Any]:
    """What an AGY session is doing right now: idle or working, current turn, elapsed time,
    and the last tool steps AGY took. Use it when the user asks for progress."""
    live = SESSIONS.get(session_id)
    if live and (live.alive or live.turn is not None):
        return live.status()
    rec = registry.get(session_id)
    if rec is None:
        raise ValueError(f"unknown session_id {session_id!r}")
    owner = _owned_elsewhere(rec)
    if owner:
        return {"session_id": session_id, "agent": rec["agent"],
                "process": f"running in another agy-bridge (pid {owner})",
                "state": "unknown here: ask in the Claude window that owns it",
                "turns": rec.get("turns", 0), "last_used": rec.get("last_used")}
    return {"session_id": session_id, "conversation_id": rec.get("conversation_id"),
            "agent": rec["agent"], "process": "stopped", "state": "idle",
            "turns": rec.get("turns", 0), "last_used": rec.get("last_used")}


@tool
async def agy_resume(session_id: str | None = None, conversation_id: str | None = None,
                     agent: str | None = None, cwd: str | None = None) -> dict[str, Any]:
    """Re-open a stored AGY session in a fresh process, by session_id or conversation_id.
    For a conversation the bridge has never seen, also pass agent and cwd.
    agy_say also resumes automatically, so this is only needed to warm a session up front."""
    if session_id is None and conversation_id is None:
        raise ValueError("pass session_id or conversation_id")
    if session_id is None:
        found = registry.find_by_conversation(conversation_id)  # type: ignore[arg-type]
        if found:
            session_id = found[0]
        else:
            if not (agent and cwd):
                raise ValueError("unknown conversation_id: pass agent and cwd to adopt it")
            project = Path(cwd).expanduser().resolve()
            if not project.is_dir():
                raise ValueError(f"cwd is not a directory: {cwd}")
            check = await selfcheck.check_agent(agent, str(project))
            session_id = new_session_id()
            registry.put(session_id, {
                "agent": agent, "cwd": str(project), "model": None,
                "effort": None, "schema": REVIEW_SCHEMA, "format": "review",
                "conversation_id": conversation_id,
                "created": registry.now_iso(), "last_used": registry.now_iso(), "turns": 0,
                "agent_file": check.get("agent_file")})
    session = _session(session_id)
    await session.ensure_process(session.record.get("model"), session.record.get("effort"))
    return session.status()


@tool
async def agy_sessions(cwd: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """List stored AGY sessions, most recently used first. Filter by project with cwd."""
    project = str(Path(cwd).expanduser().resolve()) if cwd else None
    rows = []
    for sid, rec in registry.list_all().items():
        if project and rec.get("cwd") != project:
            continue
        live = sid in SESSIONS and SESSIONS[sid].alive
        rows.append({"session_id": sid, "agent": rec.get("agent"), "cwd": rec.get("cwd"),
                     "model": rec.get("model"), "effort": rec.get("effort"),
                     "format": rec.get("format", "review"),
                     "turns": rec.get("turns", 0), "last_verdict": rec.get("last_verdict"),
                     "created": rec.get("created"), "last_used": rec.get("last_used"),
                     "conversation_id": rec.get("conversation_id"),
                     "process": "running" if live else "stopped"})
    rows.sort(key=lambda r: r.get("last_used") or "", reverse=True)
    return rows[:limit]


@tool
async def agy_end(session_id: str, forget: bool = False) -> dict[str, Any]:
    """Stop a session's AGY process. The session stays resumable unless forget=True, which
    also deletes it from the registry and removes its scratch, backup and log files."""
    rec = registry.get(session_id)
    owner = _owned_elsewhere(rec) if rec else None
    if owner:
        raise registry.SessionInUse(
            f"session {session_id} is running in another agy-bridge process (pid {owner}); "
            "end it from the Claude Code window that owns it.")
    session = SESSIONS.pop(session_id, None)
    if session:
        await session.stop_process()
    elif rec is None:
        raise ValueError(f"unknown session_id {session_id!r}")
    if forget:
        registry.remove(session_id)
        shutil.rmtree(scratch_dir(session_id), ignore_errors=True)
        backup.remove(session_id)
        (paths.LOG_DIR / f"{session_id}.ndjson").unlink(missing_ok=True)
    return {"session_id": session_id, "ended": True, "forgotten": forget}


def main() -> None:
    mcp.run("stdio")
