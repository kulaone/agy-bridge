# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- A second example agent, `design-reviewer`, with the `architecture-review` skill: an
  outside architect that discusses designs, ADRs and plans with Claude, through ten
  review lenses. `doctor` checks every shipped agent.

### Changed

- `code-reviewer` is now an outside senior reviewer. It questions the approach and
  shows alternatives, raises each once, and accepts a reasoned answer.

## [0.1.0] - unreleased

First public release.

### Tools

- An MCP server with eight tools:
  - `agy_list_agents`, `agy_start`, `agy_say`, `agy_wait`;
  - `agy_status`, `agy_sessions`, `agy_resume`, `agy_end`.
- Multi-turn conversations with AGY agents. Each session keeps one long-running `agy`
  process, and sessions can be resumed across Claude Code sessions.
- Long turns return `RUNNING` and can be collected later; progress is sent while AGY
  works.
- Model and effort can be chosen per message, and switching keeps the conversation.

### Safety

- Each turn detects and reports changes to the project, and backs up uncommitted work
  first.
- Per-session AGY permissions: any shell command, file writes only in a scratch folder.
  Denied actions are reported, and AGY gets one follow-up asking it to continue without
  them.
- The agent's tool list is checked against AGY's real tools before a session starts.

### Several sessions at once

- Several Claude Code windows can share the session registry. A session is driven by
  one window at a time.
- Overlapping reviews of the same project are flagged in each result.

### Setup and logging

- `agy-bridge install`, `uninstall` and `doctor`. Install is global or per project, and
  never overwrites files you changed.
- An example `code-reviewer` agent, its `code-review` skill, and the Claude skill `agy`.
- Transcript logging, off by default (`AGY_BRIDGE_LOG=1`).
- Tested with AGY 1.5.1 and 1.5.2.
