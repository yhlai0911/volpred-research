# Codex Review - research_inventory_seasonality_surprise_regime_conditiona

Review date: 2026-06-15

Reviewer: Codex

## Verdict

Experiment integrity: PASS

Research hypothesis: NULL

The implementation is reproducible from yfinance prices plus public EIA weekly
inventory spreadsheets, uses explicit conservative lags, fixes the random seed,
and does not overclaim the DBA seasonality-only placebo as an inventory-regime
result.

## Checklist

1. Lookahead bias: PASS.
   - yfinance price data are downloaded and cached at
     `research_inventory_seasonality_surprise_regime_conditiona.py:78-90`.
   - EIA weekly inventory dates are delayed by 7 calendar days before use
     (`research_inventory_seasonality_surprise_regime_conditiona.py:93-103`).
   - Inventory rolling means, standard deviations, and low-inventory thresholds
     are based on shifted historical windows
     (`research_inventory_seasonality_surprise_regime_conditiona.py:107-123`).
   - Daily inventory features are explicitly shifted by one trading day before
     regression use
     (`research_inventory_seasonality_surprise_regime_conditiona.py:138-145`).
   - Seasonal stress dummies are also shifted by one trading day
     (`research_inventory_seasonality_surprise_regime_conditiona.py:159-160`).

2. Random seed: PASS.
   - `SEED = 42` is set at
     `research_inventory_seasonality_surprise_regime_conditiona.py:20`.
   - Moving-block bootstrap uses `np.random.default_rng(SEED)`
     (`research_inventory_seasonality_surprise_regime_conditiona.py:248-293`).
   - `main()` calls `np.random.seed(SEED)`
     (`research_inventory_seasonality_surprise_regime_conditiona.py:353-354`).

3. Formal testing: PASS.
   - Predictive regressions are OOS-only from 2018-01-02 onward
     (`research_inventory_seasonality_surprise_regime_conditiona.py:189-202`).
   - Regressions use Newey-West HAC standard errors with `maxlags=5`
     (`research_inventory_seasonality_surprise_regime_conditiona.py:27`,
     `research_inventory_seasonality_surprise_regime_conditiona.py:214-215`).
   - Regime mean uncertainty uses a 1,000-rep 5-day moving-block bootstrap
     (`research_inventory_seasonality_surprise_regime_conditiona.py:28-30`,
     `research_inventory_seasonality_surprise_regime_conditiona.py:248-293`).

4. Verdict integrity: PASS.
   - The success rule is implemented as a paired commodity gate: both tickers
     in either oil or gas must have `seasonal*low_inventory` HAC t-stat > 3 for
     `PARTIAL`, and both groups must pass for `SUPPORT`
     (`research_inventory_seasonality_surprise_regime_conditiona.py:371-387`).
   - `results.json` reports `NULL`: interaction pass assets are empty and no
     group passes.
   - The positive DBA seasonal t-stat is not counted as an inventory result
     because DBA has no matched inventory proxy
     (`research_inventory_seasonality_surprise_regime_conditiona.py:172-178`,
     `research_inventory_seasonality_surprise_regime_conditiona.py:457-461`).

5. Reproducibility: PASS.
   - The script records price source, tickers, date bounds, EIA inventory URLs,
     method details, bootstrap parameters, figures, and literature references
     in the generated results object
     (`research_inventory_seasonality_surprise_regime_conditiona.py:389-475`).
   - Results are written directly from computed summaries
     (`research_inventory_seasonality_surprise_regime_conditiona.py:363-378`,
     `research_inventory_seasonality_surprise_regime_conditiona.py:476-478`).

6. Research-honesty caveats: PASS.
   - Simple returns are used instead of log returns to handle the negative WTI
     front-month settlement episode without dropping or distorting CL=F
     (`research_inventory_seasonality_surprise_regime_conditiona.py:149-153`).
   - The script explicitly states that this is a forward-RV diagnostic and not
     a tradable futures inventory-surprise strategy
     (`research_inventory_seasonality_surprise_regime_conditiona.py:457-461`).

## Residual Risk

The 7-day EIA delay is conservative but not a precise historical release
calendar. Futures front-month rolls from yfinance can add roll artifacts. DBA is
only a seasonality placebo; a serious agriculture inventory test would require
crop-specific report dates and inventory/supply surprise series.
