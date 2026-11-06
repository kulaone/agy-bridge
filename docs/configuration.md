# Configuration

agy-bridge has no config file. It is set up through a few environment variables, the
files `install` puts in place, and the agent files themselves.

## Environment variables

| Variable | Default | Effect |
|---|---|---|
| `AGY_BIN` | `~/.gemini/bin/agy`, then `agy` on `PATH` | The AGY executable to run. |
| `AGY_BRIDGE_HOME` | `~/.agy-bridge` | Where sessions, scratch folders, backups, caches and logs live. |
| `AGY_BRIDGE_LOG` | off | Set to `1` to keep a full transcript of every session in `logs/`. |

The server reads these when Claude Code starts it, so set them in the server's MCP entry;
your shell's environment doesn't reach it. Add an `env` block to the `agy` entry in `~/.claude.json` (user scope)
or in the project's `.mcp.json` (project scope):

```json
"agy": {
  "command": "/Users/you/.local/bin/agy-bridge",
  "args": [],
  "env": {"AGY_BRIDGE_LOG": "1"}
}
```

Or register it with the variable from the start:

```bash
claude mcp remove agy -s user
claude mcp add --scope user agy -e AGY_BRIDGE_LOG=1 -- /path/to/agy-bridge
```

Then restart Claude Code.

The `agy-bridge` commands (`install`, `uninstall`, `doctor`) run in your shell and read
your shell's environment, not the MCP entry. If you set `AGY_BIN` or `AGY_BRIDGE_HOME`
for the server, export them in your shell too, or `doctor` checks a different `agy` or
state folder. Likewise, `doctor`'s "transcript logging" line reflects your shell.

If `install --force` replaces a registration that ran a different command, the new
registration has no `env` block, so add it back afterwards.

### Transcript logging

Logging is off by default because a transcript includes everything AGY read and wrote,
which means your code. When it is on, `logs/<session>.ndjson` records:

- the command line each AGY process was started with;
- every message sent to AGY;
- every event AGY returned;
- AGY's stderr.

Turn it on to debug a problem or to report a bug. Read a log before sharing it.
`agy_end` with `forget` deletes that session's log.

## The state folder

`~/.agy-bridge/`, or `$AGY_BRIDGE_HOME`:

| Path | Contents | Cleaned up |
|---|---|---|
| `sessions.json` | One record per session: agent, project, model, effort, AGY conversation id, turn count, last verdict. | `agy_end` with `forget` |
| `sessions.lock` | Lock file, so several bridges can share the registry. | — |
| `scratch/<session>/` | AGY's own folder for experiments, such as copies or a `git worktree`. | `forget`; and at server start, folders with no session |
| `backup/<session>/turn-NNN/` | Your uncommitted work, saved before each turn. | Last 5 turns kept; `forget` removes all |
| `cache.json` | AGY's tool list (per AGY version) and model list (refreshed daily). | Delete it any time |
| `install.json` | What `install` wrote, with checksums. | `uninstall` |
| `logs/<session>.ndjson` | Transcripts, only when `AGY_BRIDGE_LOG` is on. | `forget` |

If `sessions.json` ever gets corrupted, it is renamed to `sessions.corrupt.json` and a
fresh one is started.

## What AGY is allowed to do

Each AGY process is started with settings for that session only. Your own AGY settings
are not changed, so interactive AGY use is unaffected. The settings allow:

- **Shell commands**: any. A reviewer needs to run tests, linters and builds.
- **File-writing tools**: only inside the session's scratch folder.

Anything outside these rules that AGY would normally ask you to approve is denied, since
nobody is there to approve it. AGY reports what was denied, and agy-bridge asks it once
to carry on without it. agy-bridge never passes
`--dangerously-skip-permissions`.

Shell commands can still change files. The agent's instructions forbid changing the
project, and the bridge detects and backs up, as described in the [user guide](user-guide.md#reading-the-result).
See [SECURITY.md](../SECURITY.md) for what that does and does not protect against.

## Models and effort

agy-bridge itself has no default model. The Claude skill tells Claude to use a medium
effort level by default, on a model from your AGY's list; if no model is passed, AGY uses
its own default. The model list comes from `agy models` and is cached for a day; ask Claude
to "refresh the AGY model list" after AGY adds models.

## The review format

By default AGY must answer in the review schema: `verdict`, `summary`, `findings` and
`questions_for_claude`. The full schema is in
[`src/agy_bridge/data/review.schema.json`](../src/agy_bridge/data/review.schema.json).
`agy_start` takes a `schema` argument to use a different one for a session. If AGY
answers in plain text instead, agy-bridge takes the first JSON object from the text and
marks the result `review_parsed_from_text`.

## Agents and skills

Edit the installed agents and skills to suit you. `install` won't overwrite your edits:

- `~/.gemini/config/agents/code-reviewer.md` and `design-reviewer.md`: each reviewer's
  role and ground rules, and the tools it may use.
- `~/.gemini/config/skills/code-review/SKILL.md`: how to review code, the checklist, and
  how to grade severity.
- `~/.gemini/config/skills/architecture-review/`: how to review a design (`SKILL.md`)
  and the ten review lenses (`references/principles.md`).
- `~/.claude/skills/agy/SKILL.md`: how Claude runs the review loop: how many rounds,
  when to stop arguing, what to report.

To add more agents, see [Writing your own agents](writing-agents.md).
