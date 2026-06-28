# K1558 — Candlestick OHLC Spot-Vol Estimators as Direct Day-Ahead Forecasters

## TL;DR

**Verdict: NULL** — GARCH(1,1) baseline wins per-asset QLIKE on **6/6 ETFs** (SPY, QQQ, IWM, TLT, GLD, HYG). Direct closed-form OHLC candlestick estimators (Parkinson, Garman-Klass, Rogers-Satchell, Yang-Zhang) used **without** autoregressive smoothing **do not beat GARCH** as 1-step-ahead variance forecasters. Replicates the K464 "GJR baseline hard to beat" finding under a stricter direct-forecast framing.

## Question

Can the closed-form OHLC range estimator computed on day t-1 — used **as the forecast directly**, no autoregressive layer — beat GARCH(1,1) at predicting day-t realized variance? Prior K (K934/K935/K938) wrap these estimators in CARR autoregressive structures; K1558 asks whether the raw daily candlestick already carries enough vol signal to skip the AR layer.

## Design

- **Universe**: 6 ETF panel — SPY, QQQ, IWM (equity large/tech/small-cap), TLT (treasuries), GLD (gold), HYG (high-yield credit). Daily OHLCV via yfinance, 2014-01-01 onward, n_oos ≈ 3,135 each.
- **Models** (6 total):
  1. Parkinson (1980)
  2. Garman-Klass (1980)
  3. Rogers-Satchell (1991)
  4. Yang-Zhang (2000, rolling n=20 for the k weight)
  5. Equal-weight ensemble of the 4 OHLC estimators
  6. GARCH(1,1) baseline (arch package, rolling re-estimation, target-aligned forecast per K445)
- **Target**: squared close-to-close log-return on day t (Patton-canonical variance proxy).
- **Forecast lag**: estimator computed on day t-1 OHLCV, then `.shift(1)` to forecast day-t variance. GARCH forecast manually rolled with fit on `returns[:i+1]` then indexed to target_date `idx[i+1]` (lookahead-safe — verified by audit sample showing `fc[t] == sigma2[t-1]` for all checked dates).
- **Loss**: Patton QLIKE = `mean(a/f - log(a/f) - 1)`, via `volpred.stats.model_evaluation.qlike()` / `qlike_pointwise()`. MSE reported as secondary.
- **Inference**: pairwise Diebold-Mariano (h=1, Newey-West HAC), per-asset t-stats, Holm-Bonferroni multiple-testing correction across 90 pairs (6 assets × 15 within-asset pairs), Fisher's method to combine per-asset p-values into a cross-asset combined p (avoids `.claude/rules/experiments.md` "stacking asset-day inflates significance" pitfall).
- **Seed**: `np.random.seed(42)`, `random.seed(42)`.

## Results

### Per-asset QLIKE (lower is better, best in **bold**)

| Asset | Parkinson | Garman-Klass | Rogers-Satchell | Yang-Zhang | GARCH | EqualEnsemble |
|-------|-----------|--------------|-----------------|------------|-------|---------------|
| SPY | 2.387 | 2.241 | 13,891.78 | 1.625 | **1.568** | 1.682 |
| QQQ | 2.308 | 2.183 | 426.85 | 1.569 | **1.543** | 1.657 |
| IWM | 1.829 | 1.744 | 2.068 | 1.368 | **1.359** | 1.420 |
| TLT | 2.923 | 2.725 | 17,016.20 | 1.245 | **1.228** | 1.586 |
| GLD | 4.058 | 3.717 | 4.586 | 1.526 | **1.505** | 1.940 |
| HYG | (see results.json) | | | | **GARCH** | |

GARCH wins QLIKE on **6/6 assets** (per_asset_best_count: `{"GARCH": 6, all others: 0}`). Pooled mean rank: GARCH=1.0, YangZhang=2.0, EqualEnsemble=3.0, GarmanKlass=4.0, Parkinson=5.0, RogersSatchell=6.0.

### Pairwise DM (h=1, Newey-West HAC)

- 90 pairs total (15 within-asset × 6 assets)
- 59 pairs with |t| > 3 (Harvey threshold)
- **57 pairs survive Holm-Bonferroni 5%** — significance is robust to multiple-testing correction

### Notes on Rogers-Satchell extreme QLIKE

