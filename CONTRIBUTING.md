# Contributing

Thanks for helping. Bug reports, fixes, docs improvements and example agents are all
welcome.

## Reporting bugs

Open an issue using the bug report template. Include:

- the output of `agy-bridge doctor`;
- `agy --version`;
- your OS;
- what you asked Claude to do, and what happened.

A transcript helps most; see [Troubleshooting](docs/troubleshooting.md#reporting-a-bug)
for how to capture one safely.

agy-bridge is maintained in spare time and provided as is (see [SECURITY.md](SECURITY.md)),
so there is no promise of a reply or a fix. Pull requests are the surest way to get
something changed.

## Development setup

```bash
git clone https://github.com/kulaone/agy-bridge.git
cd agy-bridge
uv sync
```

To try your changes in Claude Code, run `uv run agy-bridge install` from the clone.
Claude Code then runs your working copy. Restart Claude Code after each change to the
server.

## Tests

```bash
uv run pytest
uv run ruff check src tests scripts
```

The test suite needs no AGY account, Claude Code or network:

- `tests/fake_agy.py` stands in for `agy`. It speaks the same stream-json protocol, and
  directives in a message drive its behaviour, e.g. `[[sleep 3]]`, `[[deny]]`,
  `[[crash]]` or `[[write stats.py]]`.
- `tests/fake_claude.py` stands in for `claude mcp`.
- The end-to-end tests in `tests/test_bridge.py` run the real server over stdio, the way
  Claude Code does.
- Every test uses a temporary home folder, so your real setup is never touched.

CI runs both commands on Ubuntu and macOS with Python 3.11 to 3.13.

### Against real AGY

Two scripts drive the real AGY CLI. They need it installed and signed in, and the
`code-reviewer` agent installed (`uv run agy-bridge install`). They use your AGY quota.

```bash
uv run python scripts/live_checks.py   # parallel reviews, model switch, blocked action
uv run python scripts/smoke.py <git repo with an uncommitted change> [model] [agent]
```

`live_checks.py` creates its own throwaway repo and state folder, and takes 5 to 15
minutes. `smoke.py` needs a throwaway git repo with a tracked `stats.py` that has an
uncommitted change; it appends to that file during the run. Run both before a release,
and after every AGY update.

### When AGY releases a new version

1. Run both live scripts against the new version.
2. If they pass, add the version to `TESTED_AGY_VERSIONS` in `src/agy_bridge/selfcheck.py`
   and to the README and `docs/install.md`.
3. If AGY renamed tools, update the `tools:` lists in
   `src/agy_bridge/assets/agy/agents/*.md`.

## Pull requests

- Keep each pull request to one change. Add or update tests for any behaviour that
  changes.
- Match the surrounding style. Ruff enforces formatting rules with a line length of 100.
  Keep comments for the reasons behind code, not what it does.
- Update the docs and `CHANGELOG.md` (under *Unreleased*) when users would notice the
  change.
- Don't add hard-coded model names. Models come from `agy models`, and the user or
  Claude chooses one.
- Never pass `--dangerously-skip-permissions` to AGY.

## Layout

```
src/agy_bridge/     the server and CLI (see docs/architecture.md)
  assets/           files `install` copies: example agents, their skills, the Claude skill
  data/             the default review schema
tests/              offline tests with fake agy and claude
scripts/            live checks against real AGY
docs/               user docs; docs/history/ holds the original design log
```
