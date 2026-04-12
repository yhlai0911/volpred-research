# K1064: TW_EAV_factor as Exogenous Regressor in A4f — From Description to Prediction

**Proposer**: 賴奕豪 · **Executor**: Claude · **Date**: 2026-04-12
**Verdict**: **NULL RESULT** — EAV signal is descriptive only; does not improve OOS A4f prediction on 0050.TW.

---

## 1. Motivation

The Taiwan EAV trilogy (K1059/K1060/K1062) established several descriptive facts:

| Finding | Result |
|---|---|
| K1060 individual TW stock T+1 ratio | 1.466, binom p = 0.034 (★ sig) |
| K1059 A4f vs GJR event-window amplification | DM t = 2.50 vs 1.22 (non-event) |
| K1062 ETF T+1 ratio | 1.132 (directional but NS) |

All of these are **descriptive**: they characterize what happens around announcement dates.
K1064 asks the *predictive* question: can the EAV signal be used as an **active exogenous regressor** inside A4f's `τ_t` layer to improve the out-of-sample volatility prediction for 0050.TW?

### Hypotheses
- **H1 (main)**: A4f + EAV_signal delivers Harvey-significant DM improvement over A4f (|t| > 3.0)
- **H2**: θ₂ (EAV loading) > 0 and statistically significant across refits
- **H3**: Improvement concentrates in event-window subsamples

---

## 2. Model Specification

**Baseline A4f** (6 params):
```
τ_t = max(θ₀ + θ₁·VIX²_{t-1}, ε)
g_t = ω_g + α·u_{t-1}² + γ·u_{t-1}²·I(u<0) + β·g_{t-1}
σ²_t = τ_t · g_t
u_t = r_t / sqrt(τ_t)
```

**A4f-EAV extended** (7 params, one extra `θ₂`):
```
τ_t = max(θ₀ + θ₁·VIX²_{t-1} + θ₂·EAV_signal_{t-1}, ε)
```

**Information-set discipline (no lookahead)**: Taiwan earnings are post-close events.
`EAV_signal_t` counts announcements that *became public* during trading day t.
Used as `EAV_{t-1}` in τ_t → all conditioning information is in the info-set at t-1 close.
Code uses explicit `.shift(1)`-equivalent construction (`eav_lag[1:] = eav_series[:-1]`).

### EAV Variants
Three weighting schemes tested:
- **equal**: raw count of announcing companies on day t
- **sector**: weighted by K1060 sector T+1 ratios (Tech 1.60, Fin 1.29, Trad 2.15, Telecom 0.85)
- **top50**: restricted to 0050.TW constituents only (most relevant for ETF vol)
All variants log1p-transformed to tame heavy right tail.

---

## 3. Data & Method

| Item | Value |
|---|---|
| Asset | 0050.TW (`clean_tw50_data` applied) |
| External regressors | ^VIX (daily close), TW earnings announcements |
| Announcement source | `財報公告日.txt` (Big5, 116,856 records, 2,195 companies, 2010-2025) |
| Period | 2010-01-05 to 2025-12-30 (n = 3,912 trading days) |
| OOS | 2019-01-01 onwards (n_oos = 1,698) |
| Rolling window | 2,000 days |
| Refit cadence | Every 63 days (27 refits total) |
| Seed | 42 |
| Runtime | ~403s |

### Descriptive stats on EAV signals
| Variant | Mean | Max | Nonzero days |
|---|---|---|---|
| equal count | 29.87 | 1,924 | 2,664 / 3,912 (68.1%) |
| sector weighted | 30.38 | 1,951 | same coverage |
| top50 count | 0.775 | 37 | 908 / 3,912 (23.2%) |

### In-sample correlation with r²
| Signal | corr(r², EAV_log) |
|---|---|
| equal | −0.0087 |
| sector | −0.0090 |
| top50 | −0.0230 |

Correlations are *negative* and near zero — first warning sign.

---

## 4. Results

### 4.1 OOS QLIKE (lower is better)

| Model | QLIKE | Spearman | Δ vs A4f |
|---|---|---|---|
| A4f (baseline) | **1.430359** | +0.2521 | — |
| A4f_EAV_equal | 1.434835 | +0.2507 | +0.31% (worse) |
| A4f_EAV_sector | 1.435121 | +0.2549 | +0.33% (worse) |
| A4f_EAV_top50 | 1.439393 | +0.2520 | +0.63% (worse) |

All three EAV variants **fail to improve** over A4f baseline.

### 4.2 DM test vs A4f (negative t → EAV variant better)

| Variant | DM t | p | QLIKE improve | Harvey |t|>3.0 | Direction |
|---|---|---|---|---|---|
| equal | +1.082 | 0.280 | −0.205% | **FAIL** | A4f_better |
| sector | +0.959 | 0.338 | −0.207% | **FAIL** | A4f_better |
| top50 | +2.360 | 0.018 | −0.419% | **FAIL** | A4f_better |

The top-50 variant's +2.36 is the wrong direction — A4f baseline beats it at standard |t|>1.96 significance (but not Harvey).

### 4.3 θ₂ distribution across 27 refits (H2)

| Variant | Mean | Median | Pos fraction | t(θ₂>0) | p | 95% Bootstrap CI |
|---|---|---|---|---|---|---|
| equal | −3.02e-05 | +2.91e-07 | 0.56 | −1.00 | 0.836 | [−9.08e-05, 2.37e-07] |
| sector | −3.85e-05 | +2.63e-07 | 0.67 | −1.04 | 0.846 | [−1.14e-04, 1.82e-07] |
| top50 | −2.24e-05 | +2.02e-06 | 0.74 | −0.89 | 0.810 | [−7.34e-05, 3.71e-06] |

