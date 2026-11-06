"""One AGY conversation backed by a long-running `agy` stream-json process.

A background reader task consumes AGY's NDJSON output for the life of the
process: it records tool steps for progress/status, resolves the current turn
when a `result` event arrives, and logs every line if AGY_BRIDGE_LOG is set. Callers send a message
and then wait on the turn with a timeout; a turn that outlives the wait keeps
running and can be collected later.
"""

from __future__ import annotations

import asyncio
import collections
import json
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import backup, paths, registry, tree

STREAM_LIMIT = 32 * 1024 * 1024
DENIED_FOLLOWUP = ("These actions were denied by policy in your last step: {actions}. "
                   "Continue the review without them and give your answer.")


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def scratch_dir(session_id: str) -> Path:
    return paths.SCRATCH_DIR / session_id


def reviewer_settings(session_id: str) -> str:
    """Per-session AGY settings: any command, file-writing tools only in scratch."""
    scratch = scratch_dir(session_id)
    return json.dumps({"permissions": {"allow": ["command(regex:.*)", f"write_file({scratch}/)"]}})


def _step_label(step: dict[str, Any], cwd: str) -> str:
    params = (step.get("tool_info") or {}).get("parameters") or {}
    target = (params.get("CommandLine") or params.get("Path") or params.get("AbsolutePath")
              or params.get("TargetFile")
              or params.get("DirectoryPath") or params.get("Query") or params.get("SearchPath")
              or params.get("Pattern") or params.get("Url") or "")
    target = " ".join(str(target).split()).replace(cwd.rstrip("/") + "/", "")
    if len(target) > 120:
        target = target[:117] + "…"
    name = step.get("tool_name") or step.get("step_type") or "step"
    return f"{name} {target}".strip()


