# K1091: Out-of-Sample Validation of K1090 Meta-Regression
### (VGK + EWJ + CPER + SLV)

[提出: 用戶 (via K1091 brief), 執行: Claude]
Date: 2026-04-12 · Upstream: K1090 (meta training), K1075/K1085/K1088/K1089 (A4f baselines)

---

## Motivation

**K1090** trained a 12-asset meta-regression mapping asset-level features to the
realised A4f-VIX² vs GJR Diebold-Mariano t-statistic. The preferred compact
OLS specification was

```
DM_t  ≈  -1.22  +  3.38 · USD_dummy  −  4.11 · corr(ret, ΔVIX)
              (R² = 0.54, LOOCV R² = 0.26, LOOCV RMSE = 1.943)
```

For six out-of-sample ETFs the K1090 **ridge** predictor (chosen as the
recommended predictor by K1090) and its 95% predictive interval produced:

| Ticker | Ridge pred | 95% PI | Recommendation |
|--------|-----------:|:--------------:|----------------|
| VGK (Europe equity)  | **+4.71** | (3.26, 5.84) | strong_run |
| EWJ (Japan  equity)  | **+4.34** | (3.16, 5.40) | strong_run |
| CPER (Copper ETF)    | **+3.58** | (0.35, 4.47) | run        |
| SLV  (Silver ETF)    | **+3.58** | (0.70, 4.29) | run        |
| IEF, ETH-USD         | 1.93, 1.28 | —          | likely_fail |

K1091 takes the four PASS/run candidates, actually runs A4f-VIX² on them, and
asks: **does the meta-regression generalise to genuinely held-out assets?**

## Research questions

* **H1** VGK A4f-VIX² vs GJR Harvey-PASS (|t|>3, positive)?
* **H2** EWJ Harvey-PASS?
* **H3** CPER Harvey-PASS?
* **H4** SLV Harvey-PASS?
* **H5** MAE between K1090 ridge predictions and realised DM-t below the
  K1090 LOOCV RMSE of 1.94?

## Method

* **Model** for every asset:

  ```
  tau_t = theta0 + theta1 * VIX_{t-1}²
  r_t   = sqrt(tau_t * g_t) · z_t   with GJR(1,1) on the standardised residuals
  ```

  (identical specification to K1075, K1085, K1088, K1089).

* **Baseline**: GJR-GARCH(1,1) with the same 6-parameter bounded MLE and
  rolling window.

* **Window / OOS** per asset (data constrains CPER):

  | Asset | Data begins | Window | OOS window |
  |-------|-------------|-------:|------------|
  | VGK   | 2005-03-11  |  2000  | 2013-03-01 .. 2026-04-10 |
  | EWJ   | 1996-03-19  |  2000  | 2007-01-03 .. 2026-04-10 |
  | CPER  | 2011-11-16  |  1500  | 2020-01-02 .. 2026-04-10 |
  | SLV   | 2006-05-01  |  2000  | 2014-05-01 .. 2026-04-10 |

  Refit quarterly (63 days). CPER uses WINDOW=1500 because yfinance history
  starts only in 2011-11; still above the 500-day Hwang & Valls Pereira (2006)
  minimum.

* **No lookahead**: code uses `v_lag = vix[abs_idx - 1]` and
  `r_prev = ret[abs_idx - 1]` — every forecast at time *t* only sees
  information available at close of *t−1*. Training slice `ret[train_start:abs_idx]`
  excludes the forecast date.

* **Evaluation** (all on r² as target, Patton-2011 QLIKE):
  * DM test with Newey-West HAC (Harvey-Leybourne-Newbold 2016), pass threshold |t|>3.0.
  * Bootstrap 95% CI of mean QLIKE loss differential (1 000 reps, block bootstrap, seed 42).
  * Spearman rank correlation between forecast and realised r².

* **Data**: yfinance daily Adjusted Close for each ticker, plus ^VIX Close
  (Close is fine because VIX has no dividend/split). VIX is forward-filled
  onto the ticker's trading-day calendar.

