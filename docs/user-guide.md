# User guide

You mostly talk to Claude Code, and it calls the agy-bridge tools for you. The Claude
skill `agy` that `install` adds teaches Claude when and how to call them. This guide
covers what you can ask for and what happens.

## Asking for a review

agy-bridge never starts a review on its own. Ask for one:

- "Review my uncommitted changes with AGY."
- "Get an AGY review of this branch against main."
- "Implement the plan, then run AGY with the code-review skill."

For the last one, Claude finishes and checks its own work first, then starts the review.

Claude writes the first message to AGY itself. AGY doesn't see your conversation with
Claude, so that message says:

- what changed and why;
- what to review: uncommitted changes, a branch range, or files;
- how to run the tests;
- anything to look at closely.

You can add your own instructions: "Ask AGY to focus on the SQL", or "Tell it the flaky
test is known."

## Choosing a model

Unless you say otherwise, Claude picks a strong model at a medium effort level, and goes
higher for architecture, security-sensitive or risky changes. To change the default, edit
"Pick model and effort" in `~/.claude/skills/agy/SKILL.md`. To pick a model for one
review, name it:

- "Use Argon high." Claude maps this to a slug such as `gemini-4-argon-high`.
- "Run it on Flash with medium effort."

Claude reads the list of models from your AGY installation; agy-bridge doesn't fix one.
A model slug can include an effort level (`…-low`, `…-high`). Alternatively, give a base
slug plus an effort: `low`, `medium`, `high`, `xhigh` or `max`. Some models don't accept
an effort. If AGY rejects a model, the result includes the slugs it does accept.

You can switch model partway through a review: "Do the next round on Flash." The
conversation carries over, so AGY remembers the earlier turns. A new model starts with
no effort level unless you give one, since the old level may not suit it.

## How a review goes

1. **AGY reviews.** It reads the code, runs tests if it can, and may experiment in its
   scratch folder. This takes minutes, often 1 to 5. `code-reviewer` acts as an
   outside senior reviewer: besides bugs, it questions the approach ("why X rather
   than Y?") and shows alternatives, but leaves the direction to you and Claude.
2. **Claude responds.** For each finding, Claude either fixes it and re-runs the tests, or
   explains why it disagrees, with evidence. It also answers AGY's questions, and asks you
   any that only you can answer.
3. **AGY re-checks.** It drops findings that are fixed, and reconsiders the ones Claude
   disputed.
4. **Repeat** until AGY approves, or for about three rounds unless you say otherwise.
   If Claude changed anything, it always sends at least one round to check the changes.
5. **Claude reports**:
   - the verdict;
   - what was found and fixed;
   - any finding the two still disagree on, with both positions;
   - questions for you;
   - the session id.

If AGY still holds a finding after Claude has argued against it once, Claude stops arguing
and brings it to you.

### Long reviews

Each tool call waits up to 10 minutes. If AGY takes longer, the call returns
`RUNNING` and Claude keeps waiting with `agy_wait`. The review itself keeps going
regardless.

Ask "What is AGY doing?" at any time. Claude then reports:

- which turn AGY is on;
- how long it has been working;
- its last few steps, e.g. `run_command python -m pytest -q` or `view_file src/api.py`.

### Two reviews at once

You can run several reviews of the same project at the same time, from one Claude Code
window or several. Each has its own AGY conversation and scratch folder.

While reviews overlap, a change to the project shows up in all of them, so each result
says which other reviews were running. Claude then checks who made the change before
blaming any one reviewer.

## Reading the result

A review has:

- **verdict**: `approve`, `changes_requested`, or `needs_discussion` (important
  questions are open, or the approach itself is in question).
- **summary**: a few sentences.
- **findings**: each with:
  - `severity`: `critical`, `high`, `medium`, `low` or `info`;
  - a `category`;
  - a `location`: `path:line` for code, a section or component for a design;
  - the `issue`;
  - a `recommendation`.
- **questions_for_claude**: what AGY wants answered.

Claude may also mention one of these notes:

| Note | Meaning |
|---|---|
| `tree_changed` | Files in the project changed during the turn. AGY must not change the project, so Claude tells you which files changed and shows the diff. It offers to revert them; it never reverts without asking. |
| `backup` | Where the pre-turn backup of your uncommitted work is, and how to restore it (see below). |
| `other_reviews_running` | Other reviews of this project were working at the same time, so a `tree_changed` may be theirs. |
| `denied_actions` | AGY tried something its permissions don't allow, such as writing outside its scratch folder. The bridge asked it once to continue without it. The review may be thinner in that area. |
| `agy_version` | Your AGY version hasn't been tested with agy-bridge. |
| `likely_tool_output` | Caches or build output from running tests, e.g. `__pycache__/`. Usually harmless. |

### Restoring from a backup

Before every turn, agy-bridge saves your uncommitted work to
`~/.agy-bridge/backup/<session>/turn-NNN/`. It keeps the last five turns of each session.
The backup holds:

- `tracked.patch`: staged and unstaged changes to tracked files, as a diff against `HEAD`;
- `untracked/`: copies of untracked files that aren't ignored, and of newly added
  (staged) files, up to 10 MB each and 100 MB in total;
- `manifest.json`: the `HEAD` commit, the branch, and what was copied or skipped.

When a turn changes project files or git state, the result's `backup` note includes the
exact restore commands for that turn. Ask Claude to restore it, or do it yourself from the
project folder. Skip a line when its file or folder isn't in the backup (there was nothing
of that kind to save):

