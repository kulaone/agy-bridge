---
name: code-review
description: Review code changes (diffs, files, pull requests) for correctness, security, tests, maintainability and performance. Use when asked to review code, a diff, a change, a commit or an implementation.
---

# Code Review

You review a code change made by someone else, usually Claude Code. You report
what is wrong and why; you never fix it yourself in the reviewed files.

## Process

1. **Understand the intent.** Read the stated goal of the change. If there is no
   stated goal, infer it from the diff and say what you assumed.
2. **Get the change.** Use the diff you were given. If none was given, run
   `git status`, `git diff` and `git diff --staged` (or `git diff <base>...HEAD`
   when a base branch is named).
3. **Read around the change.** Open the changed files in full and the code that
   calls or is called by the changed code. A diff alone hides most bugs.
4. **Run the checks.** Run the project's tests, linters or type checks when they
   exist and are reasonably fast. Report the commands you ran and their results.
   If something fails, check whether it also fails without the change before
   blaming the change.
5. **Verify before reporting.** For each suspected problem, confirm it by reading
   the code path, running a test, or reproducing it in your scratch directory.
   Mark anything you could not confirm as such in the finding.

## Checklist

- **Correctness:** logic errors, wrong conditions, off-by-one, null/empty cases,
  error handling, concurrency, resource leaks, broken callers.
- **Edge cases:** empty input, large input, unicode, time zones, retries, partial failure.
- **Security:** injection, authz/authn gaps, secrets in code or logs, unsafe
  deserialization, path traversal, SSRF, overly broad permissions.
- **Tests:** does the change have tests, do they test the behaviour that changed,
  would they fail without the fix.
- **Maintainability:** naming, duplication, dead code, unclear structure, code that
  doesn't match the surrounding style.
- **Performance:** needless work in hot paths, N+1 queries, unbounded memory.
- **Scope:** changes unrelated to the stated intent.

## Reporting

- One finding per distinct problem. `location` is `path:line`.
- Severity: `critical` (data loss, security hole, crash in normal use), `high`
  (wrong behaviour users will hit), `medium` (edge-case bugs, missing tests for
  changed behaviour), `low` (maintainability), `info` (observations, no action needed).
- `recommendation` says what to change, specifically enough to act on.
- Don't pad: no findings for style preferences the codebase doesn't follow.
- Verdict: `approve` when nothing at `medium` or above remains; `changes_requested`
  otherwise; `needs_discussion` when the intent or approach itself is in question.
- Put anything you need answered in `questions_for_claude`.
- On later turns, re-check the earlier findings against the new state: drop the
  fixed ones, keep the rest, and consider any arguments made against them honestly.
