# Token report top-category drilldown review

- Task: `token_report_top_category_drilldown_20260802`
- Scope: weekly/daily JSON and Markdown reports plus the owned Email HTML/plain-text report.
- Commits: pending final writer-lock commit.

## Verification

- Matt Spec review: **PASS**.
- Standards review: **PASS**.
- Regression: `66 passed` across token usage, token-report email, and ops summary tests.
- Static gates: Ruff F/E9 and `git diff --check` passed.
- Graphify: root and active-frontend graphs are fresh after AST update.
- Live readback: regenerated `weekly_2026-07-26` and `daily_2026-08-01`; both contain top-two provider/model/session breakdowns and the attribution caveats.

## Result

The top two billable categories now expose provider, model, session, and category-specific evidence detail in JSON, Markdown/CLI, Email HTML, and Email plain text. `unclassified` explicitly states that Codex `token_count` has no authoritative task metadata and is not inferred. Bash-family billable tokens are deterministically allocated across distinct evidence families with a conservation test and an overlap/allocation caveat. Text-reason detail is explicitly labelled as keyword-heuristic, non-authoritative attribution.

Live weekly top two: `unclassified` Codex `221,788,662` billable (`82.3%`) and `bash_other` Claude `28,711,166` billable (`10.7%`).

Status: `root_cause_fixed_and_verified`.
