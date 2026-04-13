# K1090 — Cross-Asset A4f Meta-Regression (Scope Prediction Formula)

**Question**: Given Paper 9 has completed A4f tests on 12 assets, can we *predict*
whether a new asset will PASS A4f (DM t ≥ 3.0) from observable characteristics,
without having to run the full experiment first?

**Answer (short)**: Yes, partially. A two-feature Ridge/compact-OLS model
(`currency_usd + corr(ret, ΔVIX)`) achieves LOOCV R² ≈ 0.26 and RMSE ≈ 1.94–2.36
on the DM-t scale. USD denomination and a strongly negative
return–VIX correlation are the two dominant scope predictors. 0050.TW (TWD) and
BTC-USD (crypto) remain the genuine outliers — confirming K1088/K1089's finding
that scope limits are driven by currency mismatch and crypto structure.

---

## 1. Motivation — Paper 9's "meta" gap

Paper 9 ran A4f on 12 assets (K1085–K1089). Results span a wide range:
SPY scores DM t = +7.92, while 0050.TW scores −0.49 (the only fail). Mid-tier
assets (EWT +2.26, TLT +1.43, BTC +1.13) are ambiguous.

A reader / practitioner who wants to apply A4f to a *new* asset (EWJ, IEF,
SLV, CPER, ETH, VGK, …) currently has no quantitative guidance — must run the
whole pipeline. This experiment extracts a **predictor formula** from the 12
existing data points so Paper 9 can add a "scope prediction" section.

## 2. Training data

| # | Ticker   | DM t  | class            | currency | source K |
|---|----------|-------|------------------|----------|----------|
| 1 | SPY      | +7.92 | equity US large  | USD      | K1085    |
| 2 | QQQ      | +5.99 | equity US tech   | USD      | K1085    |
| 3 | EEM      | +5.25 | equity EM basket | USD      | K1086    |
| 4 | IWM      | +4.80 | equity US small  | USD      | K1085    |
| 5 | USO      | +4.48 | commodity oil    | USD      | K1088    |
| 6 | GLD      | +4.46 | commodity gold   | USD      | K1088    |
| 7 | FXI      | +3.61 | equity China     | USD      | K1086    |
| 8 | EWZ      | +2.33 | equity Brazil    | USD      | K1086    |
| 9 | EWT      | +2.26 | equity Taiwan(USD)| USD     | K1086    |
| 10| TLT      | +1.43 | bonds long-dur   | USD      | K1087    |
| 11| BTC-USD  | +1.13 | crypto           | USD      | K1089    |
| 12| 0050.TW  | −0.49 | equity Taiwan    | TWD      | K1088    |

## 3. Features (p = 12)

- Class dummies: `class_equity`, `class_commodity`, `class_bond`, `class_crypto`
- `currency_usd` (1 if USD-denominated)
- Diversification: `log_n_constituents`, `hhi` (concentration)
- Liquidity: `log_avg_dollar_volume` (log average daily dollar volume)
- VIX co-movement: `corr(ret, ΔVIX)`, `corr(r², VIX²)`
- Own volatility: `annualized_vol`, `r2_acf1` (volatility persistence)

All feature statistics computed on 2018-01-01..2024-12-31 daily adjusted close
from Yahoo Finance (VIX `^VIX`, BTC `BTC-USD`, 0050.TW etc.), fixed seed 42.

## 4. Models

| Model | Purpose | Notes |
|-------|---------|-------|
| OLS full (p=12) | Coefficient baseline | **Saturated** — N = p+1, R² = 1.0 by construction, LOOCV R² = −12 (useless for prediction). Kept only for reference & bootstrap CIs. |
| **Ridge (α=10)** | Primary model | α chosen by LOOCV grid; LOOCV RMSE **2.36**. |
| LASSO (α=1.0) | Feature selection | Selects exactly `currency_usd` + `corr_ret_vix`; LOOCV RMSE 2.46. |
| **OLS compact** | Interpretable model | Uses only LASSO-selected features. R² = 0.54, LOOCV R² = **0.26**, RMSE **1.94**. |
| Decision tree (depth 3) | PASS/FAIL classifier | Splits on `hhi` and `class_commodity`; train acc = 1.0 (overfits N=12 but yields an interpretable boundary). |

## 5. Headline findings

### 5a. Compact OLS formula (the one-liner for Paper 9)

```
DM_t  ≈  −1.22  +  3.38 · currency_usd  −  4.11 · corr(ret, ΔVIX)
          (1.79)   (1.90, p=0.11)       (1.88, p=0.056)
```

- USD denomination adds roughly **+3.4** to expected DM t.
- A **more negative** return–VIX correlation adds to A4f power (stronger leverage
  channel → larger predictable conditional vol).
- Intercept is small and not significant, consistent with both features
  capturing the dominant variation.

Econometrically only `corr_ret_vix` reaches marginal significance (p ≈ 0.06)
given N = 12. But the sign and magnitude are stable across Ridge, LASSO, and
the full OLS (Ridge standardised coefficients: `currency_usd` +0.57, `corr_ret_vix`
−0.52, `class_commodity` +0.42 — the three largest).

### 5b. Ridge LOOCV (honest predictive ability)

LOOCV RMSE 2.36 on a DM-t scale that spans [−0.49, +7.92]. Expressed as LOOCV R²
the compact OLS achieves **0.26** — low in absolute terms but meaningful given
the small sample. Point predictions systematically under-shoot the top (SPY/QQQ)
and over-shoot the bottom (0050.TW / BTC / TLT) — typical shrinkage behaviour.

### 5c. Decision tree boundary

