# Security

## What agy-bridge does with your code

agy-bridge runs the AGY CLI on your machine, signed in as you. AGY reads your project and
sends what it reads to Google's models, or to whichever provider serves the model you
choose, under your Antigravity plan's terms. agy-bridge itself sends nothing anywhere
else. Transcripts are kept on disk only if you turn logging on.

## What AGY may do

A reviewer that can run tests can, in principle, run anything. agy-bridge accepts that
trade-off and limits the damage as follows:

| Risk | What agy-bridge does |
|---|---|
| AGY edits the project with its file tools | Those tools are allowed only in the session's scratch folder. Any other write is denied and reported. |
| AGY edits the project through a shell command, or a test writes files | The agent's rules forbid it. The bridge snapshots the project before and after each turn and reports every change to Claude, which tells you. |
| Uncommitted work is lost, e.g. by `git reset --hard` or `git clean` | Before each turn the bridge backs up tracked changes as a patch, plus copies of untracked and newly added files. When a turn changes the project, its result carries a restore recipe. |
| AGY approves its own risky action | agy-bridge never passes `--dangerously-skip-permissions`. Anything the session's settings don't allow is denied. |
| Text in the reviewed code tries to steer AGY or Claude (prompt injection) | The Claude skill treats AGY's output as advice to verify, never as instructions. This reduces the risk; it can't remove it. |

What this does **not** protect against:

- shell commands that affect things outside the project, such as the network, other
  folders, or your accounts;
- changes to ignored files, or edits that keep a file's size and mtime;
- untracked files over 10 MB, or beyond 100 MB per turn, which are not backed up.

For code where that matters:

- commit or stash your work before a review;
- review inside a container or a disposable checkout;
- or give the agent a narrower `tools:` list. Without `run_command`, it can't run
  commands at all.

## Use at your own risk

agy-bridge is provided **"as is", without warranty of any kind**, under the
[MIT License](LICENSE). It runs an AI agent that can execute commands on your machine.
By installing or using it, you accept full responsibility for:

- what it does to your files, systems and accounts;
- the code and data AGY reads and sends to model providers;
- any cost, quota use, data loss or damage that results.

The authors and contributors are not liable for any of it. There is no support
commitment, no response time, and no promise that any problem will be fixed.

If you find a security problem, you are welcome to open an issue or a pull request.
