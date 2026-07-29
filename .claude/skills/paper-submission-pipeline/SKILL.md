---
name: paper-submission-pipeline
description: >
  The sole 11-stage state model and orchestrator for moving a paper from draft
  through arXiv and journal review. Use to read progress, evaluate evidence
  gates, detect stalls, coordinate review/update skills, and request a
  transition through a verified canonical writer. It does not write paper
  prose.
user-invocable: true
---

# Paper Submission Pipeline

This skill is the **only paper-stage authority**. `paper-stage-classifier` is a
lossy compatibility projection and must never make transition decisions.

## Canonical stages

```text
draft
  -> revision
  -> compliance_scrub
  -> multi_round_review
  -> review_converged
  -> arxiv_ready
  -> arxiv_posted
  -> journal_submitted
  -> under_journal_review
  -> accepted | rejected
```

An R&R editorial decision may send `under_journal_review` back to `revision`.
A retarget decision may send `rejected` back to `revision`. Preserve the
editorial receipt as transition evidence.

## Read model

Read current records and stall findings with:

```bash
uv run python scripts/paper_pipeline_check.py
```

Its non-zero exit can mean findings; preserve and inspect its JSON output. This
script is a **reader/stall detector**, not a transition writer.

## Gate evidence

Every gate evaluates one identified candidate. Record manuscript, bibliography,
included-source, figure, and PDF hashes. A receipt from another candidate is
invalid.

Resolve the active public PDF target only from
`config/project_targets.json`; never infer it from an old frontend path.

| Transition | Required current-candidate evidence |
|---|---|
| `draft -> revision` | Narrative decision satisfies the project narrative policy; main thread has an identified revision candidate and evidence map. |
| `revision -> compliance_scrub` | Candidate compiles; every central experiment passes `reproduce_check.py`; manuscript-to-result source binding passes; known revision blockers are closed. |
| `compliance_scrub -> multi_round_review` | Current compliance checker is clean; authorship, disclosure, anonymization, data/code, and forbidden-mention checks pass. |
| `multi_round_review -> review_converged` | Contribution gate passes first; latest `paper-review-cycle` on identical hashes passes, including LaTeX, citation, reproducibility, and target-journal review when a target exists. |
| `review_converged -> arxiv_ready` | Final candidate compiles; reproducibility and compliance are rerun; citation and journal reports are fresh; arXiv package exactly matches the approved hashes. |
| `arxiv_ready -> arxiv_posted` | Upload receipt records arXiv identifier/URL, timestamp, and uploaded-file hash. |
| `arxiv_posted -> journal_submitted` | Current official journal rules were reverified; package and cover letter match approved hashes; submission receipt is captured. |
| `journal_submitted -> under_journal_review` | Journal acknowledgement or submission-system status confirms editorial review. |
| `under_journal_review -> accepted/rejected` | Editorial decision receipt identifies paper, journal, date, and decision. |

The **contribution gate** asks: what is learned that was not already known, why
it matters economically/theoretically, and why it is more than a method
demonstration. A merely mechanical or incremental exercise cannot converge.

Only a candidate that has passed `review_converged` may move toward arXiv.
If an official disclosure requirement conflicts with the current compliance
checker, the gate is `BLOCKED`; do not suppress a truthful required disclosure
or bypass the checker.

## Freshness rules

- Reproducibility evidence must identify each experiment, result/spec/code
  identity, command, timestamp, and verdict, plus the manuscript locations it
  supports.
- Citation evidence must contain current manuscript/bibliography hashes and
  authoritative-source access timestamps.
- Journal evidence must contain current candidate hashes, target/article type,
  and access timestamps for official instructions.
- LaTeX/compliance evidence must cover the same candidate.

Any relevant candidate, evidence artifact, target journal, article type, or
official rule change invalidates the affected gate. Never carry a stale `PASS`
forward.

## Orchestration loop

1. **Observe** the read model and identify the earliest unmet gate.
2. **Plan** one bounded action: main-thread revision via `paper-update`,
   compliance audit, `paper-review-cycle`, package preparation, or external
   submission.
3. **Execute** only that action and capture immutable receipts.
4. **Check** the gate against the current hashes.
5. **Transition** only through the canonical mutation contract below.
6. Re-read the model and verify that the persisted stage and evidence are
   exactly what was requested.

An error-free command is not proof of transition; the read-back is mandatory.

## Canonical mutation contract

Before any transition, discover the installed ops surface and inspect the
candidate command's `--help`. Use it only if it explicitly supports atomic
paper-pipeline transitions, allowed-edge validation, evidence attachment, and
read-back.

As of this skill revision, `scripts/paper_pipeline_check.py` is read-only and no
verified transition writer is documented. Therefore a satisfied gate may be
reported, but persistence remains `BLOCKED` until such a writer exists.

When the transition surface is absent:

1. leave the canonical stage unchanged;
2. record the gate evidence and the blocker in the run report;
3. check the local control-plane tasks for an existing equivalent:

   ```bash
   uv run volpred ops tasks --status queued --limit 100
   ```

4. if absent, create one through the verified local control-plane writer:

   ```bash
   uv run volpred ops assign \
     --title "Implement canonical paper-pipeline transition writer" \
     --description "Add an atomic CLI with allowed-edge and evidence validation, read-back, tests, and documented --help; migrate no state by hand." \
     --source agent --task-family code --priority 20 \
     --preferred-agent claude --approval-mode auto \
     --risk-level safe --public-effect none \
     --created-by paper-submission-pipeline
   ```

Never edit tracker storage or database rows by hand, reuse public paper
metadata as pipeline state, or invent a command-line flag.
`paper-upsert --status` is only a coarse website projection.

## Approval boundary

- The main thread may choose methods, journal target, routine revisions, and
  submission timing under the standing authorization.
- A new paper narrative/body rewrite still obeys the project's separate
  user-confirmed narrative-decision gate.
- Stop for login/MFA, payment, legal declaration, author signature, or another
  non-delegable attestation. Withdrawal or retraction also requires explicit
  user direction.
- On a stop, preserve the prepared package and exact next action; do not mark
  the external stage complete without its receipt.
