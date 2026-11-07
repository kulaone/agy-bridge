# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Docs: [the review method](docs/review-method.md) behind agy-bridge, why a different
  agent should review Claude Code's work and the four-stage loop the bridge runs, linked
  from the README.
- A third example agent, `thinking-partner`, with the `thinking-techniques` skill: a
  thinking partner for any kind of work. It brainstorms and plans before a task and
  reviews after it, choosing a fitting technique (Socratic questioning, pre-mortem, red
  team and more), and guards against hidden assumptions by asking where each claim comes
  from.
- Docs: AGY can also follow other skills it can see (global and the project's own),
  and a project's own agent replaces a shipped one of the same name. SECURITY.md covers
  what that means for untrusted projects, and the Claude skill points out unexpected
  skill files in `looked_at`.
- A `brainstorm` answer format (`format` on `agy_start` and `agy_say`), with options,
  assumptions and their sources, a recommendation and a next step. Switching format
  mid-session keeps the conversation.

- Sessions unused for 30 days lose their scratch folder and backups at server start, to
  save space. They stay resumable. Backups of sessions that no longer exist are removed
  at server start too, as scratch folders already were.
- Dependabot keeps the CI workflow's actions up to date.

### Changed

- Backups no longer copy the same file once per turn. Every file under
  `backup/<session>/turn-NNN/untracked/` is a hardlink into a content-addressed store,
  `backup/blobs/`, shared by all turns and sessions, so a turn in which nothing changed
  costs almost nothing. The restore recipe is unchanged. Untracked files in tool-output
  folders (`__pycache__/`, `node_modules/`, build folders) are no longer backed up in git
  repos that don't ignore them; staged files always are. The unused `git stash create` commit is gone, so a backup no
  longer writes anything into the reviewed repo.
- A model AGY rejects no longer becomes the session's default: the session goes back to
  its previous model and effort, and the result says so (`model_reverted_to`).
- `agy_wait` on a turn this bridge didn't run (for example after Claude Code restarted)
  now explains what happened and how to get the answer back.

## [0.1.0] - 2026-11-06

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
  never overwrites files you changed. `doctor` checks every shipped agent.
- Two example AGY agents:
  - `code-reviewer`, with the `code-review` skill: an outside senior reviewer of code
    changes. It questions the approach and shows alternatives, raises each once, and
    accepts a reasoned answer.
  - `design-reviewer`, with the `architecture-review` skill: an outside architect that
    discusses designs, ADRs and plans with Claude through ten review lenses.
- The Claude skill `agy`, which teaches Claude when to ask for a review and how to run
  the review loop.
- Transcript logging, off by default (`AGY_BRIDGE_LOG=1`).
- Tested with AGY 1.5.1 and 1.5.2.

[Unreleased]: https://github.com/kulaone/agy-bridge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/kulaone/agy-bridge/releases/tag/v0.1.0
