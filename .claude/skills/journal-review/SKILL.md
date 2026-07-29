---
name: journal-review
description: >
  Read-only, journal-specific fit and compliance review for a current paper
  candidate. Use to compare venues, verify current author instructions, audit a
  submission package, and produce a gate report. It does not edit the paper,
  submit externally, or change pipeline state.
context: fork
---

# Journal Review

This is a **read-only journal gate**. It may recommend a target and package
changes, but all prose edits belong to the main-thread `paper-update` workflow
and all progression belongs to `paper-submission-pipeline`.

## Preconditions

1. Identify the paper and current candidate hashes.
2. Read the 11-stage pipeline model through:

   ```bash
   uv run python scripts/paper_pipeline_check.py
   ```

3. Run the formal gate at `multi_round_review` or later. A venue comparison at
   `draft`, `revision`, or `compliance_scrub` is `ADVISORY`, not a passing
   submission gate.
4. Load the relevant local profile at `references/<abbrev>.md` when present.
   Treat it as a checklist, not current authority.

## Current-rule verification

For each candidate journal, verify against official journal/publisher pages:

- aims, scope, article type, and recent topical fit;
- word/page/abstract/keyword limits;
- manuscript, title-page, anonymization, data/code, disclosure, and supplement
  requirements;
- reference and figure/table rules;
- fees, open-access choices, transfer policies, and submission-system steps.

Record every official URL and access timestamp. If a material rule cannot be
verified, return `BLOCKED`; do not silently rely on an old local profile.

## Review procedure

1. Compare venue fit using the paper's actual contribution, methods, evidence,
   and likely readership. Do not rank by prestige alone.
2. Audit the current candidate and package against the verified rules.
3. Check substance: contribution clarity, identification, economic relevance,
   robustness, limitations, and fit with recent articles.
4. Check compliance: author metadata, anonymization, acknowledgements,
   declarations, data/code statements, AI/LLM wording where prohibited, and
   all required files.
5. Cross-check that the latest `citation-verifier` and
   `latex-academic-reviewer` reports cover the same candidate hashes.

## Freshness and verdict

The report must record:

- candidate manuscript/PDF hashes;
- target journal and article type;
- official URLs with access timestamps;
- local profile version/date, if used;
- upstream review report hashes and verdicts;
- `PASS`, `FAIL`, `BLOCKED`, or `ADVISORY`.

The report becomes stale when the candidate changes, the target/article type
changes, an official instruction changes, or an upstream report becomes stale.
A stale journal report cannot satisfy a pipeline gate.

## Output

Write a concise Markdown report containing:

1. recommended venue and alternatives with evidence;
2. current-rule checklist and sources;
3. substantive fit findings;
4. package/compliance findings;
5. blockers requiring main-thread revision;
6. freshness metadata and final verdict.

Use templates under `templates/` when helpful.

## Approval boundary

Venue choice and submission timing are routine main-thread decisions under the
project's standing authorization. Stop for the user only when an external
system requires login/MFA, payment, a legal declaration, author signature, or
another non-delegable attestation. This skill itself performs no external
submission.