```bash
git checkout <head> -- .
git apply --binary ~/.agy-bridge/backup/<session>/turn-NNN/tracked.patch
cp -R ~/.agy-bridge/backup/<session>/turn-NNN/untracked/. .
```

Everything comes back unstaged.

## Sessions

A session is one AGY conversation. Sessions are stored in `~/.agy-bridge/sessions.json`
and outlive Claude Code.

- **Continue later**: "Resume the AGY review of this project." Claude lists the project's
  sessions and continues the one you mean. AGY remembers the whole conversation.
- **List them**: "Show my AGY sessions."
- **End one**: Claude ends a session when the review is done. Its AGY process stops, but
  the session can still be resumed.
- **Delete one**: "End the AGY session and forget it." This removes the session's record,
  scratch folder, backups and log.
- **Old sessions**: after 30 days unused, a session's scratch folder and backups are
  removed to save space. The session itself stays, and can still be resumed.

Only one Claude Code window can drive a session at a time. If another window is using it,
the tool says so, and you can continue in that window or start a new session.

## Design reviews

`design-reviewer` reviews a design before it is built: a design doc, an ADR, a technical
plan, or a proposed change to the system's structure. Ask for it by name, or just ask
for an AGY review of a design:

- "Ask the AGY design reviewer about docs/design/sync.md."
- "Before we build this, get an AGY design review of the plan."

It works as an outside architect, and it is a discussion rather than a fix loop:

- It reads the design and the current project, then asks about goals, constraints and
  priorities before judging. Expect 2 to 4 questions per turn and several rounds.
- It reviews through ten lenses, using those that fit: problem and drivers, structure,
  data, failure, operations, security and privacy, change over time, scale and cost,
  people and teams, and AI features.
- It questions choices and offers alternatives with their trade-offs, but doesn't push:
  a reasoned answer settles a point.
- It never edits the design. Claude updates the document, and brings you the decisions
  only you can make, such as priorities, budget or team plans.

The lenses are in `~/.gemini/config/skills/architecture-review/references/principles.md`.
Edit them to suit your team.

## Brainstorming and planning

`thinking-partner` is for thinking before you start, about any kind of work: code, a
talk, a product idea, a decision, a piece of writing. It is also a reviewer for finished
work that isn't code or a system design.

- "Before we start, brainstorm with AGY how to structure the onboarding guide."
- "Ask AGY's thinking partner to help me choose between these three names."
- "Have AGY's thinking partner review the launch email draft."
- Add "go wild" for bold, unconventional ideas.

How it works:

- **It picks a technique for the moment**, and says which and why. Examples: Socratic
  questions when the problem is vague; borrowing from other fields when the ideas are
  too similar; a pre-mortem before committing to a plan; a red team when reviewing.
  The full list is in
  `~/.gemini/config/skills/thinking-techniques/references/techniques.md`.
- **It guards against assumptions.** For every important claim, it asks Claude where it
  came from: you said it, evidence shows it, or Claude inferred it. Inferred claims are
  kept apart as assumptions, and the ones only you can confirm come to you.
- **It answers in a brainstorm format:**
  - the problem as it now understands it;
  - the assumptions and their sources;
  - real options, each with what it gains and costs;
  - a recommendation and a next step.
- **It ends when a direction is clear** (`ready`). Claude then brings you the options
  and recommendation to choose from. A brainstorm doesn't decide for you.
- **After the work is done, Claude can ask the same session to review it.** AGY still
  remembers the plan and the reasons behind it.

## Other kinds of review

You can add your own agents, for example a reviewer for prompts or infrastructure
config. See [Writing your own agents](writing-agents.md). Claude picks an agent by name
and purpose from those installed, and asks you if none fits.

## The tools

Claude calls these; you rarely need the details.

| Tool | Purpose |
|---|---|
| `agy_list_agents(refresh_models?)` | Installed agents, model slugs, effort levels, AGY version. |
| `agy_start(agent, cwd, message, model?, effort?, format?, schema?, wait_seconds?)` | Open a session and send the first message. `cwd` is the absolute project (or working) folder. `format` is `review` (default) or `brainstorm`; `schema` is a custom answer format instead. |
| `agy_say(session_id, message, model?, effort?, format?, wait_seconds?)` | Send the next message. Resumes a stopped session. Changing model, effort or format restarts AGY on the same conversation. |
| `agy_wait(session_id, wait_seconds?)` | Keep waiting for a turn that returned `RUNNING`. |
| `agy_status(session_id)` | Idle or working, the turn number, elapsed time, last steps. |
| `agy_sessions(cwd?, limit?)` | Stored sessions, most recent first. |
| `agy_resume(session_id? \| conversation_id?, agent?, cwd?)` | Start a stored session's process ahead of time. It can also adopt an AGY conversation that agy-bridge didn't start. |
| `agy_end(session_id, forget?)` | Stop the AGY process; with `forget`, also delete the session. |

`wait_seconds` defaults to 600.
