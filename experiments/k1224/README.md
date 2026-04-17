# K1224 — Paper 1 body_v4 Integration Edit Guide

## Purpose

Consolidate the outputs of **K1209** (commit `2ca9f2f8`, Paper 1 Batch 2
markdown draft, 8 items covering Table 3/4/6/7/10/11/12/C3 errata +
`experiments.md`), **K1206** (commit `d8bdb205`, Table 6 forensic sensitivity
confirming 3-cell errata), **K1198** (Tables 10/11/12/C3 pre-K rescan,
3/6 matched), **K1188** (Table 8 canonical 15/15 matched), **K1187**
(Table 7 6/20 matched), and **K1185** (Table 4 3/4 matched) into a
**single, priority-ordered main-thread execution plan** (.md form, not
`.tex`).

CLAUDE.md rule: worktree / background agents must NOT edit `body.tex`.
K1224 therefore produces only markdown + JSON artefacts; the main
thread performs the actual `body_v4.tex` edits.

Parallel to **K1223** (Paper 6 body_v2 integration edit guide).

## Source material

| Source experiment | Role |
|-------------------|------|
| K1209 (commit `2ca9f2f8`) | Paper 1 Batch 2 rewrite draft (8 items, 3574 words, 1 dropped) |
| K1206 (commit `d8bdb205`) | Table 6 forensic sensitivity: A/B/C variants all fail to reconstruct Paper 1 values → `errata_recommended` |
| K1198 | Tables 10/11/12 + §4.2.3 (C3) pre-K rebuild: 3/6 matched |
| K1188 | Table 8 window robustness 15/15 matched (STILL_NO_SOURCE resolved) |
| K1187 | Table 7 cross-asset: 6/20 matched; per-asset period undisclosed |
| K1186 | Table 6 canonical replication: 2/5 matched, 3/5 diverged |
| K1185 | Table 4 VaR attribution: 3/4 matched (Normal 33→30 yfinance revision) |
| K903  | Rolling-window QLIKE (matches Table 8 within 0.003) |

Baseline paper commit: `0a442356` (Paper 1 body_v3 Batch 1 — Kupiec p
2-decimal + GLD γ forensic + γ_HM Sec 5.4 disambiguation).

## Artefact inventory

1. `README.md` — this file.
2. `k1224_edit_guide.md` — the integrated edit guide (7 items, priority-ordered,
   with canonical numbers, footnote text, and rollback plan).
3. `k1224_edit_items.json` — structured per-item tracker for programmatic
   consumption (main-thread scripts, checklist UIs).

## Estimated execution time

- **Sequential, all items**: 60–90 min (body_v4.tex create + 5 footnotes
  + Table 6 cell updates + new `experiments.md` + compile + paper-update
  CLI + commit).
- **Per-item times** are recorded in `k1224_edit_items.json` under
  `items[*].estimated_minutes`.

## Seed / worktree discipline

- Fixed seed: `42` (inherited; K1224 does no random computation, so seed
  is recorded for provenance only).
- Worktree scope: **outputs only under `experiments/k1224/`**.
- No edits to: `paper/leverage-direction/body_v3.tex`, `paper/leverage-direction/tables.tex`,
  shared JSON, Supabase mirror, `storage/memory/*`.

## Success criteria

- `k1224_edit_guide.md` lists 7 items in priority order with canonical
  numbers verbatim from K1206 / K1198 / K1188 / K1187 / K1185 / K903
  JSONs and footnote text copy-paste-ready for `body_v4.tex`.
- `k1224_edit_items.json` provides structured records matching the
  guide, including `source_experiment`, `action`, `target_file`,
  `line_approx`, `estimated_minutes`, and status.
- Main thread can follow the guide top-to-bottom without re-reading the
  K1209 / K1206 / K1198 / K1188 / K1187 / K1185 source files.
- Item 8 (γ_HM Sec 4.7 second disambiguation) formally DROPPED; Batch 1
  commit `0a442356` already covers all three γ_HM values in Sec 5.4.

## Next steps (main thread)

1. Read `k1224_edit_guide.md` once.
2. Create `paper/leverage-direction/body_v4.tex` (copy `body_v3.tex`).
3. Execute items 1–7 in priority order (Items 1, 3, 4 footnote inserts
   first; Item 2 Table 6 3-cell update; Items 5, 7 final footnotes;
   Item 6 new `experiments.md` file).
4. Run `xelatex main_v4.tex` twice (update `main_v3.tex` → `main_v4.tex`
   `\input{body_v4}` wrapper if needed).
5. Run `uv run volpred ops paper-update --paper-id leverage-direction`.
6. Commit with message template in the guide.
