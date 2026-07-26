# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v` — `gh` does this automatically when run inside a clone.

## Pull requests as a triage surface

**PRs as a request surface: no.**

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Runtime task bridge

GitHub Issues remain the planning and acceptance layer;
`storage/next_tasks.json` remains the only runtime pending queue.  A materialized
runtime task links the two with optional canonical `issue_ref="#<number>"`:

- create through `uv run volpred ops assign --issue-ref '#37' ...` or the
  `volpred.ops.next_tasks` canonical ingress;
- a successful local claim best-effort adds the current GitHub user as assignee;
  malformed refs or unavailable `gh` are reported but never roll back the local
  claim;
- successful task completion writes an `issue_close_pending` receipt; it does
  **not** close the issue against the pre-commit HEAD;
- the exact-path Git writer or PHASE-Z closes the issue only after obtaining the
  real commit SHA, then writes `issue_closed_commit` back to the same task;
- close replay requires the task/commit marker already present in GitHub.  A
  foreign manual close is not claimed as runtime completion.

This bridge never appends a second task to compensate for GitHub failure and
never reopens legacy admission in direct-execution mode.  Non-interactive shells
may omit Homebrew from `PATH`; the implementation checks configured `GH_BIN`,
normal `PATH`, then `/opt/homebrew/bin/gh`.

## Wayfinding operations

Used by `/wayfinder`. The map is a single issue with child issues as tickets.

- **Map**: an issue labelled `wayfinder:map`.
- **Child ticket**: a GitHub sub-issue linked to the map. Fall back to a task list and `Part of #<map>` when sub-issues are unavailable.
- **Blocking**: use GitHub native issue dependencies. Fall back to a `Blocked by: #<n>` line when dependencies are unavailable.
- **Frontier query**: choose the first unblocked, unassigned open child in map order.
- **Claim**: `gh issue edit <n> --add-assignee @me`.
- **Resolve**: comment with the answer, close the issue, then add its context pointer to the map.
