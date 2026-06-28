# Codex Review: K1556

Verdict: `PASS_AS_NULL_PROXY_WITH_CAVEATS`

## Scope Reviewed

- `experiments/k1556/README.md`
- `experiments/k1556/k1556.py`
- `experiments/k1556/k1556_results.json`
- Generated data snapshots under `experiments/k1556/data/`

## Checks

1. **Experiment artifact completeness: PASS**
   - Required triplet exists: README, script, results JSON.
   - Additional trace files exist: price cache, FRED calendar cache, mapped
     release events, daily features, and chart.

2. **Data-source honesty: PASS_WITH_CAVEAT**
   - The script uses FRED release calendar pages for CPI, Employment Situation,
     and GDP.
   - A live check showed those public pages return 2025-2026 schedules in this
     context, not a complete historical archive. The script therefore restricts
     formal event/control analysis to `ANALYSIS_START = 2025-01-01` and keeps
     2014-2024 prices only for rolling baselines.
   - This is a valid free-data proxy diagnostic, but the sample is small:
     50 distinct release days and 227 control days after exclusions.

3. **Surprise proxy: PASS_WITH_CAVEAT**
   - No paid actual-minus-consensus data is used or claimed.
   - The FRED macro proxy is explicitly labeled
     `actual-minus-trailing-nowcast; not paid consensus or real-time vintage`.
   - GDP values are current-vintage FRED data, so they are unsuitable for a
     strong real-time surprise claim. The README states this limitation.

4. **Lookahead and timing: PASS**
   - Event-day cojump tests are explicitly described as contemporaneous response
     diagnostics, not tradable predictions.
   - Predictive/persistence signals use explicit lags:
     `macro_release_signal = macro_release_day.shift(1)`,
     `macro_abs_surprise_signal = macro_abs_surprise_proxy.shift(1)`, and
     `macro_market_abs_signal = macro_market_abs_proxy.shift(1)`.
   - Return/VIX/RV z-score baselines use rolling windows shifted by one day.

5. **Statistical interpretation: PASS**
   - The result is correctly classified as `NULL_PROXY`.
   - No event-day statistic clears `|t| >= 3`.
   - No country ETF beta-interaction clears `t >= 3`.
   - Lagged t+5 RV persistence is negative, not positive, and fails the strict
     gate despite a negative bootstrap CI.

## Key Result Consistency

- Release-day cojump count: +0.17 vs control, Welch t=0.68.
- Release-day average country `|ret_z|`: +0.18 vs control, Welch t=1.54.
- VIX jump z: +0.16 vs control, Welch t=1.05.
- Post-release next-5d RV z: -0.35 vs control, Welch t=-2.06.
- Strongest beta amplification: EFA +0.257, t=2.06.

## Publication Guidance

Do not publish this as positive evidence for the REStud mechanism. The honest
claim is narrower: daily USD-listed ETF close-to-close data with a free
FRED-calendar/trailing-nowcast proxy does not robustly recover the intraday
global macro-news cojump mechanism; richer intraday data and true consensus
surprises are required for a stronger test.
