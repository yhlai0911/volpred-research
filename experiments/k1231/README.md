# K1231: Paper 8 volatility-absorption K716-K722 Reconstruction Plan

## Purpose

Paper 8 (`paper/volatility-absorption/`) was flagged as **P2 BLOCKER** by the K1229
audit. `reproduce_report.json` reports only **50.7% traceability** (38 matches / 8
mismatches / 29 untraceable out of 75 checks), and listed K716, K718, K719, K720,
K721, K722 as "scripts missing".

This experiment is a **decision-matrix planning document**, not a computation.
For each of K716–K722, K1231 produces a per-experiment recommendation along the
three canonical paths defined by `docs/paper-guide.md` 三方一致 rule:

- **(a) rebuild script** to match the paper body numbers (keep paper, fix script)
- **(b) revise paper body** to match the existing K JSON numbers (keep data, fix paper)
- **(c) errata pending** — explicit disclosure when divergence is tolerated

CLAUDE.md rule: **agent 不寫 body.tex**; this K1231 artifact is Markdown / JSON
only and will feed a main-thread decision.

## Key Finding (updated 2026-04-17)

The K1229 audit report statement "No .py scripts for K716–K722" is **partially
outdated**. Per actual filesystem inspection:

- All 7 K716–K722 folders **already contain** `kNNN.py` scripts (340 / 271 / 303
  / 169 / 251 / 286 / 220 lines), headers labeled **"RECONSTRUCTED from
  paper/volatility-absorption/main_v2.tex (2026-04-17)"**.
- Each folder also has `kNNN_results_reconstructed.json` and a detailed
  `kNNN_reconstruction_diff.md` comparing reconstructed vs original JSON at
  `rtol=0.01, atol=1e-4`.
- The **original** `kNNN_results.json` files were never accompanied by source
  scripts; the diff reports explicitly note "APPROXIMATE" divergences.
- `paper/volatility-absorption/main_v2.tex` contains no `\cite{k716}` style
  references — the paper body cites **canonical numbers** (e.g. SPY slope
  −0.00028, shock N=767), so the per-K decision must compare original JSON,
  reconstructed JSON, and paper body values.

Therefore the decision is **not** "rebuild from scratch" but rather: for each K,
does the reconstructed-vs-original diff + paper-body citation warrant **(a)
iterate reconstruction to pass allclose**, **(b) revise paper numbers to the
reconstructable values**, or **(c) accept as errata with pending-errata note**?

## Source Files

- `paper/volatility-absorption/reproduce_report.json` — 50.7% traceability
- `paper/volatility-absorption/experiments.md` — canonical Table → K mapping
- `paper/volatility-absorption/main_v2.tex` — paper body (numbers verbatim)
- `experiments/k71[6-9]/k*.py` + `experiments/k72[0-2]/k*.py` — reconstructed scripts
- `experiments/k71[6-9]/k*_reconstruction_diff.md` + k72[0-2] equivalents — diff evidence
- `experiments/k71[6-9]/k*_results.json` (original) vs `k*_results_reconstructed.json`
- `storage/memory/knowledge.json` — K716–K722 canonical narrative

## Artifacts

- `k1231_reconstruction_plan.md` — human-readable decision matrix
- `k1231_reconstruction_decisions.json` — structured per-K decisions (7 entries)

## Prior K Refs

- K1229 — audit that flagged Paper 8 as P2 BLOCKER
- K716 / K717 / K718 / K719 / K720 / K721 / K722 — each analyzed below
- docs/paper-guide.md — 三方一致 rule (a/b/c)

## Seed

42 (no randomness actually executed; K1231 is an analysis document, seed fixed
for any derivative simulation that might consume this plan).

## Status

DRAFT — awaiting main-thread decision on per-K (a/b/c) and sequencing.
