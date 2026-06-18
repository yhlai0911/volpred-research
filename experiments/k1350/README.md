# K1350: HAR ceiling verification - Los Flamingos 2025

## Motivation

`research_program.md` listed `K1350: 「HAR ceiling」驗證 — Los Flamingos 2025`. The phrase maps to the Los Flamingos Research article, "Volatility Forecasting: Why a Well-Tuned HAR Model Still Reigns Supreme (Even Over ML)", which summarizes the paper "HARd to Beat: The Overlooked Impact of Rolling Windows in the Era of Machine Learning".

This experiment verifies whether the backlog item is still open in this repo. It does not fabricate an exact replication from unavailable data. Instead, it audits existing out-of-sample receipts against the project gates and records the remaining exact-replication blocker.

## Literature And Source Check

External sources checked before the audit:

- Los Flamingos Research, 2025-06-03: practitioner summary of the HARd-to-Beat finding. It states that a daily-refit HAR/HAR-VIX with a 2.5-4 year rolling window is difficult for ML models to beat.
  - https://www.losflamingosresearch.com/deeep-dive-june-3-2025
- "HARd to Beat: The Overlooked Impact of Rolling Windows in the Era of Machine Learning" (`arXiv:2406.08041v1`): primary academic source. It uses 1,445 U.S. stocks from 2015-2023 and compares tuned HAR against ML models on QLIKE, MSE, and utility.
  - https://arxiv.org/html/2406.08041v1
- Clements and Preve, "A practical guide to harnessing the HAR volatility model": background on how HAR accuracy depends on estimator/transformation/combination choices.
  - https://ink.library.smu.edu.sg/soe_research/2489/
- Federal Reserve FEDS 2025-061, "Linear and nonlinear econometric models against machine learning models": recent context showing transparent econometric volatility models can remain competitive against ML.
  - https://www.federalreserve.gov/econres/feds/linear-and-nonlinear-econometric-models-against-machine-learning-models.htm

## Local Data And Receipts

The script reads frozen local result receipts:

- `experiments/k530/k530_har_multiscale_results.json`
- `experiments/k764/k764_rough_vol_multivariate_results.json`
- `experiments/k1377/k1377_results.json`
- `experiments/k1349/K1349_results.json`
- `experiments/k1521/k1521_results.json`
- `experiments/k966/k966_har_pd_results.json`

No historical JSON, database field, or memory file was manually edited.

## Method

`K1350.py` builds a reproducible evidence matrix with these gates:

- Paper-grade OOS length: `n_oos >= 252`.
- Harvey-style forecast-comparison threshold: `|t| > 3` when DM/Harvey t-statistics are available.
- Intraday pilots below the threshold cannot become knowledge or article-grade claims.
- No new strategy PnL is computed in this audit. The script records the required future timing guard: `signal.shift(1)` or equivalent one-step-ahead forecast alignment.

The experiment produces:

- `K1350_results.json`
- `K1350_har_ceiling_matrix.csv`
- `K1350_har_ceiling_matrix.png`

## Results

Main verdict:

`PROVENANCE_CONFIRMED_LOCAL_CEILING_COVERED_EXACT_REPLICATION_DATA_UNAVAILABLE`

Evidence summary:

- 11 evidence rows.
- 4 local paper-grade rows.
- 5 rows support the generic HAR-ceiling claim.
- K530: SPY and 0050.TW daily-proxy HAR variants beat GJR/EWMA under Harvey-style project gates.
- K764: rough-vol HAR extensions did not break the HAR-ABS ceiling.
- K1377: an adaptive HAR-family combination improved over HAR-VIX in 2/3 assets, but this is still a HAR-family refinement rather than a non-HAR/ML break.
- K1349, K1521, and K966: local 5-minute follow-ups remain pilot-only because OOS length is below 252.

## Interpretation

The generic local backlog item "verify the HAR ceiling" is no longer open: prior local experiments already provide reproducible daily-proxy evidence that tuned HAR-class models are a hard baseline to beat, and richer rough-vol/path-dependent additions have not produced a robust break.

The exact Los Flamingos / HARd-to-Beat replication is not completed. It requires the 1,445-stock 2015-2023 high-frequency realized-volatility panel and the corresponding ML fitting grid. That input panel is not present in local storage.

## Codex Review

PASS with scope limitation.

This result should not be written as a new `knowledge.json` finding because it is a scope-resolution audit, not a new paper-grade forecast discovery. The correct next step, if exact replication is required, is to acquire the original high-frequency RV panel and reproduce the HAR fitting-scheme grid.
