# Troubleshooting

Start with `agy-bridge doctor` (or `uv run agy-bridge doctor` from a clone). Run it from
the project you are reviewing, or pass `--cwd DIR`, so it finds that project's own agent
and skill. Each line it prints is marked `✓` (fine), `!` (worth knowing) or `✗` (needs
fixing).

## Setup

### `agy not found`
Install the AGY CLI, or point `AGY_BIN` at it. If `agy` runs in your terminal but not
for the server, Claude Code may have started with a different `PATH`. Setting `AGY_BIN`
in the server's `env` block always works (see [Configuration](configuration.md)).

### `agy models` listed nothing
You are not signed in to AGY. Run `agy` in a terminal, sign in, then run doctor again.

### The `agy_*` tools don't appear in Claude Code
Restart Claude Code after installing. Then run `claude mcp get agy`: it should say
`✔ Connected`. If it fails, run the command it shows yourself to see the error. A
common cause is a moved or deleted clone. In that case run `agy-bridge install --force`
from the new location.

### A project-scope server shows as pending
Claude Code asks for approval before it uses a server from a project's `.mcp.json`.
Approve it when Claude Code asks, or check it with `/mcp` in an interactive `claude`
terminal.

### `install` says a file "exists and differs: kept"
You, or an earlier version, changed that file. Keep yours, or run `install --force` to
take the new version; the old file is then saved next to it as `.bak-<date>`, so you can
copy your changes back. `install --dry-run` lists which files differ.

### `install` says the server "is registered with another command"
Another copy of agy-bridge is registered, for example from an old clone.
`install --force` replaces it with this one.

### Doctor: the agent "still has a {{...}} placeholder"
The agent file was copied by hand. Run `agy-bridge install --force`, which fills in the
skill path.

## Starting a review

### `Agent 'X' lists tools AGY ... doesn't have: [...]`
The agent's `tools:` list names a tool your AGY version doesn't have, usually because
AGY renamed it. agy-bridge refuses to start rather than let AGY hang, which is what AGY
does with an unknown tool. Fix the names in the agent file. The tool names your AGY
knows are in `~/.agy-bridge/cache.json` under `tools`.

### `... must list the finish tool`
Without `finish`, AGY returns no structured answer. Add it to the agent's `tools:`.

### `AGY X has not been tested with agy-bridge`
A newer AGY may have changed its CLI. Most things keep working; if reviews misbehave,
look for an agy-bridge update or [open an issue](../CONTRIBUTING.md#reporting-bugs).

### A model error, such as an unknown model
The result lists `available_models`. Your AGY plan may not include that model, or its
name has changed. Ask Claude to refresh the AGY model list.

### `cwd is not a directory`
The project path must be absolute and exist.

## During a review

### The review seems stuck
Ask Claude "What is AGY doing?". The last steps show whether AGY is still working,
for example running a slow test suite. A tool call returns `RUNNING` after 10 minutes,
but the review keeps going. To give up, ask Claude to end the session.

### `status: ERROR` with "agy exited with code N during the turn"
AGY crashed or was killed. The result includes the last lines of AGY's error output.
Ask Claude to send the message again: the session restarts AGY on the same
conversation.

### `session ... is in use by another agy-bridge process`
Another Claude Code window is driving this session. Continue there, or start a new
session. If that window was closed, the lock clears by itself, because the bridge
checks whether the owning process is still running.

### `notes.tree_changed` lists files
Something changed in the project during the turn. Possible causes:
- your own editor;
- another review (look for `other_reviews_running`);
- a test that writes files;
- AGY breaking its rules.

Look at the diff. To undo the change, use the restore recipe in `notes.backup` (see
[Restoring from a backup](user-guide.md#restoring-from-a-backup)).

### `notes.denied_actions`
AGY tried something its permissions don't allow, and the review went on without it.
If the review is missing something because of that, tell Claude what AGY may do
instead, such as "copy the file into your scratch folder first".

### The review came back as text, not JSON
The result has `review_parsed_from_text` or a raw `response`. Some models follow the
schema less reliably. Try another model, or check that the agent lists `finish`.

## Reporting a bug

1. Run `agy-bridge doctor` and keep its output.
2. Turn on logging (`AGY_BRIDGE_LOG=1`, see [Configuration](configuration.md)), restart
   Claude Code, and reproduce the problem.
3. Open an issue with:
   - the doctor output;
   - your OS;
   - `agy --version`;
   - what you asked;
   - what happened.

   Attach the relevant part of `~/.agy-bridge/logs/<session>.ndjson` only after removing
   anything private, since logs contain your code.
