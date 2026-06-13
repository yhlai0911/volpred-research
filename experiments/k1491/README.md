# K1491 — Crypto VoV Tail-Spillover Methodology Fix

- Experiment ID: `K1491`
- Task: `K1491_fix_k1490_methodology`
- Parent: `K1490`
- Status: complete
- Seed: `42`

## Motivation

K1490 tested whether BTC / ETH vol-of-vol predicts tail events in SPY / GLD / USO / TLT. The research direction is valid, but the original implementation failed methodologically:

- Traditional ETF rolling windows were computed on a calendar panel containing weekend `NaN` values, so `sigma_20d` and `vov_20d` for SPY / GLD / USO / TLT became all `NaN`.
- The target tail event was a sparse binary indicator, and all 8 Granger tests failed with constant-column errors.
- No knowledge entry should be written from K1490 until a valid tail-spillover test exists.

K1491 keeps the same question but replaces the fragile binary target with a continuous quantile-crossing tail signal.

## Design

### Data

- Source: `yfinance` adjusted daily close
- Requested sample: `2018-01-01` to `2025-12-31`
- Predictors: `BTC-USD`, `ETH-USD`
- Targets: `SPY`, `GLD`, `USO`, `TLT`
- Returns: per-asset log close-to-close returns on each asset's valid trading days

### Signal

For each traditional target:

```text
tail_signal_t = max(0, |r_t| - rolling_q95(|r|_{t-20:t-1}))
```

This turns tail events into a continuous exceedance magnitude. It avoids the constant-column failure while preserving the question: do lagged crypto volatility shocks forecast unusually large traditional-market moves?

### Predictor

For each crypto asset:

```text
sigma_t = rolling_std_20d(r_t)
vov_t = rolling_std_20d(sigma_t)
predictor_t = vov_t.shift(1)
```

The explicit `.shift(1)` is the lookahead control.

### Tests

- Granger causality, lags 1 to 5: `tail_signal ~ own lags + lagged crypto_vov`
- Main Granger p-value: best raw lag p-value multiplied by `MAX_LAG=5`, to reduce lag-mining overclaim
- Quantile regression: `q=0.95` of target `|r|` on lagged crypto VoV z-score
- Bonferroni across 8 crypto-target pairs

## Literature Check

- Diebold & Yilmaz (2012), volatility spillover measurement
- Mazzarisi et al. (2020), tail Granger causality and false-linkage risk
- Patton (2011), volatility comparison under imperfect proxies

## Outputs

- Script: [`experiments/k1491/k1491.py`](/Users/yhlai0911/Desktop/volpred-research/experiments/k1491/k1491.py)
- Results: [`experiments/k1491/k1491_results.json`](/Users/yhlai0911/Desktop/volpred-research/experiments/k1491/k1491_results.json)
- Figures:
  - [`experiments/k1491/k1491_spillover_heatmap.png`](/Users/yhlai0911/Desktop/volpred-research/experiments/k1491/k1491_spillover_heatmap.png)
  - [`experiments/k1491/k1491_tail_signal_timeseries.png`](/Users/yhlai0911/Desktop/volpred-research/experiments/k1491/k1491_tail_signal_timeseries.png)

## Interpretation Rules

- If any Granger pair still fails, verdict is `METHOD_FAIL`.
- If any pair survives Bonferroni, verdict is `PARTIAL`.
- If only nominal p-values pass, verdict is `WEAK`.
- If no nominal pass appears, verdict is `NULL`.

No `knowledge.json` update is made here. Main-thread review should inspect the JSON and code first.

## Results

K1491 fixes the K1490 method failure:

- Granger valid pairs: `8/8`
- Constant-column errors: `0/8`
- Granger Bonferroni pair passes: `4/8`
- QuantReg q95 Bonferroni pair passes: `7/8`
- Verdict: `PARTIAL`

The Granger passes are concentrated in:

| Predictor | Target | lag-adjusted pair p | Best lag |
|---|---:|---:|---:|
| BTC-USD VoV | USO tail signal | 0.000946 | 5 |
| BTC-USD VoV | TLT tail signal | 0.000014 | 4 |
| ETH-USD VoV | USO tail signal | 0.000976 | 5 |
| ETH-USD VoV | TLT tail signal | 0.001855 | 5 |

SPY and GLD do not survive the Granger pair-level Bonferroni correction. Quantile regression is broader: 7 of 8 pairs have positive q95 absolute-return slopes after Bonferroni, with ETH-USD to GLD the only non-pass.

## Caveats

- The local snapshot source is `experiments/k1090b/data`, not a fresh yfinance download. External DNS failed during this run, so the effective common target sample ends on `2024-12-30`.
- This is predictive Granger / QuantReg evidence, not structural causality.
- No strategy, CoVaR, or OOS trading rule is validated here.
