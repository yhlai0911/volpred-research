# Codex Review - research_vrp_vrp_horizon

Review date: 2026-06-15

Reviewer: Codex

## Verdict

Experiment integrity: PASS

Research hypothesis: NULL

The implementation is reproducible from yfinance SPY/^VIX data, uses explicit
one-day lags for all VRP predictors, applies HAC lags appropriate for
overlapping forward horizons, fixes the random seed, and does not overclaim the
free-data semivariance split as a true option-implied downside/upside VRP
decomposition.

## Checklist

1. Lookahead bias: PASS.
   - yfinance SPY/^VIX adjusted close is downloaded and cached at
     `research_vrp_vrp_horizon.py:65-77`.
   - Total implied variance is shifted by one trading day:
     `iv_total_lag1 = ... .shift(1)` at `research_vrp_vrp_horizon.py:105`.
   - Trailing total/down/up realized variance legs are shifted by one trading
     day at `research_vrp_vrp_horizon.py:106-108`.
   - The 252-day downside semivariance share is shifted before it is used to
     split VIX implied variance (`research_vrp_vrp_horizon.py:110-117`).
   - The predictive controls include lagged 21-day return at
     `research_vrp_vrp_horizon.py:122-123`.
   - Forward targets start at `t+1`, not same-day, via `shift(-step)` for
     `step` from 1 to horizon (`research_vrp_vrp_horizon.py:80-88`,
     `research_vrp_vrp_horizon.py:125-128`).

2. Random seed: PASS.
   - `SEED = 42` is set at `research_vrp_vrp_horizon.py:20`.
   - Moving-block bootstrap uses `np.random.default_rng(SEED)`
     (`research_vrp_vrp_horizon.py:200-219`).
   - `main()` calls `np.random.seed(SEED)`
     (`research_vrp_vrp_horizon.py:265-267`).

3. HAC and overlapping horizons: PASS.
   - Mean tests use HAC standard errors (`research_vrp_vrp_horizon.py:135-146`).
   - Predictive regressions use Newey-West HAC with `maxlags` passed in
     (`research_vrp_vrp_horizon.py:149-167`).
   - The horizon loop passes `hac_lags=horizon`, so 21/63/126-day overlapping
     targets use HAC(21), HAC(63), and HAC(126)
     (`research_vrp_vrp_horizon.py:283-290`).

4. Verdict integrity: PASS.
   - The success gate is pre-specified in code and requires the sign gate plus
     medium-horizon return and RV gates for SUPPORT
     (`research_vrp_vrp_horizon.py:295-318`).
   - The reported verdict is NULL. The downside-minus-upside spread has HAC
     t=0.877 and bootstrap CI crossing zero, so the sign gate fails.
   - The best medium-horizon downside return t-stat is 2.265 at 63 days, below
     the t>3 gate. Medium-horizon RV t-stats are negative for downside VRP.
   - The README states the positive component means but does not convert them
     into a dominance or tradable prediction claim.

5. Reproducibility: PASS.
   - Results record the data source, tickers, date range, analysis start,
     method details, bootstrap settings, literature, figures, and research
     honesty notes (`research_vrp_vrp_horizon.py:320-393`).
   - Results are written directly from computed objects at
     `research_vrp_vrp_horizon.py:395-397`.

6. Proxy limitation: PASS.
   - The script explicitly documents that VIX provides only total implied
     variance and that the down/up split uses lagged realized semivariance
     shares (`research_vrp_vrp_horizon.py:114-117`,
     `research_vrp_vrp_horizon.py:334-340`).
   - Research honesty notes state that this is not a true option-implied
     downside/upside variance decomposition
     (`research_vrp_vrp_horizon.py:375-380`).

## Residual Risk

The main limitation is data design, not coding integrity. VIX gives total
30-calendar-day implied variance only, so allocating it by realized
semivariance shares may miss option-market skew pricing. A real follow-up would
need option-chain or model-free downside/upside variance-swap data and explicit
horizon-matched implied measures.
