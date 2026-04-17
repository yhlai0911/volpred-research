# K1223 — Paper 6 body_v2 Integration Edit Guide

## Purpose

Consolidate the outputs of **K1218** (commit `581be90f`, Paper 6 Appendix A
markdown draft, 930 words, five subsections A.1–A.5) and **K1221**
(commit `fc00c7aa`, Paper 6 pre-submission audit with 3 blockers + 3
warnings) into a **single, priority-ordered main-thread execution plan**
for the human (`.md` form, not `.tex`).

CLAUDE.md rule: worktree / background agents must NOT edit `main.tex`.
K1223 therefore produces only markdown + JSON artefacts; the main
thread performs the actual LaTeX edits.

## Source material

| Source experiment | Commit | Role |
|-------------------|--------|------|
| K1218 | `581be90f` | Appendix A markdown draft (A.1 Motivation, A.2 Methodology, A.3 Replication results, A.4 Interpretation, A.5 Reproducibility package) |
| K1221 | `fc00c7aa` | Pre-submission audit: 3 blockers (B1 Table 1 date, B2 K1218 appendix integration, B3 paper-update CLI) + 3 warnings (W1 data/README stub, W2 TAIFEX data-on-request clause, W3 reproduce.py pin) |

Both experiments audited `paper/prg-periodic-garch/main.tex` at commit
`7d35418b` (Eq.(5)–(6) errata defence; v3 PDF in place).

## Artefact inventory

1. `README.md` — this file.
2. `k1223_edit_guide.md` — the integrated edit guide (6 items, priority-ordered,
   with LaTeX diffs and rollback plan).
3. `k1223_edit_items.json` — structured per-item tracker for programmatic
   consumption (main-thread scripts, checklist UIs).

## Estimated execution time

- **Blockers only (B1+B2+B3)**: 65–80 min
- **With polish (W1+W2+W3)**: 80–120 min total
- **Per-item times** are recorded in `k1223_edit_items.json` under
  `items[*].estimated_minutes`.

## Seed / worktree discipline

- Fixed seed: `42` (inherited; K1223 does no random computation, so seed
  is recorded for provenance only).
- Worktree scope: **outputs only under `experiments/k1223/`**.
- No edits to: `paper/prg-periodic-garch/main.tex`, shared JSON, Supabase
  mirror, `storage/memory/*`.

## Success criteria

- `k1223_edit_guide.md` lists 6 items (B1, B2, B3, W1, W2, W3) in
  priority order with exact `main.tex` line numbers, LaTeX diffs, and
  reasons drawn verbatim from K1218 / K1221.
- `k1223_edit_items.json` provides structured records matching the
  guide, including `source_experiment`, `severity`, `file`,
  `line`, `estimated_minutes`, and `rollback_commit`.
- Main thread can follow the guide top-to-bottom without re-reading the
  K1218 or K1221 source files.

## Next steps (main thread)

1. Read `k1223_edit_guide.md` once.
2. Execute items in priority order (B1 → B2 → W1/W2/W3 → B3).
3. Run `xelatex main.tex` twice.
4. Run `uv run volpred ops paper-update --paper-id paper-6`.
5. Commit; re-run K1221 to verify readiness = READY.
