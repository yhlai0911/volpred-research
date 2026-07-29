---
name: paper-review-cycle
description: >
  Orchestrate and archive a read-only review round for the current paper
  candidate: reproducibility preflight, LaTeX review, citation verification,
  and optional journal review. It does not revise the paper or own pipeline
  state.
user-invocable: true
---

# Paper Review Cycle

This skill runs reviewers and records evidence. Main-thread revision belongs to
`paper-update`; the unique stage model and any transition belong to
`paper-submission-pipeline`.

Before use, read
`../paper-update/references/reproduce-gate-rules.md`.

## 1. Identify the candidate

- Resolve the paper entry point, included sources, bibliography, figures, and
  compiled PDF.
- Record SHA-256 for every reviewed input.
- Read current pipeline state with:

  ```bash
  uv run python scripts/paper_pipeline_check.py
  ```

This checker is a read model, not a transition writer.

## 2. Reproducibility preflight

Build a manifest from every experiment/result used by a headline claim, table,
or figure. For each experiment, run the existing checker using its verified
interface:

```bash
uv run python scripts/reproduce_check.py run --experiment <K-id> --timeout <seconds>
```

Also verify source binding: manuscript number, result artifact, experiment,
period, sample, code/spec identity, and figure/table source must agree. Abort
the review with `BLOCKED` if a required experiment fails, is missing, or the
candidate cites a different snapshot.

## 3. Run independent reviews

Run these read-only reviewers in parallel on the **same hashes**:

- `latex-academic-reviewer`
- `citation-verifier`

Run `journal-review` as well when a target journal/article type is selected or
when testing a submission gate. Review agents must not edit `.tex`, compile a
replacement PDF, or update metadata/state.

## 4. Archive the round

Create the next immutable directory under the paper's existing
`review_history/v<n>/` convention and save:

- LaTeX review report;
- citation report;
- journal report, when run;
- reproducibility/source-binding manifest;
- `README.md` round manifest.

The round manifest records candidate hashes, reviewer/report hashes,
timestamps, commands used, verdicts, unresolved findings, and the previous
round. Never overwrite an older round.

## 5. Decide the round result

- `PASS`: reproducibility/source binding pass, LaTeX review has no
  CRITICAL/MAJOR finding, citation review has no MAJOR finding or unresolved
  central source, and any required journal review passes.
- `FAIL`: the candidate is reviewable but has a blocking finding.
- `BLOCKED`: required evidence, source, candidate identity, or official rule
  cannot be verified.

On `FAIL`, give the main thread an ordered revision list for `paper-update`.
After any revision, all reports whose input hashes changed are stale and a new
round is required.

On `PASS`, hand the immutable round evidence to
`paper-submission-pipeline`. Do not advance state here.

## State-write rule

Never edit a tracker or database directly. A transition may be executed only
through an already-existing canonical writer/CLI whose `--help` has been
verified in the current checkout. If no such transition surface exists, the
pipeline remains `BLOCKED` and the main thread must create a
governance/implementation task through the currently canonical task-creation
surface. Do not substitute a queue edit, metadata field, or invented command.
