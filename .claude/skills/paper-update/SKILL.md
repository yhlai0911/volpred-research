---
name: paper-update
description: >
  Main-thread-only workflow for evidence-backed manuscript edits, LaTeX
  compilation, and canonical paper synchronization. Use after review findings
  or approved narrative decisions. It does not run independent reviews or
  change pipeline stage.
user-invocable: true
---

# Paper Update

Only the main thread may edit paper `.tex` prose or make methodological and
narrative decisions. Subagents may inspect evidence and propose patches, but
must not write the manuscript.

Read `references/reproduce-gate-rules.md` before changing a paper.
Pipeline context, when needed, is read through
`scripts/paper_pipeline_check.py`; this workflow never transitions it.

## 1. Resolve scope and evidence

1. Identify the stable paper id and current entry point. Use
   `uv run volpred ops paper-list` when metadata is needed.
2. Read the latest immutable review round and separate blocking findings from
   optional polish.
3. Map every changed numerical or causal claim to archived result artifacts.
4. Record current hashes for manuscript, included sources, bibliography,
   figures, and PDF.
5. Preserve the previous version using the paper's established version/archive
   convention. Never overwrite review history.

If evidence is missing or conflicts with the manuscript, stop the affected
claim and report `BLOCKED`; do not repair a published number by hand.

## 2. Reproduce and bind sources

For every experiment supporting a changed central claim, table, or figure, use
the existing checker:

```bash
uv run python scripts/reproduce_check.py run --experiment <K-id> --timeout <seconds>
```

Verify experiment id, result/spec/code identity, input snapshot, period, sample
size, seed, manuscript location, and rendered figure/table source. A runnable
experiment is not enough when the manuscript points to a different snapshot.

## 3. Edit in the main thread

- Apply the smallest coherent source change.
- Keep claims within the reproduced design and retain nulls/limitations.
- Preserve explicit timing/lag conventions and fair baseline definitions.
- Update abstract, body, tables, captions, appendix, and bibliography together
  when one change affects several surfaces.
- Do not let a reviewer agent directly implement `.tex` changes.

All independent review reports become stale when their reviewed hashes change.

## 4. Compile and inspect

Use the paper's checked-in build instructions and available engine; do not
invent a build command. Compile enough passes to resolve references and
bibliography, fail on LaTeX errors, inspect warnings, and visually inspect the
rendered PDF for clipped tables, missing figures, broken references, font
issues, and stale artifacts.

Record the final source and PDF hashes plus build command and timestamp.

## 5. Canonical synchronization

Read `config/project_targets.json` before synchronization. The active frontend
and `paper_public_dir` in that file are the only deployment target; never
hardcode or infer a frontend path.

Verify the installed interface, then use:

```bash
uv run volpred ops paper-update --help
uv run volpred ops paper-update --paper-id <id> --paper-dir paper/<id>
```

This CLI performs metadata/PDF upload and copies to the configured active
frontend target. Do not substitute manual database, storage, or frontend-file
edits.

## 6. Read-back

After synchronization:

1. run `uv run volpred ops paper-list`;
2. resolve the active public PDF path from `config/project_targets.json`;
3. verify local candidate, uploaded object when observable, and active public
   copy have the expected identity;
4. verify page/citation metadata and downstream API/UI acknowledgement when
   available.

No-error execution without this read-back is only `contained`.

## Handoff

- Archive a revision receipt containing changed files, review findings
  addressed, evidence/reproduce receipts, build result, hashes, sync output,
  and read-back result.
- Send the new candidate to `paper-review-cycle`; never reuse reports from the
  old hashes.
- Send gate evidence to `paper-submission-pipeline`. This skill never persists
  a pipeline transition or repurposes public paper status as stage.
- Source-control staging/commit, if requested by the parent workflow, must use
  the repository's canonical `scripts/git_writer_lock.py` command with exact
  paths. This skill never issues bare Git mutation commands.
