"""A stand-in for the `agy` CLI, so the bridge can be tested without AGY or an account.

It speaks the same NDJSON stream-json protocol as AGY 1.5 (event shapes copied from
real logs) and supports the subcommands the bridge uses: --version, models, agents
and `-p`. A user message steers each turn with directives:

  [[sleep N]]      take N seconds (emitting a tool step first)
  [[deny]]         end the turn with an empty response and a denied action
  [[crash]]        exit with code 3 in the middle of the turn
  [[write PATH]]   append a line to PATH in the project (a misbehaving reviewer)
  [[error MSG]]    end the turn with status ERROR
  [[text]]         answer in fenced JSON text instead of structured_output

Environment: FAKE_AGY_VERSION (default 1.5.2), FAKE_AGY_STATE (folder for
conversation history and the argv log, required for stream-json mode).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

TOOLS = ["command_status", "find_by_name", "finish", "grep_search", "list_dir",
         "multi_replace_file_content", "read_url_content", "replace_file_content",
         "run_command", "search_web", "sed_file", "send_command_input", "view_file",
         "write_to_file"]
MODELS = [("gemini-fake-pro", "Fake Pro"), ("gemini-fake-flash-low", "Fake Flash (Low)")]


def emit(event: dict) -> None:
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def arg(args: list[str], name: str) -> str | None:
    return args[args.index(name) + 1] if name in args else None


def init_event(conv: str, args: list[str]) -> dict:
    return {"event": "init", "conversation_id": conv,
            "init": {"model": arg(args, "--model") or "gemini-fake-pro", "cwd": os.getcwd(),
                     "agent": arg(args, "--agent"), "tools": TOOLS}}


def step(conv: str, index: int, **fields) -> None:
    emit({"event": "step_update",
          "step_update": {"conversation_id": conv, "step_index": index, **fields}})


def result(conv: str, **fields) -> None:
    emit({"event": "result", "result": {"conversation_id": conv, "status": "SUCCESS",
                                        "response": "", "usage": {"total_tokens": 1},
                                        **fields}})


def stream(args: list[str]) -> None:
    state = Path(os.environ["FAKE_AGY_STATE"])
    state.mkdir(parents=True, exist_ok=True)
    with open(state / "argv.ndjson", "a") as f:
        f.write(json.dumps({"argv": args, "cwd": os.getcwd(), "pid": os.getpid()}) + "\n")
    conv = arg(args, "--conversation") or str(uuid.uuid4())
    history_file = state / f"{conv}.json"
    history = json.loads(history_file.read_text()) if history_file.exists() else []
    model = arg(args, "--model")
    denied: list[dict] = []  # accumulates across turns, as AGY's does
    deny_pending = False
    started = False
    index = 0

    for line in sys.stdin:
        if not line.strip():
            continue
        text = json.loads(line)["message"]["content"]
        if not started:
            emit(init_event(conv, args))
            started = True
        history.append(text)
        history_file.write_text(json.dumps(history))
        step(conv, index, state="DONE", step_type="user_input")
        index += 1

        if model == "bad-model":
            result(conv, status="ERROR", error=f"unknown model {model!r}")
            continue
        if m := re.search(r"\[\[sleep (\d+(?:\.\d+)?)\]\]", text):
            step(conv, index, state="DONE", step_type="tool", tool_name="read_file",
                 tool_info={"name": "read_file",
                            "parameters": {"Path": os.path.join(os.getcwd(), "stats.py")}})
            index += 1
            time.sleep(float(m.group(1)))
        if "[[crash]]" in text:
            sys.exit(3)
        for path in re.findall(r"\[\[write (\S+?)\]\]", text):
            with open(path, "a") as f:
                f.write("# written by fake agy\n")
        if m := re.search(r"\[\[error (.+?)\]\]", text):
            result(conv, status="ERROR", error=m.group(1))
            continue
        if "[[deny]]" in text and not deny_pending:
            deny_pending = True
            denied.append({"action": "command", "display_name": "RunCommand"})
            result(conv, denied_actions=list(denied))
            continue
        deny_pending = False

        review = {"verdict": "approve",
                  "summary": f"message {len(history)} of conversation {conv}; "
                             f"model={model}; effort={arg(args, '--effort')}",
                  "findings": [], "questions_for_claude": []}
        step(conv, index, state="DONE", step_type="finish")
        index += 1
        extra = {"denied_actions": list(denied)} if denied else {}
        if "[[text]]" in text:
            result(conv, response=f"Here it is:\n```json\n{json.dumps(review)}\n```", **extra)
        else:
            result(conv, response=json.dumps(review), structured_output=review, **extra)


def main() -> None:
    args = sys.argv[1:]
    if "--version" in args:
        print(os.environ.get("FAKE_AGY_VERSION", "1.5.2"))
    elif args[:1] == ["models"]:
        for slug, label in MODELS:
            print(f"{slug}\t{label}")
    elif args[:1] == ["agents"]:
        agents = Path.home() / ".gemini" / "config" / "agents"
        for f in sorted(agents.glob("*.md")) if agents.is_dir() else []:
            print(f.stem)
    elif "-p" in args:
        conv = str(uuid.uuid4())
        emit(init_event(conv, args))
        result(conv, response="ok")
    elif arg(args, "--input-format") == "stream-json":
        stream(args)
    else:
        print(f"fake agy: unsupported arguments {args}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
