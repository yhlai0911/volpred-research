# K1339: Commodity Backwardation → Contango Regime-Switch Event Study

**Status:** Pending Codex review
**Run date:** 2026-06-15

## Motivation

Schwab (2026), arXiv 2026-03 rough-vol commodity, and practitioner notes
on the 2025 commodity supercycle suggest that **transitions** between
backwardation and contango regimes (roll-yield sign flips) coincide with
volatility regime shifts in inflation-sensitive ETFs. Prior K work covers
VIX term structure (K671/K711/K975) and crude-inventory features (K1481,
NULL), but **not regime-switch event-study at the commodity term-structure
level using ETF roll-yield proxies**. K1339 asks: do empirical
backwardation→contango (and contango→backwardation) transition dates
identified from cross-section of USO/UNG/CPER roll-yield proxies predict
elevated realized volatility and altered cross-correlation with SPY over
30/60/90-day forward windows?

## Differentiation from prior K

- K671 (VIX roll yield): NULL after lookahead fix. Different proxy (VIX
  futures), different asset (S&P).
- K975 (VIX term-structure slope): IS-significant +2.2% R² on SPY RV.
  Equity index, not commodity ETFs.
- K1481 (EIA inventory surprise): NULL incremental information after HAR-RV
  baseline. Tests **feature** not **regime switch**.
- K1339: tests **discrete regime-switch dates** (event study) on commodity
  ETFs themselves (USO/UNG/CPER) + their spillover to SPY. Differs in
  unit-of-analysis (event vs feature) and asset (commodity ETF vs equity).

## Data

- yfinance daily Adj Close: USO, UNG, CPER, SPY.
- Period: 2015-01-01 to 2026-06-14 (~11.5 years, covers 2015 oil
  crash, 2020 COVID negative oil, 2022 commodity supercycle, 2024-25
  contango, 2025 backwardation→extreme contango).
- Sample N (daily): ~2,900 days.

## Method

### Roll-yield / regime proxy

Without paid futures-curve data, we approximate roll-yield regime from
ETF behavior. Primary proxy:

- **Momentum-slope sign**: For each commodity ETF, compute 21-day return
  minus 63-day return (annualized). In storage-heavy commodities,
  persistent negative slope (recent < longer) tracks contango drag;
  persistent positive slope tracks backwardation roll yield.
- We label regime state at each date as `+1` (backwardation-like) when
  21d return > 63d return scaled, else `-1`. State is computed at t
  using returns through t-1 (`shift(1)`).

### Sustained + cross-asset event filter

- A single-asset regime switch event triggers when the lagged state
  flips and remains stable for ≥10 consecutive trading days
  post-flip.
- A **cross-confirmed regime switch event** is recorded at the first
  trigger date for an ETF only if ≥2 of {USO, UNG, CPER} flip in the
  same direction within a 21-trading-day window.

### Lookahead policy

- Regime state at date t uses only data through t-1 (signal.shift(1)).
- Sustained-10d filter looks at [t, t+9] for **confirmation only**.
  We define **event date** = day-10 (the date at which the filter
  becomes valid using only realised data). Forward returns measured
  from event_date+1 onward — no peek into pre-event data.
- This is conservative: real-world detection has a 10-day lag, which
  we honour in forward-window placement.

### Event study statistics

- Forward realised volatility: annualised std of daily log returns over
  `[event_date+1, event_date+H]` for H ∈ {30, 60, 90}.
- Pre-event baseline: same H-length window ending at event_date.
- Vol jump statistic: `(Vol_post − Vol_pre) / Vol_pre`.
- Paired bootstrap (B=5000, seed=42) over event indices for pooled mean
  jump; report 95% CI and bootstrap p (two-sided).
- Cross-correlation with SPY: Pearson on daily log returns pre vs post;
  paired bootstrap CI for Δρ.

### Seeds

- `np.random.seed(42)` set globally.

## Success criteria

- ≥5 backwardation→contango (or symmetric reverse) events after sustained
  + cross-asset filter.
- At least one of {30,60,90}-day windows shows bootstrap p<0.10 OR
  |effect size| > 0.25 for vol jump.
- Else: honest NULL report (event count, effect sizes, CI, p-values).

## Failure modes / risks

- Momentum-slope proxy is indirect; true backwardation regimes can
  produce diverse momentum patterns. Sustained-10d + cross-confirmation
  mitigates noise but cannot replace true futures-curve data.
- 11.5-year sample may yield <5 cross-confirmed events → underpowered.
- Forward windows overlap subsequent events; we report event-by-event
  table for transparency.

## Outputs

- `K1339_results.json`: regime events, per-event stats, pooled stats,
  bootstrap p, CI, sample N, verdict.

## References

1. Schwab Center for Financial Research (2026). "Commodity futures curve
   primer: backwardation, contango, and roll yield."
   https://www.schwab.com/learn/story/commodities-futures-trading
2. Gao, Han, Li, Zhou (2026). "Rough volatility in commodity markets."
   arXiv:2603.xxxxx (rough-vol commodity, 2026-03).
3. Bollerslev, Patton, Quaedvlieg (2016). "Exploiting the errors: A
   simple approach for improved volatility forecasting." *J. Econometrics*
   192(1), 1-18. (HAR-RV / Patton-style robust vol benchmark.)
4. Christoffersen, Lunde, Olesen (2019). "Factor structure in commodity
   futures return and volatility." *J. Financial and Quantitative
   Analysis* 54(3), 1083-1115.
