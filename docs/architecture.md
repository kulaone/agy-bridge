# Architecture

How agy-bridge works, and why it is built this way. For the original design brief and
the experiments behind it, see the [design log](history/design-log.md).

## The pieces

```
Claude Code ──stdio MCP──▶ agy-bridge (one per Claude Code session)
                              │
                              ├─ one long-running `agy` process per AGY session
                              │    stream-json in and out, cwd = the project
                              │
                              └─ ~/.agy-bridge/  sessions.json, scratch/, backup/, cache.json
```

- **Claude Code** starts one agy-bridge process for each of its sessions. The Claude
  skill `agy` tells Claude when to call the tools and how to run the review loop.
- **agy-bridge** is a Python MCP server. It talks to Claude Code over stdio.
- **AGY** runs as `agy --input-format stream-json --output-format stream-json`. Each
  process keeps one conversation open, so later turns are fast and AGY keeps its
  context. The bridge writes messages to its stdin and reads NDJSON events from its
  stdout.

## Modules

| Module | Responsibility |
|---|---|
| `server.py` | The MCP tools, the wait-or-return-`RUNNING` logic, progress notifications. |
| `session.py` | One AGY conversation: process lifecycle, the event reader, turns, the result Claude gets. |
| `registry.py` | `sessions.json`, under a file lock: session records, process ownership, overlapping turns. |
| `tree.py` | Snapshots of the project before and after a turn, and the diff between them. |
| `backup.py` | The per-turn backup of uncommitted work. |
| `selfcheck.py` | AGY's version, models and real tool list (cached), and the agent tool check. |
| `paths.py` | Locations and environment variables. |
| `cli.py` | `install`, `uninstall`, `doctor`, `serve`. |
| `assets/` | The files `install` copies: the example agent, its skill, and the Claude skill. |

## A turn

1. **Before sending.** The bridge:
   - snapshots the project's files: size and mtime of every tracked and non-ignored file,
     plus `HEAD`, branch, stashes and worktrees;
   - backs up the uncommitted work;
   - records in the registry that a turn has started.
2. **Sending.** The message goes to AGY's stdin. The first message of a session also names
   the project directory and the scratch directory, and says not to modify the project.
3. **While AGY works.** A background reader handles each event from AGY:
   - `init` gives the conversation id, which is stored so the session can be resumed;
   - each finished tool step is recorded and sent to Claude as a progress notification;
   - `result` ends the turn.
4. **Denied actions.** A denied action ends AGY's turn with an empty answer. When that
   happens, the bridge sends one follow-up asking AGY to continue without it.
5. **After the result.** The bridge:
   - snapshots the project again and diffs it with the first snapshot;
   - checks the registry for other turns on the same project that overlapped this one;
   - returns the review with any notes.
6. **Waiting.** The tool call waits up to `wait_seconds`. If the turn isn't done by then,
   the call returns `RUNNING`, the turn keeps going, and `agy_wait` collects it later.

If AGY exits during a turn, the turn ends with an error and the last lines of AGY's
stderr. The next message starts a new process on the same conversation with
`--conversation <id>`. A new model or effort does the same, so switching models keeps
the conversation.

## Sessions across processes

Several Claude Code windows each run their own bridge, and all of them share
`sessions.json`:

- Every read-modify-write takes an exclusive lock, and the file is replaced atomically.
- A bridge that starts an AGY process for a session records itself as the owner
  (`owner_pid`). Another bridge refuses to drive that session while the owner is alive.
- "Alive" means the process exists and its command line is an agy-bridge, which guards
  against a reused PID. When the owner's process ends, the claim lapses.
- Ending a session releases the claim. Any bridge can then resume the session from the
  stored conversation id.

## Self-check

AGY hangs when an agent lists a tool that doesn't exist. So before a session starts, the
bridge compares the agent file's `tools:` with the tools AGY really has. It finds those by
running one tiny prompt and reading AGY's `init` event. The result is cached per AGY
version; the model list is cached for a day.

The bridge also compares AGY's version with the versions it was tested with, and adds a
note when they differ.

## Key decisions

**The CLI, not the SDK.**
The AGY CLI uses the user's existing Antigravity sign-in and plan. The Python SDK
would need a separate API key, and was a research preview at the time.

**Write safety is prompt-guided, then detected and backed up; it is not enforced.**
A useful reviewer runs tests, and tests are shell commands that can write anywhere.
Blocking all writes would make AGY a much weaker reviewer, and AGY has no sandbox that
allows test runs but forbids edits. So:

- the agent's rules forbid changing the project;
- file-writing tools work only in the scratch folder;
- every turn is snapshotted and backed up;
- any change is reported to Claude, and through Claude to the user.

**Never `--dangerously-skip-permissions`.**
Permissions come from per-session settings passed with `--settings`. Anything those
don't allow is denied and reported, not approved silently. The user's own AGY settings
are never edited.

**No fixed models.**
Model names change often, and plans differ in which models they include. The bridge
passes through whatever the user or Claude picks, and otherwise leaves the choice to
AGY's default.

**One long-running process per session.**
Starting AGY for each turn would be slower and would lose in-process state. A crashed
or restarted process resumes from the conversation id.

**Return `RUNNING` instead of blocking forever.**
Reviews take minutes. MCP clients may time out a call, and the user should be able to
ask for progress while they wait.

**Transcript logging is opt-in.**
A transcript holds the user's code, so it is written only when the user asks for it.

## Limits

- **Change detection uses size and mtime.** An edit that keeps both the same is missed.
  So is a file that changes and then changes back within one turn.
- **Ignored files are not watched** in git repos: most caches and build output.
- **Backups skip files over 10 MB, and stop at 100 MB per turn.** The manifest lists
  what was skipped.
- **POSIX only.** `fcntl` locks and `ps` are used, so Windows is not supported.
