# Codex Review - research_intraday_vs_overnight_vrp

Review date: 2026-06-15

Reviewer: Codex

## Verdict

Experiment integrity: PASS

Research hypothesis: NULL

The implementation is reproducible from yfinance adjusted OHLC plus the script,
uses explicit one-day lags for predictive features, fixes the random seed, and
does not overclaim the yfinance-only proxy as true option-implied VRP.

## Checklist

1. Lookahead bias: PASS.
   - yfinance adjusted OHLC is downloaded and cached in
     `research_intraday_vs_overnight_vrp.py:62-76`.
   - Overnight returns use `Open_t / Close_{t-1}` and close-to-close returns use
     `Close_t / Close_{t-1}` at `research_intraday_vs_overnight_vrp.py:113-118`.
   - GARCH one-step forecasts are documented and implemented so the forecast
     for day `t` uses returns through `t-1`
     (`research_intraday_vs_overnight_vrp.py:79-110`).
   - The trailing 252-day component allocation is shifted by one day:
     `overnight_share_lag1 = share_raw.shift(1)`
     (`research_intraday_vs_overnight_vrp.py:136-145`).
   - Predictive features are explicitly shifted:
     `overnight_pseudo_vrp.shift(1)`, `intraday_pseudo_vrp.shift(1)`,
     `log_session_var.shift(1)`, and `log_garch_total_var.shift(1)`
     (`research_intraday_vs_overnight_vrp.py:149-154`).

2. Random seed: PASS.
   - `SEED = 42` is set at `research_intraday_vs_overnight_vrp.py:28`.
   - Moving-block bootstrap uses `np.random.default_rng(SEED)`
     (`research_intraday_vs_overnight_vrp.py:167-175`).
   - `main()` also calls `np.random.seed(SEED)`
     (`research_intraday_vs_overnight_vrp.py:314-316`).

3. Formal testing: PASS.
   - OOS share uncertainty uses a 1,000-rep 21-day moving-block bootstrap
     (`research_intraday_vs_overnight_vrp.py:35-40`,
     `research_intraday_vs_overnight_vrp.py:159-199`).
   - Predictive regressions use Newey-West HAC standard errors with `maxlags=5`
     (`research_intraday_vs_overnight_vrp.py:209-231`).
   - The success rule is pre-specified in code and requires both overnight
     majority and predictive strength in at least 3 of 4 assets
     (`research_intraday_vs_overnight_vrp.py:321-336`).

4. Verdict integrity: PASS.
   - `results.json` reports `NULL`, only EFA passes the overnight-majority leg,
     and no asset passes the lagged overnight pseudo-VRP t-stat leg.
   - The script's plain-English verdict says the OHLC-only pseudo-VRP proxy does
     not support the broad overnight-dominance plus prediction claim
     (`research_intraday_vs_overnight_vrp.py:417-428`).

5. Reproducibility: PASS.
   - Results include source, tickers, date bounds, method parameters, bootstrap
     parameters, figures, and literature references
     (`research_intraday_vs_overnight_vrp.py:338-416`).
   - Outputs are written directly from computed objects:
     `research_intraday_vs_overnight_vrp.py:430-432`.

6. Research-honesty caveat: PASS.
   - The script explicitly states that daily yfinance OHLC cannot identify true
     option-implied VRP and that the measured object is pseudo-VRP
     (`research_intraday_vs_overnight_vrp.py:1-8`,
     `research_intraday_vs_overnight_vrp.py:358-360`,
     `research_intraday_vs_overnight_vrp.py:412-416`).

## Residual Risk

This experiment cannot adjudicate the true Papagelis-Dotsis option-implied
VRP result because it lacks option-chain data. It is only a free-data diagnostic
showing that an OHLC plus GARCH proxy is insufficient for a broad overnight-VRP
dominance claim.
