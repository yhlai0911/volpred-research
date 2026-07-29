---
name: paper-stage-classifier
description: >
  Compatibility projection for the canonical 11-stage paper-submission
  pipeline. Use only when an older caller asks for a coarse paper status or
  "paper stage." It does not define gates, run reviews, or transition papers.
user-invocable: true
---

# Paper Stage Classifier — Compatibility Alias

This skill is a retired state-machine surface. The only authoritative stage
model and orchestrator is `paper-submission-pipeline`.

## Read

Read the current tracker through the existing read model:

```bash
uv run python scripts/paper_pipeline_check.py
```

Do not infer stage from page count, review age, website status, or a previous
report. Do not write the tracker.

## Coarse projection

For legacy UI/reporting only, project the canonical stage as follows:

| Canonical pipeline stage | Coarse public status |
|---|---|
| `draft`, `revision`, `compliance_scrub`, `multi_round_review` | `working` |
| `review_converged`, `arxiv_ready` | `ready_for_submission` |
| `arxiv_posted`, `journal_submitted`, `under_journal_review` | `submitted` |
| `accepted` | `accepted` |
| `rejected` | `working` |

This mapping is lossy and never feeds back into the canonical stage.

When a public-status projection genuinely needs persistence, first verify the
installed interface:

```bash
uv run volpred ops paper-upsert --help
```

Then use only its supported metadata field:

```bash
uv run volpred ops paper-upsert --paper-id <id> --status <coarse-status>
uv run volpred ops paper-list
```

This command updates a public metadata projection; it is **not** a pipeline
transition. Treat the write as failed unless the read-back shows the requested
paper and status.

## Transition requests

Forward every transition request to `paper-submission-pipeline`. A transition
may run only through an already-existing canonical writer/CLI verified by
`--help`. If none exists, return `BLOCKED` and create a
governance/implementation task through the currently canonical task-creation
surface. Never mutate tracker/database records by hand, invent a flag, or
repurpose the coarse `status` field as the 11-stage state.
