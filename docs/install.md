# Install guide

## Before you start

You need:

- **AGY CLI**, signed in. Run `agy --version` and `agy models` in a terminal. The second
  command lists models only when you are signed in. agy-bridge looks for `agy` at
  `$AGY_BIN`, then `~/.gemini/bin/agy`, then on `PATH`.
- **Claude Code**, with `claude` on `PATH`.
- **Python 3.11 or newer** and **[uv](https://docs.astral.sh/uv/)**.
- **macOS or Linux.** Windows is not supported (the session registry uses POSIX file locks).

agy-bridge is tested with AGY 1.5.1 and 1.5.2. Newer versions usually work. If yours has
not been tested, `agy-bridge doctor` and the first review say so.

## Option 1: from a clone (recommended)

```bash
git clone https://github.com/kulaone/agy-bridge.git
cd agy-bridge
uv sync
uv run agy-bridge install
```

Claude Code then starts the server with `uv run --project <clone>`, so the clone must stay
where it is. To update, run `git pull`, then `uv sync`, then `uv run agy-bridge install`
again.

## Option 2: as a uv tool

```bash
uv tool install git+https://github.com/kulaone/agy-bridge.git
agy-bridge install
```

This puts an `agy-bridge` command on your `PATH`, and that is what gets registered. To
update, run `uv tool upgrade agy-bridge`, then `agy-bridge install`. `pipx install` works
the same way.

## Then

1. **Restart Claude Code.** It loads MCP servers and skills when it starts.
2. **Run `agy-bridge doctor`**, or `uv run agy-bridge doctor` from a clone. It checks:
   - AGY is installed and signed in;
   - the shipped agents use only tools your AGY has;
   - the Claude skill is installed;
   - Claude Code can connect to the server;
   - the state folder is writable.

   The first run takes about a minute while it asks AGY for its tool list. After that,
   the list is cached until AGY's version changes.
3. In Claude Code, ask: "Review my uncommitted changes with AGY."

## What `install` does

| Step | Global install (default) | `--project DIR` |
|---|---|---|
| AGY agents `code-reviewer`, `design-reviewer`, `thinking-partner` | `~/.gemini/config/agents/` | `DIR/.agents/agents/` |
| AGY skills `code-review`, `architecture-review`, `thinking-techniques` | `~/.gemini/config/skills/` | `DIR/.agents/skills/` |
| Claude skill `agy` | `~/.claude/skills/` | `DIR/.claude/skills/` |
| MCP server `agy` | Claude Code user scope (`~/.claude.json`) | project scope (`DIR/.mcp.json`) |

`install` records what it wrote, with a checksum of each file, in
`~/.agy-bridge/install.json`. That record keeps it safe to run again:

- **Unchanged files** are left alone, or updated to the new version.
- **Files you have edited** are kept. `--force` replaces them, and saves the old file next
  to it as `<name>.bak-<date>`.
- **Files that already existed** before agy-bridge are treated as yours, and kept the
  same way.
- **The MCP registration** is left alone if it already runs the same command. If it runs
  a different command, `install` keeps it and tells you; `--force` replaces it.

Each agent file names its skill by absolute path, because AGY requires one. `install`
fills that path in for you.

### Options

| Option | Effect |
|---|---|
| `--project DIR` | Install into one project instead of your home folder (see below). |
| `--force` | Replace files and a registration that differ. Keeps `.bak` copies of files. |
| `--no-register` | Copy the files only; don't touch Claude Code's MCP config. |
| `--server-command CMD` | The command Claude Code should run, e.g. `--server-command "/opt/bin/agy-bridge serve"`. By default it is worked out from how agy-bridge was installed. |
| `--dry-run` | Print what would change and change nothing. |

## Per-project install

```bash
agy-bridge install --project ~/code/my-app
```

Use it to keep the agents and skills in a project's own repo, where you can tune them for
that project. AGY uses the nearest agent with a given name, so inside that project its
agents take over from the global ones, together with the skills they point to.

When you commit those files, keep in mind:

- Each agent file contains an absolute path to its skill folder, which only works on
  your machine. Each teammate edits the `skills:` path in the committed
  `.agents/agents/*.md` files to match their checkout, unless everyone keeps the
  repo at the same path. (Running `install --project .` on their side won't help: it
  keeps files it didn't write, and `--force` would reset your team's edits to the stock
  files.)
- Claude Code asks for approval before it uses a server from a project's `.mcp.json`.
- The registered command points at your copy of agy-bridge, so it is personal too. If
  teammates install agy-bridge in different ways, use `--no-register` for the project and
  have each person install globally.

## Registering by hand

If `claude` is not on `PATH`, `install` prints the command to run. Its shape:

```bash
claude mcp add --scope user agy -- /path/to/agy-bridge
```

Any command that starts the server works: `agy-bridge`, `agy-bridge serve`,
`python -m agy_bridge`, or `uv run --project <clone> agy-bridge`. Then restart Claude Code.

## Uninstall

```bash
agy-bridge uninstall                 # or: --project DIR; from a clone: uv run agy-bridge uninstall
```

This removes the files and registration that `install` added, and keeps anything you
have changed since; `--force` removes those too. `--dry-run` shows what it would do.

Your sessions, backups and scratch folders stay in `~/.agy-bridge/`. Delete that folder
to remove them. Finally, remove the program itself: `uv tool uninstall agy-bridge`, or
delete the clone.
