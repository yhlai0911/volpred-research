# Codex Review - K1597 Non-Gaussian Rough Volatility Stable-Increment Proxies

verdict: CONDITIONAL_PASS

## Findings

| Severity | Location | Issue | Fix / Status |
|---|---|---|---|
| MED | `k1597.py` | The implementation uses stable-tail, codifference-proxy, and LFSM-lite features, not the full Garcin-Sawaya-Valade LFSM estimator. | Scope is explicit in the script, README, JSON limitations, and conclusion. |
| MED | `k1597_results.json` | Non-Gaussianity is strong, but Hill/log-log tail indices are above 2, so an alpha-stable increment claim is not supported. | Verdict is `NON_GAUSSIAN_BUT_NOT_STABLELIKE_NO_EDGE`; no stable-law claim is made. |
| LOW | `k1597.py` | Formal inference is single-market TAIFEX only. | README limits the implication to local TAIFEX day-session RV and calls for longer cross-asset intraday data before paper-level claims. |
| LOW | `k1597.py` | `CodiffAR` has the best mean QLIKE but not a robust DM/Holm win. | Result is reported as non-robust; zero strict wins are recorded. |

## Checks

- Data provenance: uses frozen local `experiments/k1100h/data/_taifex_5min_2017-2021.parquet`; no live download.
- Artifact completeness: script, README, JSON results, OOS forecast CSV, figure, review, and knowledge handoff are present.
- Lookahead control: each forecast for date `t` uses realized-volatility information through `t-1`; training target `j` uses features dated `j-1` or earlier.
- Metric orientation: QLIKE uses the repo canonical `actual / predicted - log(actual / predicted) - 1` via `volpred.stats.model_evaluation.qlike_pointwise`.
- Inference: one-step DM/HAC uses `h=1`; Holm adjustment is applied across the reported HAR/HARQ pair tests; Harvey |t| > 3 is required for strict wins.
- Randomness: `SEED = 42`; estimation is deterministic.

## Result Integrity

Core JSON checks:

- `verdict = NON_GAUSSIAN_BUT_NOT_STABLELIKE_NO_EDGE`
- `n_days = 1138`
- `n_oos = 488`
- OOS window: 2020-01-02 to 2021-12-30
- Hurst estimates: frequency-ratio H = 0.0545; variogram H = 0.1428
- Jarque-Bera p-value = 6.82e-17
- Student-t df = 8.94; AIC normal minus Student-t = 25.29
- Hill absolute-tail alpha q90 = 3.6256; log-log survival alpha q80 = 3.5781
- Best mean-QLIKE model = `CodiffAR`
- Non-Gaussian strict wins = 0

The conclusion is appropriately conservative: K1597 finds non-Gaussian rough realized volatility, but no alpha-stable or codifference-based forecasting contribution beyond HAR/HARQ.