RS QLIKE blows up on SPY (13,891), TLT (17,016) and QQQ (427) because the estimator occasionally produces near-zero variance forecasts (sigma2_RS can be near 0 when intraday returns drift but range = O-C ≈ 0), and `actual / predicted` in QLIKE then explodes. This is a known instability of unsmoothed RS and one reason CARR/HAR wrapping is usually used. K1558 reports these untruncated to be honest about the failure mode.

## Mechanism

1. **GARCH carries persistence**; raw daily candlestick estimators have no memory beyond yesterday's range. When yesterday's range happens to be quiet but the true vol process is in a persistent high-vol regime, GARCH's β term still lifts the forecast — the estimator can't.
2. **Yang-Zhang is the strongest OHLC estimator** (rank 2 pooled, beats Parkinson/GK/RS comfortably on every asset), consistent with K441's efficiency finding — but still loses to GARCH on the **forecasting** task. Efficiency at estimating contemporaneous variance ≠ forecasting next-day variance.
3. **Equal-weight ensemble (rank 3) beats individual estimators except YZ**, but not GARCH. Ensemble smooths RS's worst blow-ups without recovering GARCH's persistence.

## What This Adds

- **Direct closed-form forecast is a non-starter** at the daily horizon for ETF panels — even with the best closed-form estimator (Yang-Zhang), GARCH wins QLIKE on 6/6 assets with 57/90 pairs significant after Holm correction.
- Replicates / extends the K464 finding under a cleaner direct-forecast framing across a 6-asset cross-section.
- Honest documentation of RS instability — useful negative result for anyone considering raw RS as a forecast (vs. as a proxy).

## Caveats (audit-flagged)

- **HLN finite-sample correction not explicitly applied** to DM tests — `dm_test(l1, l2, h=1)` uses Newey-West HAC but does not multiply by the Harvey-Leybourne-Newbold `((T+1-2h+h(h-1)/T) / T)^0.5` factor. With h=1 the HLN factor is `((T-1)/T)^0.5` ≈ 1 for large T (n_oos=3135), so impact on the 57 Holm-significant pairs is negligible (HLN would mildly attenuate t-stats — direction is conservative, NULL verdict robust).
- **GARCH `res.convergence_flag` not explicitly checked**; fit exceptions fall back to previous params. Non-convergence would weaken the GARCH baseline, biasing against the NULL verdict — i.e., GARCH winning 6/6 *despite* the unchecked convergence makes the NULL claim **stronger**, not weaker. Still a methodological caveat worth recording.
- Target is squared close-to-close log-return (Patton proxy), not 5-min RV — yfinance 1m quota-bounded prevents full 5-min RV reconstruction over the 12-year sample.
- Single seed (42). Multi-seed not run because no random init exists in the model spec (closed-form estimators + deterministic GARCH MLE init).

## Files

- `k1558.py` — full experiment (795 lines, includes lookahead audit notes in header)
- `k1558_results.json` — per-asset QLIKE/MSE, DM pairwise table, summary, lookahead audit
- `k1558_qlike_bar.png` — pooled QLIKE bar chart
- `k1558_dm_heatmap.png` — pairwise DM t-stat heatmap (90 cells)

## Replication

```bash
uv run python experiments/k1558/k1558.py
```

Outputs `k1558_results.json` + 2 PNGs. Wall time ~22s on M-class Mac.

## Reviewer

Codex code-review subagent audit 2026-06-29:
- Lookahead absence: **PASS** (`.shift(1)` correctly applied k1558.py:339-352; audit sample lines 354-366 verify per-day)
- GARCH target alignment: **PASS** (manual recursion fits on `returns[:i+1]`, indexes forecast to `idx[i+1]`; k1558.py:252-292, 349-351)
- Patton QLIKE direction: **PASS** (`qlike(actual, forecast)` from `volpred.stats.model_evaluation`; k1558.py:416-442)
- DM/HLN/Holm multiple testing: **CONDITIONAL** — Holm/Bonferroni correctly implemented (k1558.py:393-411, 599-627); HLN finite-sample factor not applied — negligible impact at n_oos=3135
- Seed / convergence: **CONDITIONAL** — seed=42 set; `res.convergence_flag` not checked; warnings suppressed. Non-convergence would weaken GARCH, biasing AGAINST NULL — does not threaten verdict direction

**Overall verdict: CONDITIONAL_PASS** — methodology sound, NULL conclusion robust to flagged caveats; record caveats but do not re-run.
