# agy-bridge

Get a second opinion on Claude Code's work from a Google Antigravity (AGY) agent, and
let the two of them talk it through.

agy-bridge is an [MCP](https://modelcontextprotocol.io) server. It gives Claude Code
tools to start an AGY reviewer agent, send it work, read its review, reply with fixes or
counter-arguments, and keep the conversation going over several turns, even across
Claude Code sessions.

> **Not affiliated with Google or Anthropic.** agy-bridge is an independent open-source
> project. Antigravity and Gemini are Google products; Claude and Claude Code are
> Anthropic products. It drives the `agy` command-line tool you already have, using your
> own Antigravity login.

## How it looks

You ask Claude Code:

> Implement the retry logic from the plan, then run AGY with the code-review skill.

Claude writes the code and runs the tests. Then it starts an AGY `code-reviewer`, which
reads the project, runs the tests itself and returns a structured review:

```json
{
  "verdict": "changes_requested",
  "summary": "Retries work, but the backoff ignores Retry-After and one path never gives up.",
  "findings": [
    {"severity": "high", "category": "correctness", "location": "client.py:88",
     "issue": "...", "recommendation": "..."}
  ],
  "questions_for_claude": ["Should a 429 count towards max_attempts?"]
}
```

Claude fixes what it agrees with, argues with what it doesn't, answers the questions and
sends the new diff back. AGY re-checks. When they agree, or after a few rounds, Claude
reports the outcome to you, including any point they still disagree on.

## Requirements

- **AGY CLI**, installed and signed in. agy-bridge finds it at `~/.gemini/bin/agy`, on
  `PATH`, or at `$AGY_BIN`. Tested with AGY 1.5.1 and 1.5.2.
- **Claude Code**, with the `claude` command on `PATH` (used to register the server).
- **Python 3.11+** and [uv](https://docs.astral.sh/uv/).
- **macOS or Linux.** Tested on macOS; Linux runs in CI. Windows is not supported.

## Quick start

```bash
git clone https://github.com/kulaone/agy-bridge.git
cd agy-bridge
uv sync
uv run agy-bridge install
```

Restart Claude Code, then check the setup:

```bash
uv run agy-bridge doctor
```

`install` copies three files and registers the server:

| What | Where |
|---|---|
| The example AGY agent, `code-reviewer` | `~/.gemini/config/agents/code-reviewer.md` |
| Its AGY skill, `code-review` | `~/.gemini/config/skills/code-review/SKILL.md` |
| The Claude skill that teaches Claude the review loop | `~/.claude/skills/agy/SKILL.md` |
| The MCP server, named `agy` | Claude Code's user config |

It never overwrites a file you have changed, and `agy-bridge uninstall` removes only
what it added. See the [install guide](docs/install.md) for per-project installs and
other options.

## Use it

Ask Claude Code in your own words:

- "Review my uncommitted changes with AGY."
- "Run AGY with the code-review skill on this branch against main, using Argon high."
- "What is AGY doing right now?"
- "Resume yesterday's AGY review of this project."

The [user guide](docs/user-guide.md) covers choosing models, long reviews, reading the
results and resuming sessions.

## What AGY may do

AGY is a full reviewer. It may read the whole project, run tests, linters and builds, and
experiment in its own scratch folder. Its instructions forbid changing the project, and
its file-writing tools only work in that scratch folder. Shell commands can't be limited
that way, so agy-bridge also:

- **detects** any change to the project during each turn and reports it to Claude, which
  tells you;
- **backs up** your uncommitted work before each turn, so it can be restored;
- never runs AGY with `--dangerously-skip-permissions`.

Read [SECURITY.md](SECURITY.md) before using it on code you can't afford to have touched.

> **Use at your own risk.** agy-bridge is provided as is, with no warranty and no support
> commitment. You are responsible for what it and AGY do on your machine.

## Documentation

- [Install guide](docs/install.md): install options, per-project installs, uninstalling
- [User guide](docs/user-guide.md): reviews, models, results, sessions, the tools
- [Configuration](docs/configuration.md): environment variables, files and folders
- [Writing your own agents](docs/writing-agents.md): add an architect, a docs reviewer
- [Troubleshooting](docs/troubleshooting.md)
- [Architecture](docs/architecture.md): how it works and why
- [Contributing](CONTRIBUTING.md) and the [changelog](CHANGELOG.md)

## License

[MIT](LICENSE) © Daniel Gwerzman