* **Seed 42** for every bootstrap and optimiser restart.

## Results

### Full-OOS Harvey table

| Asset | n_OOS | QL_GJR | QL_A4f | QLIKE Δ%  | DM-t | p | Harvey |
|-------|------:|--------:|--------:|----------:|-----:|---:|:------:|
| **VGK** | 3298 | −8.2407 | −8.2976 | −0.69% | **+4.457** | 8.32e-06 | **PASS** |
| **EWJ** | 4848 | −8.0310 | −8.0622 | −0.39% | **+4.806** | 1.54e-06 | **PASS** |
| CPER    | 1576 | −7.1825 | −7.1882 | −0.08% | +0.436 | 0.663 | FAIL |
| SLV     | 3004 | −7.2047 | −7.2041 | +0.01% | −0.082 | 0.935 | FAIL |

Bootstrap 95% CI of mean QLIKE loss differential (positive ⇒ A4f better):

| Asset | CI_lo | CI_hi | CI excludes 0? |
|-------|------:|------:|:--------------:|
| VGK   | 0.0332 | 0.0833 | **yes** |
| EWJ   | 0.0174 | 0.0436 | **yes** |
| CPER  | −0.0193 | 0.0314 | no |
| SLV   | −0.0158 | 0.0120 | no |

### Meta-prediction validation

| Asset | K1090 ridge_pred | Realised DM-t | \|err\| | Within PI95 | Harvey | Direction correct? |
|-------|-----------------:|--------------:|-------:|:-----------:|:------:|:------------------:|
| VGK   | +4.71 | **+4.46** | 0.25 | yes | PASS | **yes** |
| EWJ   | +4.34 | **+4.81** | 0.47 | yes | PASS | **yes** |
| CPER  | +3.58 | +0.44    | 3.14 | yes | FAIL | no |
| SLV   | +3.58 | −0.08    | 3.67 | no  | FAIL | no |

Aggregate (n = 4):

* **MAE = 1.882**  (vs K1090 LOOCV RMSE **1.943**  → H5 **marginally PASS**)
* **RMSE = 2.429**
* **Mean bias (realised − predicted) = −1.65**  (meta over-predicts)
* **Harvey PASS: 2/4**
* **Direction-correct: 2/4**

### Asset-class pattern

| Class | Assets in K1091 | Result |
|-------|-----------------|--------|
| Equity (non-US, USD denom) | VGK, EWJ | **2/2 PASS** (error ≤ 0.47) |
| Commodity (industrial/precious, no IV) | CPER, SLV | **0/2 PASS** (error 3.1–3.7) |

The split is exactly the K1088 lesson **re-confirmed on two new assets**:
commodity ETFs with only *cross-asset* (VIX) information fail Harvey — they
need **asset-matched implied vol** (GVZ for gold, OVX for oil). The ridge
model, trained on only one proper commodity-with-matched-IV pair (GLD+GVZ via
K1085 scoring), overestimates how much generic VIX helps an untyped
commodity. In fact realised corr(ret, ΔVIX) for CPER is only −0.054, for SLV
−0.041 — far weaker than GLD (−0.149 in K1085 diagnostics).

## Conclusions

1. **H1 (VGK) PASS**: +4.46 DM-t, very close to ridge prediction of +4.71
   (|err| = 0.25). European equity follows the VIX-fits-global-equity rule.
2. **H2 (EWJ) PASS**: +4.81 DM-t, again within 0.47 of ridge prediction.
   Japan equity, despite being a different time zone, also inherits the VIX
   cross-asset signal (consistent with K991–K992 Japan results).
3. **H3 (CPER) FAIL** and **H4 (SLV) FAIL**: VIX-only A4f is indistinguishable
   from GJR for copper and silver. Realised DM-t (+0.44, −0.08) is well below
   the Harvey threshold.
