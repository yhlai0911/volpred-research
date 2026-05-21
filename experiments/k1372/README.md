# K1372: BTC Halving Volatility Event Study

**Experiment ID**: K1372
**Status**: completed
**Created At**: 2026-05-17T11:15:33Z
**Member Question Source**: uq_mock1 (score 82/100)

---

## Research Question

BTC 半減期前後的波動率是否有可預測的 pattern？GARCH 能否捕捉？

## Motivation

This experiment addresses a high-scoring member question (82/100) about whether Bitcoin halving events create predictable volatility regimes. The hypothesis is that the supply shock from halving—combined with heightened speculative attention—might cause a systematic pre-halving volatility spike followed by post-halving mean reversion (or vice versa). GJR-GARCH(1,1)-t is used to model conditional volatility and compared with 20-day rolling realized volatility across ±90-day event windows around each halving.

## Method

- **Asset**: BTC-USD daily (2014-09-17 to 2025-12-30; yfinance earliest available)
- **Returns**: Log returns, n=4,122 observations
- **Halvings analyzed**: H2 (2016-07-09), H3 (2020-05-11), H4 (2024-04-19). H1 (2012-11-28) excluded — before data window.
- **Model**: GJR-GARCH(1,1) with Student-t errors (appropriate for BTC's heavy tails; nu≈3.2)
- **Event window**: [-90, +90] trading days per halving
- **Realized vol**: 20-day rolling std of log returns × √252
- **Per-halving test**: Mann-Whitney U (pre 90 obs vs post 90 obs realized vol, two-sided)
- **Aggregate test**: Wilcoxon signed-rank on N=3 post-minus-pre differences

## Key Findings

### GJR-GARCH(1,1)-t Parameters (full sample)

| Parameter | Value |
|-----------|-------|
| omega     | 0.1693 |
| alpha     | 0.1137 |
| gamma     | -0.0198 |
| beta      | 0.8963 |
| nu (t df) | 3.21 |
| Log-lik   | -10,159.8 |

The asymmetry parameter gamma is negative and insignificant (p=0.30), suggesting no classical leverage effect for BTC — positive and negative shocks affect future volatility similarly.

### Event Window Results

| Halving | Date       | Pre Vol (mean) | Post Vol (mean) | Change   | MW U  | MW p    |
|---------|------------|----------------|-----------------|----------|-------|---------|
| H2 2016 | 2016-07-09 | 0.406          | 0.296           | -0.110   | 4,997 | 0.0068  |
| H3 2020 | 2020-05-11 | 0.833          | 0.409           | -0.423   | 6,042 | <0.001  |
| H4 2024 | 2024-04-19 | 0.475          | 0.379           | -0.097   | 5,649 | <0.001  |

All three halvings show **post-halving volatility is LOWER than pre-halving**. Each individual halving shows a statistically significant reduction in realized vol (MW test, all p<0.01). However, the direction is the opposite of a "volatility spike around halving" narrative — volatility tends to be elevated before the halving and decays afterward.

### Aggregate Test

- Post-minus-pre differences: [-0.110, -0.423, -0.097]
- Mean difference: -0.210 (annualized vol units)
- Wilcoxon signed-rank (N=3): stat=0.0, p=0.25

The aggregate Wilcoxon test is non-significant (p=0.25), which is expected given N=3. With only 3 halvings, the test has near-zero statistical power — Wilcoxon with N=3 can only achieve p=0.25 (minimum possible two-sided p-value).

### GARCH Conditional Vol

GARCH conditional volatility tracks the same pattern as realized vol: elevated pre-halving (especially H3 2020, driven by COVID-19 crash in March 2020), declining post-halving. GARCH does capture the broad regime shifts but cannot distinguish halving-specific patterns from concurrent macro events.

## Verdict: EXPLORATORY_NULL (insufficient power)

The data consistently show post-halving vol is LOWER than pre-halving across all three halvings. However:

1. N=3 halvings → near-zero aggregate statistical power (Wilcoxon p=0.25 minimum achievable)
2. H3 2020 pre-period coincides with COVID-19 crash (March 2020) — the high pre-halving vol may be COVID-driven, not halving-anticipation
3. No causal identification: the pattern is observationally consistent with "buy the rumor, sell the news" vol dynamics, but confounders abound
4. GARCH captures realized vol levels well but offers no unique predictive signal beyond standard time-series vol clustering

**Honest answer to the member question**: There is a consistent descriptive pattern of post-halving vol declining, but with N=3 and substantial confounders, this cannot be claimed as statistically reliable or predictable. GARCH adds descriptive value but does not uniquely capture halving-specific patterns. More halvings are needed for any inference.

## Anti-Lookahead Note

GARCH is estimated over the full sample for **descriptive purposes only**. No trading signal is implied. For each event window, only historical data from that actual period is used — no future information enters the event-window realized vol computation.

## Power Caveat

N=3 halvings means any aggregate test is near-powerless. The pattern (all three halvings show lower post-vol) is directionally consistent but cannot be distinguished from chance at conventional significance levels. Results are strictly exploratory.

## Files

- `k1372.py` — Main experiment script
- `k1372_results.json` — Full results (GARCH params, per-halving tests, aggregate test)
- `k1372_event_windows.png` — ±90 day realized + GARCH vol around each halving
- `k1372_vol_comparison.png` — Pre vs post realized vol bar chart with significance markers
