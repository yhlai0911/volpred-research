# K1316 — VIX Sufficient Statistic Test on TAIFEX TX1 (Cross-Market Replication)

## Motivation

K1315 confirmed that US VIX is a **sufficient statistic** for SPY daily realized variance: in an Anti-QLIKE forecast combination, HAR-VIX receives full weight (1.0) while HAR-ABS receives zero. The natural cross-market extension is: does this hold for Taiwan futures (TX1)?

This experiment tests whether US VIX lags can substitute for own-RV lags in predicting TX1 realized variance, using a parallel HAR regression architecture.

## Hypotheses

- **H1**: HAR-VIX achieves significantly lower QLIKE on TX1 than HAR-RV; DM-HLN |t| > 3
- **H0 (NULL)**: VIX has no incremental predictive value over own past RV for TX1 RV

## Methodology

### Models

| Model | Features | Description |
|-------|----------|-------------|
| HAR-RV (baseline) | log(RV_{t-1}), log(RV_w), log(RV_m) | Standard HAR with own past RV |
| HAR-VIX (test) | log(VIX²_{t-1}), log(VIX²_w), log(VIX²_m) | HAR with US VIX² as variance proxy |

- **RV_w** = mean of rv_lag1 over 5 days on TX1 calendar
- **RV_m** = mean of rv_lag1 over 22 days on TX1 calendar
- **VIX_w/VIX_m** analogous, computed on VIX calendar
- log(VIX²) = 2·log(VIX) — aligns VIX to log-variance scale comparable to log(RV)

### Lookahead Discipline

- `rv_lag1 = rv.shift(1)` on TX1-only series **before** inner-join with VIX
- `vix_lag1 = vix.shift(1)` on VIX-only series **before** inner-join
- Rolling averages computed on each series' own calendar
- Target: `rv.shift(-1)` on TX1 series before merge
- This preserves true own-calendar lags (not compressed by holiday-induced inner-join gaps)

### Data

| Source | Details |
|--------|---------|
| TX1 daily RV | TAIFEX tick CSV, day session 08:45–13:45, 5-min bars, 2017-2026 |
| VIX daily | yfinance `^VIX` close, 2017-01-01 to 2026-05-01 |
| Alignment | Inner join on trading date (Taiwan/US holiday differences → ~80 dates lost) |

### Statistical Tests

- **Loss function**: QLIKE (Patton 2011) — proxy-robust, theoretically justified
- **DM-HLN**: Harvey-Leybourne-Newbold (1997) small-sample correction, h=1
- **Pass rule**: |DM_HLN_t| > 3 AND HAR-VIX lower QLIKE AND bootstrap 95% CI excludes 0
- **Bootstrap**: 500x iid resample CI on QLIKE diff (seed=42)
- **Split**: 70/30 chronological (IS: 2017-06-16 to 2023-08-22; OOS: 2023-08-23 to 2026-04-30)

## Results

| Metric | HAR-RV | HAR-VIX |
|--------|--------|---------|
| QLIKE OOS | -6.1558 | -8.6538 |
| MSE OOS | 1.5156 | 1.5872 |
| R² IS | — | — |
| R² OOS | — | — |

| Test | Statistic | p-value | Threshold | Result |
|------|-----------|---------|-----------|--------|
| DM-HLN (QLIKE) | t = 1.041 | 0.298 | |t| > 3 | NOT MET |
| DM-HLN (MSE) | t = -0.735 | 0.463 | |t| > 3 | NOT MET |
| Bootstrap CI | [-0.265, 7.587] | — | excludes 0 | NOT MET |

**Verdict: NULL**

## Verdict Components

- `pass_3sigma_dm_qlike = False` (t=1.04 < 3.0)
- `vix_lower_qlike = True` (HAR-VIX QLIKE is lower in raw level terms)
- `bootstrap_ci_excludes_zero = False` (CI includes 0)

Although HAR-VIX has a numerically lower QLIKE in absolute terms (+40.6% diff), the difference is **not statistically significant** by DM-HLN criteria (|t|=1.04 << 3.0). The bootstrap CI also spans zero. NULL stands.

## Interpretation

**K1315 result does not generalize cross-market to Taiwan futures.**

- For SPY (own-market): VIX is a sufficient statistic (K1315 PASS, HAR-VIX weight=1.0)
- For TX1 (cross-market): VIX has no statistically significant incremental predictive power over domestic HAR-RV (K1316 NULL)

This finding supports the view that **domestic RV persistence dominates foreign vol signals** for TX1. The US fear gauge conveys information about US equity vol, but this cross-market spillover is too noisy to reliably outperform the TX1's own realized variance history at h=1 day horizon.

The two experiments together characterize the boundary of the VIX sufficient-statistic property:
- **Within-market**: Strong (VIX explains all of SPY variance predictability)
- **Cross-market**: Weak (VIX provides no significant incremental information for TX1)

## Sample Statistics

- n_total: 2085 (after warm-up dropna)
- n_train (IS): 1459
- n_test (OOS): 626
- Date range: 2017-06-16 to 2026-04-30
- Inner-join lost ~80 rows (Taiwan/US holiday differences)

## Files

| File | Description |
|------|-------------|
| `k1316.py` | Main experiment script |
| `k1316_results.json` | Full results including all metrics and methodology |
| `k1316_qlike_plot.png` | Cumulative QLIKE + scatter plot (OOS) |
| `data/_vix_daily_2017-2026.parquet` | Cached VIX daily data |

## Related Experiments

- **K1315**: HAR-VIX vs HAR-ABS on SPY — PASS (VIX sufficient, weight=1.0)
- **K1309**: HAR-PD vs HAR-RV on TX1 — NULL
- **K1303**: HAR-CJ vs HAR-RV on TX1 — NULL
- **K1301**: HAR-RS vs HAR-RV on TX1 — NULL

## Codex Review

Reviewed by Codex (gpt-5.4) prior to execution. Two issues identified and fixed:
1. Lag construction was incorrectly done post-merge; fixed to build lags on each series' own calendar before inner join
2. Bootstrap label corrected from "block" to "iid" bootstrap
All four primary checks passed: (1) lookahead clean, (2) DM-HLN correct, (3) QLIKE matches Patton 2011, (4) IS/OOS split integrity confirmed.