4. **H5 (MAE < LOOCV RMSE)** marginal PASS (1.88 < 1.94). Remove SLV and the
   MAE drops to 1.29; keep only the equities and MAE = 0.36. **The meta formula
   is accurate for equities and over-optimistic for matched-IV-less commodities.**

### What this tells us about K1090

* The meta formula captures the **equity-VIX pattern** very accurately: for
  VGK and EWJ it predicts the realised DM-t to within half a unit. This is a
  genuine out-of-sample success for the regression framework.
* The formula **systematically over-predicts for commodities without matched
  IV** because K1090's training set contained only one matched-IV commodity
  (GLD+GVZ in K1085) and one unmatched commodity (USO pre-OVX, K1088).
  Ridge pulls commodity predictions toward the equity mean.
* Suggested K1090 refinement: add a feature **`has_matched_IV`** (binary:
  does an implied-vol series exist for the asset class?) and re-fit. Current
  features (`class_commodity`, `currency_usd`) cannot distinguish CPER/SLV
  from GLD-with-GVZ.
* Alternative: re-run CPER and SLV with asset-matched IV (copper-IV, silver-IV)
  if Volmex/Cboe publish such series. A home-IV proxy (30-day rolling RV) like
  K1089's BTC30RV is a reasonable fallback.

### Four-class matrix update after K1091

| Class | Representative | A4f with asset-matched IV? | K1091 evidence |
|-------|----------------|-----------------------------|-----------------|
| Equity (US)     | SPY, QQQ, IWM, EEM, FXI | N/A (VIX *is* matched) | — |
| Equity (non-US USD) | **VGK, EWJ**         | N/A (VIX proxies) | **PASS (new)** |
| Commodity (gold/oil) | GLD, USO             | GVZ / OVX matched | PASS (K1085/K1088) |
| Commodity (copper/silver) | **CPER, SLV**    | No matched IV yet | **FAIL with VIX only (new)** |
| Bonds | TLT | MOVE/yield-curve FAIL (K1086/87) | — |
| Crypto | BTC-USD | BTC30RV matched (K1089) | — |

## Limitations

* N = 4 validation assets. An MAE with n = 4 has a very wide CI; point
  estimate only.
* CPER uses WINDOW=1500 instead of 2000, so results are not perfectly
  comparable to the other assets. Robustness to window size not probed.
* No commodity-matched IV was available for copper / silver at the time of
  this run. If Volmex publishes such series the CPER and SLV results should
  be re-evaluated.
* SLV realised DM-t is *negative*, which lies outside the ridge 95% PI
  (0.70, 4.29). This is a genuine failure of the meta model, not a small
  over-prediction.

## Files

```
experiments/k1091/
├── README.md                          (this file)
├── k1091.py                           (batch pipeline, 4 assets)
├── k1091_results.json                 (all numbers, per-asset refit logs)
├── k1091_meta_validation.png          (scatter: prediction vs realised)
├── k1091_four_assets_dm.png           (bar chart of realised DM-t + predictions)
└── k1091_updated_matrix.png           (16-asset matrix = 12 training + 4 K1091)
```

## References

* Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
  Fundamentals. *RES* 95(3):776–797. [GARCH-MIDAS / A4f foundation]
* Patton (2011). Volatility forecast comparison using imperfect volatility
  proxies. *J. Econometrics* 160:246–256. [QLIKE]
* Harvey, Leybourne & Newbold (2016). Testing the equality of prediction
  MSE. [Harvey |t|>3 threshold]
* Diebold & Mariano (1995). Comparing Predictive Accuracy. *J. Business &
  Economic Statistics* 13:253–263. [DM test]
* Hansen & Lunde (2005). A forecast comparison of volatility models. [FCV rule]
* Andersen, Bollerslev, Diebold & Labys (2003). Modeling and Forecasting
  Realized Volatility. [r² as target]
* K1085, K1088, K1089 (this project).

*Author: VolPred Research System (Claude).  Seed 42, yfinance data snapshot
ending 2026-04-10.*
