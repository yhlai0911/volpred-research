# K1481 — Inventory-surprise commodity RV regime feature (Crude pilot)

## Motivation

Backlog item from `research_program.md`: 能否把 **EIA crude inventory surprise** (actual − naive baseline) 作為 commodity RV 的 regime feature, 加進 HAR-RV，比 price-only baseline 改善 QLIKE/MSE?

Source rationale:
- CFA Institute 2025 "ML in commodity futures" notes inventory shocks are the canonical fundamental driver of WTI vol.
- *Journal of Futures Markets* literature (Bjornson-Carter 1997; Kilian 2008) treats inventory disturbances as the structural supply shock identifying oil price vol.
- Prior K1129 (GAS-t commodity NULL), K1136 (robust vol methods commodity NULL), K1135 (Skew-t GAS QLIKE NULL), K1402/K1403 (har-rv quantile commodity) all compared **vol-model spec families** and produced NULL/CONDITIONAL. None added a **fundamental exogenous feature**. This is the differentiation angle.

## Hypothesis

H1: Adding a lagged crude-inventory-surprise term to HAR-RV improves daily WTI RV one-step-ahead forecast vs price-only HAR (in QLIKE and MSE), with Diebold-Mariano p < 0.10.

H2 (regime): The improvement is concentrated in weeks with `|surprise| > 1σ` (large inventory shocks), captured via an interaction `surprise × regime_dummy`.

## Design

### Data
- **CL=F** (WTI futures, yfinance) daily OHLC, 2010-01-04 → 2026-05-29 (~4126 trading days)
- **EIA WCESTUS1** (Weekly U.S. Ending Stocks excluding SPR of Crude Oil, thousand barrels): downloaded from `https://www.eia.gov/dnav/pet/hist_xls/WCESTUS1w.xls`, 1982-08-20 → 2026-06-05
- Sample restricted to 2010-01-04 onward to match futures coverage and avoid pre-shale regime.

### Realized vol proxy
Daily RV proxy: **Garman-Klass range estimator**
```
RV_t = 0.5 (log(High_t / Low_t))^2 - (2 ln 2 - 1) (log(Close_t / Open_t))^2
```
Higher efficiency than squared close-to-close returns; standard in commodity vol literature (Patton 2011, Liu et al. 2015). We use RV as the target and forecast `RV_{t+1}`.

### Inventory surprise construction
1. Compute weekly **delta**: `Δinv_w = inv_w − inv_{w-1}` (kbbl change)
2. Naive consensus proxy: **rolling AR(1)** one-step forecast trained on the prior 52 weeks of `Δinv` (expanding when <52 obs available; first 52 weeks dropped).
3. `surprise_w = Δinv_w − ar1_forecast_w` (actual minus expected change)
4. **Standardize** by rolling 52-week std of surprise (Z-score).
5. **Publication lag**: EIA releases Wednesday 10:30 ET for the prior Friday's snapshot. We treat the inventory surprise as **available on the report's calendar-week Thursday close**, i.e. forward-fill `surprise_z_w` to daily, then `signal at t = surprise_z` available **two business days after the period_end Friday**. This is conservative (real release is Wed of the following week ≈ 5 days post period_end).

### Models (all targeting `log(RV_{t+1})` to stabilize variance)
1. **HAR-RV** (Corsi 2009): `log_RV_{t+1} = b0 + b1·log_RV_t + b2·log_RV_w + b3·log_RV_m`
   - `log_RV_w` = mean of last 5 daily log-RV; `log_RV_m` = mean of last 22.
2. **HAR-INV**: HAR-RV + `b4·surprise_z_{t-k}` (k chosen to enforce post-publication availability — see "Lookahead" section).
3. **HAR-INV-REGIME**: HAR-RV + `b4·surprise_z + b5·|surprise_z|·I(|surprise_z|>1)` (regime interaction).

### Train/test
- **Expanding-window OLS**, refit every 252 business days (~annual).
- First fit: 2010-01-04 → 2014-12-31 (initial 5-yr train).
- OOS: 2015-01-01 → 2026-05-29.
- One-step-ahead forecasts collected; `signal at t` uses information ≤ `t-1` (see `run.py` `signal.shift(1)` enforcement).

### Evaluation
- **QLIKE** (Patton 2011 robust loss): `QLIKE = log(σ̂²) + RV/σ̂²` averaged.
- **MSE** on log-RV.
- **R²_OOS** vs in-sample mean of log-RV.
- **Diebold-Mariano test** of HAR-INV vs HAR-RV and HAR-INV-REGIME vs HAR-RV. Newey-West HAC (5-lag), bootstrap n_boot=1000 seed=42 for finite-sample p-values.

### Lookahead audit
- `EIA report_t` (period_end Friday w) → **earliest usable trading day** = Friday(w+1) (5 calendar days lag). In code: `surprise` series indexed at period_end Friday, then `.shift(5, freq='B')` (5 business days) and forward-filled. Daily HAR features then take `surprise_z.shift(1)` to ensure signal at trading day `t` only uses info ≤ `t-1`.
- All seeds: `np.random.seed(42)`, `np.random.default_rng(42)` for bootstrap.

## Differentiation from related K

| K | Topic | Verdict | Differentiation |
|---|---|---|---|
| K1129 | GAS-t commodity | NULL | We do **not** change vol-model family; we add exog feature to HAR. |
| K1136 | Robust vol methods commodity | NULL | Same — methodology not feature. |
| K1135 | Skew-t GAS commodity | QLIKE NULL / VaR rescued | Different metric focus + we test mean RV not tails. |
| K1402/3 | HAR-RV quantile commodity | fair-comp violation / bootstrap bug | We fix both: symmetric refinement (all models HAR family + OLS), DM with seeded bootstrap. |

## Expected outcome

Prior literature is split: Kilian (2008) finds inventory shocks affect oil prices but the RV-level forecasting evidence is thin. We expect:
- **Best case**: HAR-INV improves QLIKE by 1-3% with DM p < 0.10.
- **Realistic case**: HAR-INV marginal; HAR-INV-REGIME (large shocks only) shows isolated improvement.
- **Null case**: surprise is already priced in by futures market intraday before the OOS forecast — feature offers no incremental info post-publication.

## References
1. Corsi, F. (2009). A simple approximate long-memory model of realized volatility. *Journal of Financial Econometrics*, 7(2), 174-196.
2. Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256.
3. Kilian, L. (2008). Exogenous oil supply shocks: How big are they and how much do they matter for the U.S. economy? *Review of Economics and Statistics*, 90(2), 216-240.
4. Bjornson, B., & Carter, C. A. (1997). New evidence on agricultural commodity return performance under time-varying risk. *American Journal of Agricultural Economics*, 79(3), 918-930.
5. Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics*, 13(3), 253-263.

## Files
- `run.py` — full reproducible script
- `k1481_inventory_surprise_crude_rv_pilot_results.json` — metrics + DM tests + provenance
- `figure_har_vs_inv.png` — OOS RV forecast vs realized
- `references.md` — full bibliography