def parse_json_response(text: str) -> Any | None:
    """Fallback when structured_output is missing: take the first JSON object in the text."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    start = text.find("{")
    if start >= 0:
        candidates.append(text[start:])
    decoder = json.JSONDecoder()
    for c in candidates:
        try:
            obj, _ = decoder.raw_decode(c.strip())
            return obj
        except json.JSONDecodeError:
            continue
    return None


@dataclass
class Turn:
    number: int
    message: str
    started: float = field(default_factory=time.time)
    steps: list[str] = field(default_factory=list)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    result: dict[str, Any] | None = None
    ended: float | None = None
    before: tree.Snapshot | None = None
    denied_new: list[dict] = field(default_factory=list)
    followups: int = 0
    collected: bool = False
    tree_changes: dict[str, Any] | None = None
    backup: dict[str, Any] | None = None
    backup_error: str | None = None
    overlapping: list[str] = field(default_factory=list)  # other reviews on this project
    previous_settings: tuple[str | None, str | None] = (None, None)  # model, effort before


class Session:
    def __init__(self, session_id: str, record: dict[str, Any]):
        self.id = session_id
        self.record = record
        self.proc: asyncio.subprocess.Process | None = None
        self.proc_args: tuple[str | None, str | None] = (None, None)  # (model, effort)
        self.turn: Turn | None = None
        self.recent = collections.deque(maxlen=20)
        self.stderr_tail = collections.deque(maxlen=50)
        self.denied_seen: list[dict] = []  # this process's denied_actions so far
        self._send_lock = asyncio.Lock()
        self._reader: asyncio.Task | None = None
        self._err_reader: asyncio.Task | None = None
        self.log_path = paths.LOG_DIR / f"{session_id}.ndjson"

    # ----- process lifecycle -------------------------------------------------

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    @property
    def busy(self) -> bool:
        return self.turn is not None and not self.turn.done.is_set()

    def _log(self, kind: str, payload: Any) -> None:
        if not paths.LOGGING:
            return
        with open(self.log_path, "a") as f:
            f.write(json.dumps({"t": time.time(), "kind": kind, "data": payload}) + "\n")

    async def start_process(self, model: str | None, effort: str | None) -> None:
        rec = self.record
        registry.claim(self.id, os.getpid())  # raises SessionInUse if another bridge has it
        scratch_dir(self.id).mkdir(parents=True, exist_ok=True)
        self.denied_seen = []  # AGY's list starts afresh with each process
        args = [paths.agy_binary(),
                "--input-format", "stream-json", "--output-format", "stream-json",
                "--agent", rec["agent"],
                "--json-schema", json.dumps(rec["schema"]),
                "--settings", reviewer_settings(self.id),
                "--disable-slash-commands"]
        if rec.get("conversation_id"):
            args += ["--conversation", rec["conversation_id"]]
        if model:
            args += ["--model", model]
        if effort:
            args += ["--effort", effort]
        self._log("spawn", {"args": args[1:], "cwd": rec["cwd"]})
        self.proc = await asyncio.create_subprocess_exec(
            *args, cwd=rec["cwd"], limit=STREAM_LIMIT,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        self.proc_args = (model, effort)
        self._reader = asyncio.create_task(self._read_stdout(self.proc))
        self._err_reader = asyncio.create_task(self._read_stderr(self.proc))

    async def stop_process(self, grace: float = 20) -> None:
        proc = self.proc
        if proc is None:
            return
        if proc.returncode is None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(proc.wait(), grace)
            except TimeoutError:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 5)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
        for task in (self._reader, self._err_reader):
            if task:
                try:
                    await asyncio.wait_for(task, 5)
                except (TimeoutError, Exception):
                    task.cancel()
        self.proc = None
        registry.release(self.id, os.getpid())

    async def ensure_process(self, model: str | None, effort: str | None) -> None:
        """Start the process, or restart it if the requested model/effort changed."""
        if self.alive and self.proc_args == (model, effort):
            return
        if self.alive:
            await self.stop_process()
        await self.start_process(model, effort)

    # ----- readers --------------------------------------------------------------

    async def _read_stderr(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stderr
        async for raw in proc.stderr:
            line = raw.decode(errors="replace").rstrip()
            if not line:
                continue
            self._log("stderr", line)
            # AGY's own verbose glog lines start with I/W/E + date; keep the rest.
            if not re.match(r"^[IWE]\d{4} ", line):
                self.stderr_tail.append(line)

    async def _read_stdout(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout
        error = None
        try:
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").strip()
                if not line:
                    continue
                self._log("stdout", line)
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                await self._on_event(event)
        except Exception as e:  # never leave a turn hanging on a bridge-side failure
            error = f"agy-bridge failed while reading AGY's output: {type(e).__name__}: {e}"
            if proc.returncode is None:
                proc.kill()
        await proc.wait()
        self._log("exit", proc.returncode)
        if self.proc is proc:  # the process is gone: let other bridges take the session
            await asyncio.to_thread(registry.release, self.id, os.getpid())
        turn = self.turn
        if turn and not turn.done.is_set():
            turn.result = {"status": "ERROR",
                           "error": error or f"agy exited with code {proc.returncode} "
                                             "during the turn",
                           "stderr": list(self.stderr_tail)[-10:]}
            await self._finish_turn(turn)

    async def _on_event(self, event: dict[str, Any]) -> None:
        kind = event.get("event")
        if kind == "init":
            conv = event.get("conversation_id")
            if conv and conv != self.record.get("conversation_id"):
                self.record["conversation_id"] = conv
                registry.update(self.id, conversation_id=conv)
        elif kind == "step_update":
            step = event.get("step_update") or {}
            if step.get("step_type") == "tool" and step.get("state") == "DONE":
                label = _step_label(step, self.record["cwd"])
                self.recent.append({"t": time.time(), "step": label})
                if self.turn:
                    self.turn.steps.append(label)
        elif kind == "result":
            await self._on_result(event.get("result") or {})

    async def _on_result(self, result: dict[str, Any]) -> None:
        turn = self.turn
        if turn is None or turn.done.is_set():
            return
        # AGY's list grows for the life of the process, and repeats look alike, so what is
        # new is whatever lies past the part already seen.
        denied = result.get("denied_actions") or []
        new = denied[len(self.denied_seen):] if len(denied) >= len(self.denied_seen) else denied
        self.denied_seen = list(denied)
        turn.denied_new.extend(new)
        # A denied action ends the turn with nothing. Ask AGY once to carry on.
        empty = (not (result.get("response") or "").strip()
                 and result.get("structured_output") is None and result.get("status") != "ERROR")
        if new and empty and turn.followups < 1 and self.alive:
            turn.followups += 1
            names = {d.get("display_name") or d.get("action", "?") for d in new}
            actions = ", ".join(sorted(names))
            self._log("auto_followup", actions)
            await self._send_raw(DENIED_FOLLOWUP.format(actions=actions))
            return
        turn.result = result
        await self._finish_turn(turn)

    async def _finish_turn(self, turn: Turn) -> None:
        if turn.ended is not None:  # the reader and send() may both get here
            return
        cwd = self.record["cwd"]
        turn.ended = time.time()
        try:
            if turn.before is not None:
                after = await asyncio.to_thread(tree.snapshot, cwd)
                turn.tree_changes = tree.diff(turn.before, after)
            turn.overlapping = await asyncio.to_thread(
                registry.overlapping_turns, self.id, cwd, turn.started, turn.ended)
            await asyncio.to_thread(registry.update, self.id, turn_ended=turn.ended)
        except Exception as e:  # bookkeeping only; never lose the turn's result over it
            self.stderr_tail.append(f"agy-bridge: turn bookkeeping failed: {e}")
        finally:
            turn.done.set()

    # ----- turns -----------------------------------------------------------------

    async def _send_raw(self, text: str) -> None:
        assert self.proc and self.proc.stdin
        msg = {"event": "user", "message": {"content": text}}
        self._log("send", msg)
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self.proc.stdin.drain()

    async def send(self, text: str, model: str | None, effort: str | None) -> Turn:
        if self.busy or self._send_lock.locked():
            raise RuntimeError(f"session {self.id} is still working on a turn; "
                               "call agy_wait first")
        async with self._send_lock:  # two calls at once must not both start a turn
            await self.ensure_process(model, effort)
            number = int(self.record.get("turns", 0)) + 1
            turn = Turn(number=number, message=text,
                        previous_settings=(self.record.get("model"), self.record.get("effort")))
            turn.before = await asyncio.to_thread(tree.snapshot, self.record["cwd"])
            try:
                turn.backup = await asyncio.to_thread(backup.take, self.id, number,
                                                      self.record["cwd"])
            except Exception as e:  # a failed backup shouldn't block the review; report it
                turn.backup_error = f"{type(e).__name__}: {e}"
            self.record.update(turns=number, last_used=registry.now_iso(),
                               model=model, effort=effort)
            # Recorded before sending, so a fast turn's turn_ended can't be overwritten.
            registry.update(self.id, turns=number, last_used=self.record["last_used"],
                            model=model, effort=effort, turn_started=turn.started,
                            turn_ended=None, turn_pid=os.getpid())
            self.turn = turn
            self.stderr_tail.clear()
            try:
                await self._send_raw(text)
            except OSError as e:  # AGY died before reading the message
                turn.result = {"status": "ERROR", "error": f"could not send to agy: {e}"}
                await self._finish_turn(turn)
            return turn

    def status(self) -> dict[str, Any]:
        turn = self.turn
        info: dict[str, Any] = {
            "session_id": self.id,
            "conversation_id": self.record.get("conversation_id"),
            "agent": self.record["agent"],
            "process": "running" if self.alive else "stopped",
            "state": "working" if self.busy else "idle",
            "turns": self.record.get("turns", 0),
        }
        if turn:
            info["current_turn"] = {
                "number": turn.number,
                "elapsed_seconds": round((turn.ended or time.time()) - turn.started, 1),
                "steps_so_far": len(turn.steps),
                "last_steps": turn.steps[-8:],
                "result_ready": turn.done.is_set() and not turn.collected,
            }
        return info

    def cleanup_scratch(self) -> None:
        shutil.rmtree(scratch_dir(self.id), ignore_errors=True)


def build_turn_payload(session: Session, turn: Turn) -> dict[str, Any]:
    """What Claude gets back for a finished turn: compact, review first."""
    turn.collected = True
    result = turn.result or {}
    out: dict[str, Any] = {
        "session_id": session.id,
        "conversation_id": session.record.get("conversation_id"),
        "turn": turn.number,
        "status": result.get("status", "ERROR"),
    }
    if result.get("error"):
        out["error"] = result["error"]
    review = result.get("structured_output")
    if review is None and result.get("response"):
        review = parse_json_response(result["response"])
        if review is not None:
            out["review_parsed_from_text"] = True
    if review is not None:
        out["review"] = review
    elif result.get("response"):
        out["response"] = result["response"]
    out["duration_seconds"] = round((turn.ended or time.time()) - turn.started, 1)
    if result.get("usage"):
        out["usage"] = result["usage"]

    notes: dict[str, Any] = {}
    if turn.denied_new:
        notes["denied_actions"] = turn.denied_new
        if turn.followups:
            notes["auto_followup"] = "AGY was asked once to continue without the denied actions."
    if turn.tree_changes:
        notes["tree_changed"] = turn.tree_changes
        if turn.backup and ("files" in turn.tree_changes or "git" in turn.tree_changes):
            notes["backup"] = {"dir": turn.backup["dir"],
                               "restore": backup.restore_hint(turn.backup)}
        if turn.overlapping:
            notes["other_reviews_running"] = {
                "sessions": turn.overlapping,
                "note": "Other AGY reviews of this project were working during this turn, so "
                        "tree_changed may include their changes, not only this agent's."}
    if turn.backup_error:
        notes["backup_error"] = turn.backup_error
    if session.stderr_tail and out["status"] != "SUCCESS":
        notes["stderr"] = list(session.stderr_tail)[-10:]
    if notes:
        out["notes"] = notes
    if turn.steps:
        out["looked_at"] = turn.steps[:25] + ([f"… {len(turn.steps) - 25} more"]
                                              if len(turn.steps) > 25 else [])
    return out
