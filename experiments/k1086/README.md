# K1086: A4f on TLT with MOVE — Testing Asset-Matched Regressor Theory on Bonds

**Experiment ID**: K1086
**Asset**: TLT (iShares 20+ Year Treasury Bond ETF)
**Proposed by**: User (Claude executed)
**Date**: 2026-04-12
**Status**: **FAIL** (asset-matched regressor theory does NOT extend to bonds — null result)

---

## 1. Problem & Motivation

K1085 discovered on GLD:
- `A4f-VIX` DM t = +1.83 — **FAIL** (Harvey |t|>3)
- `A4f-GVZ` (gold's own IV) DM t = +4.46 — **PASS**

**Interpretation**: The A4f structure (Engle 2013 MIDAS-style multiplicative,
with free omega and Engle-2013 denom=tau) is a general form, but the long-run
regressor must match the asset's *own* implied volatility index.

**This experiment tests whether the theory extends to bonds.** If yes, the
asset-matched regressor principle becomes a general law across asset classes
(equity/gold/bonds). If no, K1085 is a gold-specific curiosity.

## 2. Hypotheses

| H | Statement | Threshold |
|---|-----------|-----------|
| H1 | TLT A4f-VIX does not Harvey-PASS | \|DM t\| ≤ 3 |
| H2 | TLT A4f-MOVE Harvey-PASSes vs GJR | DM t > 3 |
| H3 | A4f-MOVE Harvey-significantly beats A4f-VIX on TLT | pairwise DM t > 3 |
| H4 | MOVE still beats GJR during 2022 rising-rate regime | DM t > 0 in 2022 |

## 3. Data

| Source | Ticker | Range | Notes |
|--------|--------|-------|-------|
| yfinance | TLT (Adj Close) | 2003-01-02 ~ 2026-04-10 | Log returns |
| yfinance | ^MOVE (Close) | 2003-01-02 ~ 2026-04-10 | Treasury option IV |
| yfinance | ^VIX (Close) | 2003-01-02 ~ 2026-04-10 | Equity IV baseline |

Corr(VIX, MOVE) on aligned sample = ~0.59 (distinct enough).

## 4. Method

### OOS Design
- Rolling window `W = 2000` trading days
- Refit every `REFIT_EVERY = 63` days (quarterly)
- OOS window: **2011-01-01 ~ 2026-04-10** (ensures ≥2000 days of MOVE-era training before first OOS forecast)

### Models
| Key | τ specification |
|-----|-----------------|
| `GJR` | GJR-GARCH(1,1) baseline (no regressor) |
| `A4f_VIX` | τ = θ₀ + θ₁·VIX²ₜ₋₁ |
| `A4f_MOVE` | τ = θ₀ + θ₁·MOVE²ₜ₋₁ |
| `A4f_COMBO` | τ = θ₀ + θ₁·VIX²ₜ₋₁ + θ₂·MOVE²ₜ₋₁ |

All A4f variants use Engle (2013) denom=τ for the short-run component `g`, with free ω_g and GJR leverage γ in the g-equation.

### Evaluation
- **QLIKE** on r² (Patton 2011, proxy-robust)
- **DM test** with Newey-West HAC (Harvey 2016 threshold |t|>3)
- **Spearman** rank correlation
- **Bootstrap** 95% CI (moving block, seed=42)
- **Crisis sub-periods**: Euro 2011-12, Taper Tantrum 2013, COVID 2020, Rising Rates 2022
- **Regime buckets**: VIX and MOVE deciles

### Lookahead controls
- All regressors enter at `t-1` (see `vix[abs_idx - 1]` / `move[abs_idx - 1]` in code)
- Rolling-window refit: parameters at time t use only data `[t-W, t)`

## 5. Expected Outcomes

If asset-matched theory holds:
- H1, H2, H3 all PASS
- Paper 9 extends to "A4f structure is general but τ regressor must match asset-class IV"
- Next step: test USO-OVX (oil-oil), EEM-VXEEM (emerging markets)

If theory does not hold:
- K1085 remains a gold-specific result
- Needs alternative explanation (perhaps bond returns are driven more by level factors than by option IV)

## 6. Files

| File | Purpose |
|------|---------|
| `k1086.py` | Experiment script |
| `k1086_results.json` | Complete results (QLIKE, DM, per-window, crisis, buckets, refit log) |
| `k1086_extended_dm.png` | 4 models' full-OOS DM vs GJR |
| `k1086_crisis_periods.png` | A4f-MOVE vs A4f-VIX across 4 crisis windows |
| `k1086_vix_move_compare.png` | QLIKE side-by-side + DM bar chart |
| `k1086_theta1_evolution.png` | θ₁ time series (dual axis: VIX vs MOVE coefs) |
| `k1086_asset_class_matrix.png` | Heatmap of DM t-stats across (asset × IV index) cells, combining K1075 + K1085 + K1086 |

## 7. Results

Runtime: 781s (13 min). OOS n=3759 (2011-01-03 ~ 2026-04-10), 60 refits.

### Full OOS

| Model | QLIKE | Spearman | DM vs GJR | Harvey |
|-------|-------|----------|-----------|--------|
| GJR | -8.465790 | 0.253 | — | — |
| A4f-VIX | -8.498327 | 0.261 | +1.431 | FAIL |
| A4f-MOVE | -8.493825 | 0.269 | +1.363 | FAIL |
| A4f-COMBO | -8.497910 | 0.262 | +1.435 | FAIL |

All three A4f variants improve QLIKE slightly (~0.03) but **none pass Harvey |t|>3**. The theta1 coefficients carry the expected positive sign but are not economically large enough to dominate the baseline GJR.

### Pairwise DM

| Comparison | DM t | p-value | Harvey |
|------------|------|---------|--------|
| A4f-MOVE vs A4f-VIX | **-0.889** | 0.374 | FAIL |
| A4f-COMBO vs A4f-MOVE | +0.835 | 0.404 | FAIL |
| A4f-COMBO vs A4f-VIX | -0.439 | 0.661 | FAIL |

Critically, MOVE does **not** beat VIX on TLT (t = -0.889, i.e. VIX is marginally better, not worse). This contradicts the asset-matched theory.

### Crisis Sub-Periods

| Crisis | n | GJR QL | VIX QL | MOVE QL | MOVE DM | VIX DM |
|--------|---|--------|--------|---------|---------|--------|
| Euro Debt (2011-12) | 272 | -7.754 | -7.760 | -7.717 | -1.339 | +0.201 |
| Taper Tantrum (2013) | 161 | -8.490 | -8.500 | -8.512 | +1.431 | +0.550 |
| COVID Crash (2020) | 104 | -6.598 | -7.485 | -7.449 | +1.776 | +1.650 |
| Rising Rates 2022 | 249 | -7.588 | -7.635 | -7.645 | +1.549 | +2.132 |

In the 2022 rising-rate regime, **VIX (t=+2.132) actually beats MOVE (t=+1.549)**. MOVE is competitive but not uniformly superior.

### Bucket Analysis

MOVE gets its strongest signal in the **VIX_Extreme** bucket (VIX>40, n=51, QLIKE improvement -28%, DM=+2.07). But both VIX and MOVE are strong here — this is a cross-asset stress window, not a MOVE-specific signal.

### Hypothesis Verdicts

| H | Target | Result | Verdict |
|---|--------|--------|---------|
| H1 | TLT A4f-VIX does NOT Harvey-PASS | t=1.43 ≤ 3 | **PASS** |
| H2 | TLT A4f-MOVE Harvey-PASSes | t=1.36 ≤ 3 | **FAIL** |
| H3 | MOVE Harvey-beats VIX | t=-0.89 | **FAIL** |
| H4 | MOVE beats GJR in 2022 | t=+1.55 | PASS (weak) |

**Overall: FAIL.** The asset-matched regressor theory found on gold (K1085) does NOT transfer to long-duration Treasuries.

### Interpretation (null result as finding)

1. **K1085 (GLD-GVZ) may be a special case, not a general law.** Gold is a monetary hedge with distinct vol dynamics; Treasury vol may not share the same compositional structure.
2. **TLT vol under MOVE is only marginally better than under VIX.** The high correlation (0.59) between VIX and MOVE means whatever long-run signal MOVE carries is largely redundant with VIX for TLT's r² — unlike GVZ vs VIX for GLD.
3. **A4f *as a structure* does not fail on TLT — it marginally improves over GJR (QLIKE -0.033)**, just not Harvey-significantly with either regressor in isolation.
4. **Possible explanation**: bond return volatility is driven more by *level and slope* of the yield curve than by option-implied vol. MOVE captures option-market fear but may miss the duration-risk channel that dominates bond r² variability.

### Future directions this opens

- Test A4f on TLT with **yield-curve factors** (e.g. 10y-2y slope squared, 10y level) as the long-run regressor
- Test on **IEF** (7-10yr) and **EDV** (25+yr) — duration gradient analysis
- Test **corporate bond** ETFs (LQD, HYG) where credit spread is the natural matched IV
- Re-examine K1085 GLD result with controls that match TLT's regime (rate-sensitive periods only)

## 8. Key Numbers (for cross-reference with knowledge base)

Verbatim from `k1086_results.json`:
- `full_oos.A4f_VIX.dm_t_vs_gjr` = **+1.431**
- `full_oos.A4f_MOVE.dm_t_vs_gjr` = **+1.363**
- `full_oos.A4f_COMBO.dm_t_vs_gjr` = **+1.435**
- `pairwise_dm.A4f_MOVE_vs_A4f_VIX.dm_t` = **-0.889**
- `crisis_subperiods.Rising_Rates_2022.A4f_MOVE.dm_t_vs_gjr` = **+1.549**
- `crisis_subperiods.Rising_Rates_2022.A4f_VIX.dm_t_vs_gjr` = **+2.132**
- `hypothesis_verdicts.overall` = **"FAIL"**

All quoted numbers have been verified against the JSON output.

## 8. Limitations

- MOVE data from yfinance starts 2003; no pre-GFC history from late-1980s CBOE release
- OOS starts 2011 (after 2000-day training requirement); GFC 2008-09 not in OOS
- Results may be sensitive to how A4f COMBO's two coefficients jointly identify in periods when VIX and MOVE are highly correlated (e.g. 2008, 2020)
- TLT 1:4 history concerns not applicable (TLT is a US-listed ETF, fully reflected in Adj Close)
- Only one asset per class tested here — single-asset conclusions cannot establish bond-class universality without EDV / IEF / LQD replication (future work)

## 9. References

- Engle, R. F., Ghysels, E., & Sohn, B. (2013). *Stock Market Volatility and Macroeconomic Fundamentals*. RES 95(3), 776-797.
- Patton, A. J. (2011). *Volatility forecast comparison using imperfect volatility proxies*. J. Econometrics 160, 246-256.
- Harvey, D. I., Leybourne, S. J., & Newbold, P. (2016). *Testing the equality of prediction mean squared errors*.
- K1075 (VolPred, 2026-04): SPY A4f-VIX extended-history stress test
- K1085 (VolPred, 2026-04): GLD A4f-GVZ asset-matched regressor validation
