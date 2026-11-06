# Writing your own agents

agy-bridge works with any AGY agent, not only the `code-reviewer` and `design-reviewer`
it installs. You might add, for example:

- a reviewer for docs, prompts or infrastructure config;
- a security reviewer with its own checklist.

An agent is a Markdown file with YAML frontmatter. It usually comes with an AGY skill: a
folder holding a `SKILL.md` with the detailed method. The agent says who the reviewer is
and what it may do; the skill says how to review.

## Where they go

| Scope | Agents | Skills |
|---|---|---|
| All projects | `~/.gemini/config/agents/<name>.md` | `~/.gemini/config/skills/<skill>/SKILL.md` |
| One project | `<project>/.agents/agents/<name>.md` | `<project>/.agents/skills/<skill>/SKILL.md` |

An agent can also be a folder, `<name>/agent.md`. AGY uses the nearest agent with a given
name: it looks in the project folder and each folder above it, then in the global folder.
Run `agy agents` to check that AGY sees yours.

## A starting point

Copy the installed `code-reviewer.md` and change it. Here is a docs reviewer:

```markdown
---
name: docs-reviewer
description: Reviews documentation for accuracy against the code, clarity and completeness. Never edits the docs it reviews.
tools: [view_file, list_dir, grep_search, find_by_name, read_url_content,
        run_command, command_status, write_to_file, finish]
mainAgent: true
subagent: true
model: inherit
skills:
  - /Users/you/.gemini/config/skills/docs-review
---
# Role

You are a technical editor reviewing documentation written by Claude Code, another AI
agent. Follow the docs-review skill.

## Ground rules

- Claude made the work and will reply to you. Put questions in `questions_for_claude`.
- Check every command, path and option the docs mention against the code. Run commands
  when it is safe to.
- **Never change any file in the project.** Experiment only in your scratch directory,
  which is named in the first message.
- Answer in the JSON schema you were given.
```

Then write `~/.gemini/config/skills/docs-review/SKILL.md`, following the shape of the
installed `code-review` skill:

- a `name` and `description` in its frontmatter;
- the review process, step by step;
- a checklist;
- how to grade severity and pick the verdict.

## The rules that matter

### List `finish` in `tools`
AGY sends its structured answer through `finish`. Without it there is no review, and
agy-bridge refuses to start the agent.

### Use tool names your AGY actually has
An agent that lists an unknown tool hangs in AGY. agy-bridge checks each agent's list
against AGY's real tools before each new session and refuses to start it if a name is
wrong. After your first review, the real names are in `~/.agy-bridge/cache.json` under
`tools`.

### Skill paths must be absolute
AGY doesn't expand `~` or resolve relative paths here. For a project agent, give the
absolute path of `<project>/.agents/skills/<skill>`.

### File-writing tools only work in the scratch folder
agy-bridge allows `write_to_file` and similar tools only inside the session's scratch
folder, and AGY reports any other write as denied. Shell commands are not limited this
way, so the ground rules must say plainly that the project is off limits.

### Write for Claude, not a person
The other side of the conversation is Claude Code. Tell the agent so, and tell it to
put questions in `questions_for_claude`. Claude passes on to you anything only you can
answer.

### Leave the model to the caller
With `model: inherit`, the model chosen through agy-bridge applies, or AGY's default if
none was chosen. A fixed model in the agent file would take that choice away from you
and from Claude.

## The answer format

Every agent answers in the review schema unless the caller passes another:

| Field | Contents |
|---|---|
| `verdict` | `approve`, `changes_requested` or `needs_discussion`. |
| `summary` | A few sentences. |
| `findings` | Each has `severity`, `category`, `location`, `issue` and `recommendation`. |
| `questions_for_claude` | What the agent wants answered. |

This suits most reviews, not only code. For a discussion-style agent, have it use
`needs_discussion` and put its questions in `questions_for_claude`, as the shipped
`design-reviewer` does. The Claude skill treats that as a conversation, not a fix loop:
Claude answers, pushes back, and brings in you for decisions only you can make.

## Telling Claude about it

You don't need to change the Claude skill. Claude lists the installed agents and picks
one by name and purpose. Make the `description` say clearly what the agent is for, or
name it in your request: "Ask the AGY docs-reviewer to check the install guide."

## Sharing an agent

To share an agent with a team, commit it and its skill under the project's `.agents/`
folder. Because AGY needs an absolute skill path, each person changes that path to match
their own checkout, unless everyone keeps the repo at the same path.
