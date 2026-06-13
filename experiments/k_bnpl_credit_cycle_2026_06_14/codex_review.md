# Codex Review: k_bnpl_credit_cycle_2026_06_14

Verdict: `CONDITIONAL_PASS_NULL_RESULT`

## Scope

Reviewed `k_bnpl_credit_cycle_2026_06_14.py`, `README.md`, generated results JSON, and the three generated figures.

## Checks

- Experiment three-piece requirement: PASS. The folder contains `README.md`, the runnable experiment script, and `k_bnpl_credit_cycle_2026_06_14_results.json`, plus figures and this review.
- Data provenance: PASS. Price data are downloaded from yfinance adjusted close; FRED series and conservative lags are recorded in JSON metadata.
- Literature pre-check: PASS. README records CFA Institute, CFPB, BIS, New York Fed, and FRED sources.
- Lookahead: PASS. Daily predictive features use `.shift(1)` or a more conservative FRED lag. The event stress flag is explicitly `raw_signal.shift(1)`, so same-day BNPL stress is not paired with same-day target returns.
- Randomness: PASS. The event moving-block bootstrap uses `SEED=42` and `N_BOOT=1000`.
- Formal tests: PASS. The experiment reports moving-block bootstrap event diagnostics, HAC regressions, and OOS QLIKE/DM comparisons with the strict `|t| > 3` threshold.
- Claim strength: PASS with caveat. The final conclusion is correctly NULL and does not convert listed-equity proxy evidence into private BNPL loan-performance evidence.

## Caveats

- The public ticker sample starts only in 2021 because AFRM/SOFI have short histories, so OOS evidence spans 2024-08-01 to 2026-06-12 only.
- FRED delinquency series are lagged conservatively, but this is still not a true ALFRED first-release vintage design.
- The BNPL basket is an equity-market proxy for fintech/platform lending stress, not a direct measure of BNPL credit performance or ABS/private-credit marks.
- Event-study next-day p-values around 0.05 are descriptive and should not be treated as a publication-grade multiple-testing pass.

## Publishability

Publishable only as a null-result / proxy-limitations note. Do not claim a tradable BNPL early-warning signal. A fair article angle is that public BNPL/consumer-lender equities may flag short-lived stress co-movement, but they do not improve rolling OOS volatility forecasts for IWM, HYG, or XLF once HAR and market controls are considered.
