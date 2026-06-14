# Codex Review - research_conditional_expected_drawdown_ced_vt

Review date: 2026-06-15

Reviewer: Codex

## Verdict

Experiment integrity: PASS

Research hypothesis: NULL

The implementation is reproducible from the script plus yfinance adjusted OHLC
data, uses explicit signal lagging, fixes the random seed, and reports a NULL
result rather than overclaiming CED as an improved risk target.

## Checklist

1. Lookahead bias: PASS.
   - yfinance adjusted OHLC is downloaded before signal construction
     (`research_conditional_expected_drawdown_ced_vt.py:69-83`).
   - Daily low returns are computed as adjusted Low divided by previous adjusted
     Close (`research_conditional_expected_drawdown_ced_vt.py:311-315`).
   - The realized-vol baseline exposure is explicitly lagged:
     `vol_exposure = vol_exposure_raw.shift(1)`
     (`research_conditional_expected_drawdown_ced_vt.py:319-321`).
   - Each CED exposure is explicitly lagged:
     `exposure = exposure_raw.shift(1)`
     (`research_conditional_expected_drawdown_ced_vt.py:326-333`).
   - CED signals are trailing-window estimates. The rolling loop only uses
     observations inside the lookback window ending at the current index before
     the exposure is shifted (`research_conditional_expected_drawdown_ced_vt.py:117-139`).

2. Random seed: PASS.
   - Global seed is defined at `research_conditional_expected_drawdown_ced_vt.py:24`.
   - Bootstrap sampling uses `np.random.default_rng(SEED)`
     (`research_conditional_expected_drawdown_ced_vt.py:228-233`).
   - `main()` also sets `np.random.seed(SEED)`
     (`research_conditional_expected_drawdown_ced_vt.py:306-308`).

3. Formal comparison: PASS.
   - OOS comparison uses paired moving-block bootstrap, not only charts
     (`research_conditional_expected_drawdown_ced_vt.py:228-266`).
   - Bootstrap block length is 21 trading days, matching the short horizon of
     overlapping risk windows (`research_conditional_expected_drawdown_ced_vt.py:40-41`).
   - The verdict gate requires drawdown, Calmar, Sharpe, and left-tail checks
     rather than selecting the best single metric (`research_conditional_expected_drawdown_ced_vt.py:363-375`).

4. OHLC usage: PASS with limitation.
   - The CED path incorporates intraday low information through
     `horizon_path_drawdown()` (`research_conditional_expected_drawdown_ced_vt.py:104-114`).
   - Limitation: basket low return is approximated as the average constituent
     low return (`research_conditional_expected_drawdown_ced_vt.py:314-315`),
     not as an exact intraday synchronized portfolio low.

5. Verdict integrity: PASS.
   - The script initializes verdict to `NULL` and only upgrades it if the
     pre-specified gate passes (`research_conditional_expected_drawdown_ced_vt.py:363-375`).
   - `results.json` reports no winning variants and the plain-English NULL
     statement. This matches the metrics: CED20 and CED60 both have worse OOS
     MDD, Calmar, and left-tail day counts than the vol target.

6. Reproducibility: PASS.
   - Data source, tickers, date bounds, cached OHLC directory, transaction cost,
     bootstrap parameters, and figure names are written to results
     (`research_conditional_expected_drawdown_ced_vt.py:376-419`).
   - The script writes `research_conditional_expected_drawdown_ced_vt_results.json`
     directly from computed objects (`research_conditional_expected_drawdown_ced_vt.py:456-458`).

## Residual Risk

The experiment uses ETF adjusted daily OHLC, so it cannot reconstruct
sub-day portfolio lows exactly. That is acceptable for this backlog task because
the stated test is a daily OHLC practitioner proxy, but any production strategy
claim should be retested with synchronized intraday data.
