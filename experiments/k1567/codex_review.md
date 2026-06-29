# K1567 Codex Source Review

Review date: 2026-06-29  
Artifact verdict: `CONDITIONAL_PASS`  
Research verdict: `WEAK_RAW_ONLY` / corrected-primary NULL

## Scope

Reviewed:

- `experiments/k1567/k1567.py`
- `experiments/k1567/k1567_results.json`
- `experiments/k1567/README.md`

## Findings

- A1 signal lag: PASS. Every tested signal is explicitly shifted once in `k1567.py:233-234`.
- A2 forward target: PASS. Forward RV and cumulative return targets use `ret.shift(-i)` for `i=1..H`, so row `t` uses strictly `[t+1, t+H]` in `k1567.py:241-246`.
- A3 rolling signal baseline: PASS. Stress z-scores use rolling mean/std shifted once, so the normalization baseline ends at `t-1` in `k1567.py:164-167`.
- A4 FRED publication lag: PASS. FRED observations are date-shifted by conservative release lags before forward-fill in `k1567.py:198-202` and documented in results metadata.
- A5 market calendar: PASS after remediation. yfinance non-US / partial-calendar rows are removed by requiring target/control ETF prices before rolling features are computed in `k1567.py:207-213`.
- B1 HAC: PASS. HAC maxlags equals forecast horizon in `k1567.py:310-319`.
- B2 Spearman CI: PASS. Moving-block bootstrap uses `block=H`, `B=1000`, fixed seed in `k1567.py:330-359`.
- B3 AUC CI: PASS. AUC uses the Mann-Whitney rank formulation and Hanley-McNeil SE in `k1567.py:362-382`.
- C1 multiple testing: PASS. Primary family is 24 controlled-HAC p-values with Bonferroni and Holm-Bonferroni in `k1567.py:386-412`; no survivor in `k1567_results.json`.
- D1 overclaim control: PASS. README and JSON explicitly state the proxy limitation: no merchant loan, approval, repayment, enforcement, reserve, or platform delinquency data are observed.

## Caveat

The strongest cells are economically plausible but weak: HYG 21d and IWM 5d credit-fintech stress have controlled HAC t-stats around 2.5 and raw p-values near 1%, but fail the 24-test correction. Univariate t-stats are much larger, showing that platform-equity stress partly captures broad market fear already represented by own RV / SPY RV / VIX controls.

This artifact is acceptable as a reduced-form public-proxy screen. It must not be promoted as a causal merchant-platform credit channel, a platform-lending replication, or a trading signal.

## Verification

- `uv run python -m py_compile experiments/k1567/k1567.py`
- `uv run python experiments/k1567/k1567.py --refresh`
- `uv run python experiments/k1567/k1567.py`
- Targeted JSON checks of `multiple_testing`, IWM/HYG top cells, and final signal/target availability.

No blocking source-code-level issue remains for the stated weak/null claim.
