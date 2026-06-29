# K1568 Codex Source-Level Review

**Reviewer**: Codex CLI interactive session  
**Date**: 2026-06-29  
**Verdict**: `CONDITIONAL_PASS` for artifact integrity; research verdict remains `WEAK_RAW_ONLY`.

## A. Lookahead

- A1 signal lag: **PASS**. Rolling z-score baselines use shifted mean/std at `k1568.py:125-130`, and all tested Federal Register signals are explicitly lagged at `k1568.py:279-280`; regressions consume `*_lag1` at `k1568.py:511-514`.
- A2 forward labels: **PASS**. Forward RV, downside variance, cumulative return, and volume targets are built with `shift(-i)` for `i=1..H`, so the realized window is strictly `[t+1,t+H]` at `k1568.py:315-332`.
- A3 Federal Register timing: **PASS**. Documents are mapped to the first ETF trading date on or after publication date at `k1568.py:230-242`, then shifted one trading day before prediction at `k1568.py:279-280`. This avoids same-day publication/market-close ambiguity.
- A4 yfinance EOD data: **PASS with caveat**. The script uses adjusted OHLCV from yfinance at `k1568.py:142-165` and restricts to rows where all target/control ETF closes are present at `k1568.py:288-290`. Adjusted prices are standard total-return style inputs, but they are still public-market proxies, not transaction-cost or intraday tradability data.

## B. Statistical Tests

- B1 HAC: **PASS**. Controlled OLS uses statsmodels HAC with `maxlags=horizon` at `k1568.py:361-378`; each horizon gets its own lag in `run_tests` at `k1568.py:502-516`.
- B2 Spearman CI: **PASS**. Moving-block bootstrap uses block=`H`, `B=1000`, seed=42 via global RNG at `k1568.py:41-42` and `k1568.py:381-410`.
- B3 AUC CI: **PASS**. Hanley-McNeil normal approximation is implemented at `k1568.py:413-440`. AUC is a downside-tail diagnostic, not a primary pass gate.
- B4 Outcome controls: **PASS**. Controls include own/SPY/VIX lagged RV; downside and volume outcomes add matching lag controls at `k1568.py:474-484`.
- B5 numerical caveat: **WARN**. `log_downside_var` uses `log(var + 1e-12)` at `k1568.py:320-323`; 5-day windows with no negative returns create a lower point mass. This does not invalidate the weak/null verdict, but raw downside p-values should not be overinterpreted.

## C. Multiple Testing

- C1 primary family disclosure: **PASS**. Results define and correct 144 tests: 8 targets x 2 horizons x 3 outcomes x 3 signals at `k1568.py:763-767` and in `k1568_results.json`.
- C2 correction implementation: **PASS**. Bonferroni and Holm-Bonferroni are computed over all controlled-HAC rows at `k1568.py:443-471`.
- C3 significant raw cells: **PASS**. Top raw cells such as `XLI|5d|log_downside_var|proposed_rule_flow_stress` are raw-significant only; no positive Bonferroni/Holm survivor exists in `k1568_results.json`.

## D. Verdict Honesty

- D1 claim strength: **PASS**. README and results repeatedly state that Federal Register rule-flow is not RegData, OIRA paperwork burden, legal spend, or firm-level compliance burden.
- D2 verdict/numbers alignment: **PASS**. The strongest raw positive cell has p=0.0014, above the 144-test Bonferroni alpha 0.000347; `WEAK_RAW_ONLY` is the correct conclusion.
- D3 publication safety: **PASS**. The experiment may support a future-data-motivation statement, but not a robust "regulatory compliance beta predicts RV" claim.

## Overall

`CONDITIONAL_PASS`: implementation is lookahead-safe and statistically disclosed. The main caveats are proxy validity and downside-target zero-mass behavior, both already reflected in the weak/null conclusion.