**H2 REJECTED**: None of the variants show statistically significant θ₂ > 0.
Noteworthy: θ₂ median is positive in all variants (0.56–0.74 positive fraction), but a handful of large negative estimates drag the mean below zero. This suggests a **fragile, non-robust signal** rather than a consistent positive one.

### 4.4 Event vs non-event conditional analysis (H3)

| Variant | Event days (n=457) |  Non-event days (n=1241) |
|---|---|---|
| equal | DM t=+0.181, improve=−0.052% | DM t=+1.261, improve=−0.398% |
| sector | DM t=−0.551, improve=**+0.552%** | DM t=+1.799, improve=−0.622% |
| top50 | DM t=+0.325, improve=−0.042% | DM t=+2.831, improve=−0.825% |

**H3 PARTIALLY SUPPORTED (directionally, not significantly)**:
- Only the **sector-weighted** variant shows positive improvement on event days (+0.55%, t=−0.55, not significant)
- All variants are worse on non-event days
- Consistent with K1059's qualitative finding, but the magnitude is far too small to be predictively useful

### 4.5 Robustness: lag sensitivity (in-sample)

| Specification | θ₂ | IS QLIKE |
|---|---|---|
| EAV_{t−1} (default) | −9.74e-07 | 1.351471 |
| EAV_{t−2} | −1.58e-06 | 1.350424 |
| EAV rolling 5-day | −1.43e-07 | 1.352130 |

θ₂ remains negligible across all specifications. The change in lag does not unlock any hidden signal.

---

## 5. Why the null?

Three plausible explanations (consistent with prior literature):

1. **Aggregation-level dilution**: 0050.TW as an ETF is a diversified basket; idiosyncratic earnings news across 50 constituents averages out. K1060 showed this clearly: individual stocks T+1 = 1.466, ETF T+1 = 1.132, gap ≈ 33%.

2. **VIX already absorbs macro risk**: A4f's `θ₁·VIX²` captures the market-wide component. Earnings news is *idiosyncratic*, and by the time it aggregates to a systemic effect, it is already reflected in VIX. The in-sample `corr(r², EAV_log) ≈ −0.01` confirms there is almost no linear residual signal after VIX.

3. **Descriptive ≠ predictive**: K1060's T+1 ratio = 1.466 is a *conditional mean* on individual event days. K1059's DM t = 2.50 is an *average model advantage over a rolling period*. Neither implies that the aggregate EAV count has a *daily linear predictive loading* for the ETF's next-day σ².

---

## 6. Limitations

- **Linear specification only**: We tested `θ₂·EAV_{t-1}` linearly. A non-linear transformation (e.g. threshold effect, interaction with VIX) was not tested.
- **Single index**: Only 0050.TW tested. K1060 shows clear individual-stock EAV — a stock-level A4f-EAV experiment might succeed (a future experiment, K1070+).
- **Fixed refit cadence**: 63-day refit may dilute any transient signal. A 5-day refit around announcements might help but would be a very different experiment.
- **Value-weighting proxy**: We used sector-tier weights as a proxy for market-cap weighting. True 0050.TW constituent market caps (time-varying) would be more accurate but require quarterly weight snapshots.

---

## 7. Conclusion

**The EAV signal is descriptive, not predictive — at least for 0050.TW at the daily frequency.**

| Hypothesis | Verdict |
|---|---|
| H1 — A4f+EAV improves A4f (|t|>3.0) | **REJECTED** (all variants FAIL Harvey; top-50 marginal sig. in wrong direction) |
| H2 — θ₂ > 0 significantly | **REJECTED** (all three variants NS, means slightly negative) |
| H3 — improvement concentrated in event windows | **PARTIALLY supported directionally** (sector variant +0.55% on event days, NS) |

The finding is consistent with the ETF-level diversification dilution story (K1062) and the EMH-based view that by the time earnings news from 50+ companies aggregates to the ETF level, VIX has already absorbed the systemic component.

### Implications for Paper 2 (Taiwan VT)
- A4f with US VIX² alone remains the right specification for 0050.TW vol prediction
- The EAV story belongs in the **descriptive / mechanism section** of Paper 2, not in the forecasting model
- A follow-up experiment at the **individual-stock level** (e.g., TSMC 2330.TW with A4f-EAV) is the natural next step — if sufficient individual-stock option/hedging applications exist

---

## 8. Files

| File | Description |
|---|---|
| `k1064.py` | Main experiment script |
| `k1064_results.json` | Full results including parameter histories |
| `k1064_dm_comparison.png` | QLIKE + DM t-stats for all variants |
| `k1064_theta2_distribution.png` | θ₂ evolution across refits + 95% bootstrap CI |
| `k1064_event_window_analysis.png` | Event vs non-event conditional performance |
| `README.md` | This document |

## 9. References
- Engle, Ghysels & Sohn (2013). GARCH-MIDAS. *Review of Economics and Statistics* 95(3):776-797.
- Patton (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics* 160:246-256.
- Harvey, Liu & Zhu (2016). ... and the Cross-Section of Expected Returns. *RFS*.
- Patell & Wolfson (1984). The intraday speed of adjustment of stock prices. *Journal of Accounting Research*.
- Savor & Wilson (2016). Earnings announcements and systematic risk. *Journal of Financial and Quantitative Analysis*.
- K1058: A4f cross-market validation on 0050.TW (baseline establishment)
- K1059: A4f vs GJR event-window amplification (descriptive)
- K1060: Individual TW stock EAV (T+1 ratio = 1.466)
- K1062: 0050.TW ETF-level EAV dilution (T+1 ratio = 1.132)
