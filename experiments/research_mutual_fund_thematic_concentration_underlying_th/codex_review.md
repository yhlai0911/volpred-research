# Codex Review

Reviewer: Codex
Date: 2026-07-03
Experiment: `research_mutual_fund_thematic_concentration_underlying_th`

## Verdict

**CONDITIONAL_PASS_SOURCE_REVIEW / research verdict PASS_ETF_PROXY**

The implementation is reproducible and the ETF-proxy result passes the stated
stock-level gate. The conclusion must remain strictly scoped: this is not a
mutual-fund thematic concentration index replication, and it does not establish
a tradable holdings-history signal.

## Checks

- Experiment triplet present:
  - `README.md`
  - `research_mutual_fund_thematic_concentration_underlying_th.py`
  - `research_mutual_fund_thematic_concentration_underlying_th_results.json`
- Data sources are explicit:
  - yfinance `funds_data.top_holdings` for current thematic ETF top holdings.
  - yfinance adjusted closes and volumes for ETFs and current top holdings.
  - Literature context includes RFS thematic concentration, SEC N-PORT data, and
    FAJ thematic-risk framing.
- Lookahead controls:
  - Current ETF holdings are disclosed as ex-post basket definitions only.
  - ETF dollar-volume attention is rolling-z transformed and shifted one trading
    day.
  - Forward RV/downside targets begin at t+1.
  - Lagged 63d baselines and lagged recent 5d RV control are shifted before the
    target window.
- Gate logic:
  - Primary gate is stock-level only.
  - PASS requires positive pressure coefficient, clustered t-stat >= 3, and
    positive high-minus-low Welch t-stat >= 3.
  - ETF-level pass cells are auxiliary and do not broaden the claim.
- Corrections made during review:
  - Added lagged recent 5d RV control to reduce mechanical volatility-clustering
    explanation from ETF volume attention.
  - Fixed multi-header yfinance price-cache reader.
  - Preserved ex-post holdings caveat in README and results limitations.

## Result Snapshot

- Overall verdict: `PASS_ETF_PROXY`.
- Stock-level gate pass count: `4/4`.
- ETF-level auxiliary pass count: `4/4`.
- Thematic ETFs with usable U.S. top holdings: `16`.
- Top-holding rows used: `122`.
- Unique underlying symbols: `76`.
- Strongest stock cell: 5d downside beta `0.10875`, clustered t=`7.0006`,
  p=`2.55e-12`, high-low Welch t=`7.0973`.
- 5d stock RV: beta `0.03862`, clustered t=`5.2349`.
- 22d stock RV: beta `0.03200`, clustered t=`3.9769`.
- 22d stock downside: beta `0.05025`, clustered t=`5.4840`.

## Limitations

- Current holdings snapshots create ex-post basket-definition bias.
- yfinance top holdings are incomplete relative to full N-PORT holdings.
- ETF dollar-volume attention can still reflect theme news, market making, or
  volatility clustering rather than pure fund crowding.
- The design uses `QQQ` residual returns, not a full factor model.
- A mutual-fund TCI claim requires historical N-PORT holdings or author TCI data.

No blocking source-level defect remains if downstream language says
`ETF proxy PASS` and does not call this a mutual-fund TCI replication.
