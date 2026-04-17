# K1238: Paper 10 §3 Data and Preliminaries Initial Draft

## Purpose

Produce an initial Markdown draft of Paper 10 (crypto-fear-channel) Section 3 "Data and Preliminaries" (~600 words, 3 subsections) for main-thread adoption into `paper/crypto-fear-channel/body_v1.tex`.

This is a **planning / drafting artifact only** — it does not modify shared state, does not write `.tex`, and does not trigger paper-level decisions. Per CLAUDE.md §"論文 narrative state machine", worktree agents produce `.md` drafts; the main thread cherry-picks and translates into `body_v(n).tex`.

## Source References

- `experiments/k1234/k1234_kickoff_guide.md` — §3 target scope and subsection outline (~600 words, 2 pages, 5 bullets consolidated to 3 subsections here)
- `paper/crypto-fear-channel/body_v0_intro.tex` — §1 Introduction draft, which locks sample to SPY + BTC + VIX and $N = 2{,}812$
- `paper/crypto-fear-channel/outline.md` — paper-level outline
- `experiments/k1025/k1025_results.json` — canonical source of all descriptive statistics and ADF test values reproduced in the draft
- `experiments/k1025/README.md`, `experiments/k639/README.md`, `experiments/k746b/README.md` — supporting experiment context

## Scope Decision (User-Brief vs Paper State)

The launching task brief suggested broadening §3 to cover BTC + ETH + SOL and adding the Alternative.me crypto-fear-greed index. After cross-checking with:

1. `body_v0_intro.tex` abstract, which commits to "daily returns on SPY, BTC-USD, and VIX";
2. K1234 kickoff guide §3, which specifies "SPY, BTC-USD, VIX daily 2015-02 to 2026-04, $N = 2{,}812$";
3. K639 / K746b / K1025 — all three supporting experiments use the three-series setup only;

I have kept the draft **within the existing three-series scope** (SPY + BTC + VIX). Expanding to ETH/SOL/CFIX would require new supporting experiments and would contradict §1 as already drafted. The scope-expansion question is flagged in `k1238_data_draft.md` §"Notes for Main-Thread Adoption" bullet 2 for explicit decision.

## Parallel Context

- **K1237**: §2 Literature Review draft (parallel worktree, in-progress).
- **K1238**: this one — §3 Data draft.
- Both feed into main-thread `body_v1.tex` compilation after review.

## Main-Thread Adoption Workflow

1. Main thread reviews `k1238_data_draft.md` alongside `k1237_*.md` (§2) once both worktrees commit.
2. Cherry-pick wording into `paper/crypto-fear-channel/body_v1.tex` under a `\section{Data and Preliminaries}` block.
3. Convert the Markdown Table 1 placeholder into a `booktabs` LaTeX table, saving the source fragment to `paper/crypto-fear-channel/tables/table1_descriptive.tex`.
4. Cross-check reproduced numbers against `experiments/k1025/k1025_results.json` bit-for-bit.
5. Resolve the ETH/SOL scope decision flagged in §"Notes for Main-Thread Adoption".
6. When `body_v1.tex` is complete, run `paper-update` CLI per standard workflow.

## Files Produced

- `k1238_data_draft.md` — the ~600-word §3 draft with Table 1 placeholder
- `k1238_data_outline.json` — structured outline and canonical-value registry
- `README.md` — this file

## Constraints Respected

- Seed 42 (declared in draft §3.1).
- Lookahead-bias lag discipline called out explicitly in draft §3.2 via `signal.shift(1)`.
- No fabricated descriptive statistics — all numbers reproduced from `k1025_results.json`.
- No `.tex` files created; only `.md` + `.json`.
- No modifications to any shared state (`storage/`, `paper/`, `knowledge.json`, etc.).

## Canonical Numbers Used (all from k1025_results.json)

| Field | Value | Source path in JSON |
|-------|-------|---------------------|
| Sample $N$ | 2,812 | `n_observations` |
| Sample period | 2015-02-02 to 2026-04-08 | `sample_period` |
| OOS period | 2019-01-01 to 2026-04-08 (1,826 obs) | `oos_period` |
| Data source | yfinance (SPY, BTC-USD, ^VIX) | `data_source` |
| BTC mean / std / skew / kurt | 0.00229 / 0.03764 / -0.093 / 7.579 | `descriptive_statistics.btc_ret` |
| SPY mean / std / skew / kurt | 0.00056 / 0.01117 / -0.307 / 14.150 | `descriptive_statistics.spy_ret` |
| VIX mean / std / min / max | 18.382 / 7.110 / 9.140 / 82.690 | `descriptive_statistics.vix` |
| BTC-RV20 mean / std / min / max | 0.5418 / 0.2569 / 0.0980 / 1.7009 | `descriptive_statistics.btc_rv20` |
| ADF BTC-RV20 | -4.898, p=3.5e-05 | `adf_tests.btc_rv20` |
| ADF VIX | -5.711, p=7.3e-07 | `adf_tests.vix` |
| ADF SPY-RV20 | -4.460, p=2.3e-04 | `adf_tests.spy_rv20` |