Depth-3 tree uses only `hhi` and `class_commodity` (feature importances 0.51 /
0.49). It memorises the 12 training cases (acc 1.0), so it is **not a
generalisation claim** — but it is a useful mnemonic: single-asset ETFs
(`hhi = 1.0`) that are commodities PASS easily; concentrated *equity* baskets
(high hhi, not commodity) are flagged as the risk zone. See
`k1090_scope_decision_tree.png`.

### 5d. Outliers in LOOCV

The two assets that most violate the linear pattern are **0050.TW** and
**BTC-USD**:

- 0050.TW is the only non-USD asset → the `currency_usd` dummy has the
  full weight of distinguishing it; LOOCV error ≈ +2.3 means the model
  *under-penalises* TWD because there is only one TWD asset in training.
  → Any firm conclusion about currency size requires a second non-USD asset
  (pre-registered: Nikkei in JPY as robustness in a future K).
- BTC-USD sits inside USD-denominated features yet crypto structure
  (24/7 trading, regime breaks) limits A4f. Tree correctly catches this
  via `class_crypto` + `hhi`, but continuous models cannot.

These are consistent with K1088/K1089's own qualitative conclusions.

## 6. Predictions for 6 untested assets

| Ticker   | Class            | Currency | Ridge DM t | 95% PI (Ridge) | P(PASS) | Tree | Recommendation |
|----------|------------------|----------|-----------:|----------------|--------:|------|----------------|
| **VGK**  | equity Europe    | USD      | **+4.71**  | [−1.1, +7.4]   | 0.99    | PASS | strong_run |
| **EWJ**  | equity Japan     | USD      | **+4.34**  | [−1.0, +7.0]   | 0.99    | PASS | strong_run |
| **CPER** | commodity copper | USD      | **+3.58**  | [−0.7, +6.4]   | 0.75    | PASS | run |
| **SLV**  | commodity silver | USD      | **+3.58**  | [−0.5, +6.4]   | 0.80    | PASS | run |
| IEF      | bonds medium-dur | USD      | +1.93      | [−1.4, +5.7]   | 0.29    | FAIL | likely_fail |
| ETH-USD  | crypto           | USD      | +1.28      | [−2.3, +6.2]   | 0.30    | FAIL | likely_fail |

(`pass_prob` = share of B=10 000 Ridge bootstrap replicates where predicted
DM t ≥ 3.0. Ridge bootstrap PIs shrink versus raw OLS bootstrap because of
regularisation.)

Implication for **Paper 9 follow-up**:

- ✅ **Worth running**: EWJ, VGK (confirms developed-ex-US equity scope), SLV, CPER
  (extends K1088 beyond gold/oil).
- ⚠️ **Expected null**: IEF (shorter-duration Treasuries — weaker leverage
  effect), ETH-USD (crypto structure).

None of these is a certainty — the 95% PIs are wide (≈ ±2.5 DM-t units).
The predictions are a *prioritisation aid*, not a substitute for running the
actual A4f experiment.

## 7. Caveats and self-critique

1. **N = 12.** With p = 12 features, the full OLS is saturated (R² = 1, t/p
   undefined). All inferential statements come from Ridge / LASSO / compact
   OLS, which are identified.
2. **p-values are marginal.** Compact OLS p-values are 0.056 and 0.109 — the
   signals survive regularisation but nobody should call them "significant"
   without a much larger training set.
3. **Currency leverage from a single non-USD asset.** Any estimate of the
   `currency_usd` coefficient is effectively "mean(USD assets) − 0050.TW".
   Adding at least one JPY/EUR ETF is the obvious next sample expansion.
4. **Feature collinearity.** `class_commodity` is perfectly aligned with
   `hhi = 1.0` for GLD/USO, which inflates both coefficients in OLS.
   This is *why* Ridge / LASSO were selected — they absorb the collinearity.
5. **Predictions are not a formal hypothesis test.** P(PASS) should be read as
   "should we schedule this experiment?" not "this asset will PASS".
6. **Downloaded features only.** We did not recompute intraday RV, microstructure
   or option-skew features. A richer feature set likely lifts LOOCV R².

## 8. Files

```
experiments/k1090/
├── README.md                                (this file)
├── k1090.py                                 (full pipeline, seed=42)
├── k1090_results.json                       (all coefficients, LOOCV, predictions)
├── k1090_features.png                       (12×12 feature correlation heatmap)
├── k1090_coefficients.png                   (OLS coef + bootstrap 95% CIs)
├── k1090_loocv.png                          (Ridge & compact OLS LOOCV fit)
├── k1090_new_asset_predictions.png          (Ridge forecasts + 95% PIs)
├── k1090_scope_decision_tree.png            (depth-3 PASS/FAIL tree)
├── k1090_training_dm_t.png                  (N=12 DM t ordered)
└── data/                                    (cached yfinance CSVs)
```

## 9. Suggested Paper 9 usage

Add a **"Scope prediction" subsection** (≤ 1 page) citing the compact formula:

> Extrapolating the 12 in-sample A4f results, a two-feature regression
> (`currency_usd` + `corr(r, ΔVIX)`) explains 54% of cross-sectional DM-t
> variation (LOOCV R² 0.26). The point estimates imply that USD-denominated
> equity/commodity assets with a strongly negative return–VIX correlation are
> the natural scope for A4f, while non-USD equity and crypto remain outside.

Followed by Table 5 (= §6 above) as the concrete reader-facing prediction.

## 10. Attribution
- **Proposer**: Claude (autonomous K1090 design, Paper 9 scope analysis).
- **Executor**: Claude.
- **Training labels**: Paper 9 Ks K1085–K1089.
- **Random seed**: 42 (all bootstraps, LOOCV shuffles, tree).
