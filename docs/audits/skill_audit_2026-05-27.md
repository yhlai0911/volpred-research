# Skill Audit — 2026-05-27

Task: `governance_skill_audit_20260527`

Scope: audit the 8 `.claude/skills/` directories whose `SKILL.md` or parent dir had been untouched for >30 days during queue generation.

## Verdict

- `admin-ops`: kept, refreshed
  - Replaced legacy CLI examples `uv run python -m volpred.cli ops ...` with canonical `uv run volpred ops ...`
  - Added `references/scheduling.md` to the progressive-load index so schedule drift work has an explicit entrypoint
- `agent-result-verification`: kept, refreshed
  - Replaced legacy `experiments/K{ID}/k{id}_results.json` example with lowercase `experiments/<experiment_id>/<experiment_id>_results.json`
- `citation-verifier`: kept, no content change
  - Reference links valid; no stale path/CLI examples found
- `finance-paper-quality`: kept, no content change
  - Scope and handoff boundaries still match current paper workflow
- `latex-academic-reviewer`: kept, no content change
  - No dead references or legacy CLI/path examples detected
- `publication-candidates`: kept, no content change
  - Event/control-plane notes still align with current scheduling model
- `worktree-merge-verification`: kept, refreshed
  - Replaced legacy uppercase experiment placeholders with lowercase repo path examples
- `member-questions`: kept, refreshed
  - Replaced legacy CLI examples with `uv run volpred ops ...`
  - Updated workflow to reflect current `member_qa` immediate-published flow
  - Added explicit `question-finish` close-out step

## Related Refreshes Outside the Original 8

- `.claude/skills/feed-publisher/SKILL.md`
  - Replaced remaining legacy ops CLI examples
- `.claude/skills/autonomous-research/references/publishing-guide.md`
  - Replaced remaining legacy ops CLI examples
- `.claude/skills/admin-ops/references/platform-api-manual.md`
- `.claude/skills/admin-ops/references/session-cron-workflows.md`
- `.claude/skills/admin-ops/references/surfaces.md`
- `.claude/skills/member-questions/references/evaluation-guide.md`
  - Synced references with the same canonical CLI / member_qa flow updates

## Process Fix

`scripts/check_skills_complete.sh` now audits more than file existence:

- missing `SKILL.md`
- incomplete frontmatter
- dead `references/*.md` links
- legacy ops CLI drift (`uv run python -m volpred.cli ops`)
- legacy uppercase experiment path drift (`experiments/K{ID}`)
- stale `SKILL.md` list by age threshold (`--stale-days`, default 30)

Validation after patch:

```bash
env -i PATH=/bin:/usr/bin:/usr/local/bin HOME=$HOME /bin/bash scripts/check_skills_complete.sh
env -i PATH=/bin:/usr/bin:/usr/local/bin HOME=$HOME /bin/bash scripts/check_skills_complete.sh --json
```

Current result:

- `workflow_drift = []`
- `dead_references = []`
- remaining stale-by-age only: `citation-verifier`, `finance-paper-quality`, `latex-academic-reviewer`, `publication-candidates`

These four remain old by mtime, but this audit found no broken paths or obsolete workflow snippets, so they were retained unchanged.
