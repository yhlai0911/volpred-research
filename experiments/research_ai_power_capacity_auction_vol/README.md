# AI Power Capacity Auction Volatility Event Study

## Purpose

This experiment tests a narrow follow-up to K1508. K1508 found no broad
post-ChatGPT utility/grid ETF relative-volatility regime break. This run asks a
more specific question: did official PJM/MISO capacity-auction result
announcements produce unusually large next-day volatility in public-market
power proxies?

The task was motivated by the AI electricity-supercycle narrative: IEA (2025)
projects a sharp rise in data-centre electricity demand, while PJM capacity
prices moved from about `$28.92/MW-day` for 2024/2025 to `$329.17/MW-day` for
2026/2027. This experiment does not claim AI causality; it tests whether the
auction announcements themselves line up with equity-volatility shocks.

## Data

- Price source: yfinance adjusted close.
- Sample: 2020-01-02 through 2026-07-01.
- Groups:
  - Utility ETFs: `XLU`, `VPU`
  - IPP / capacity winners: `VST`, `CEG`, `NRG`
  - Uranium proxy: `URA`
  - Market control: `SPY`, `QQQ`
- Event count: 8 PJM/MISO capacity-auction result announcements.
- Random seed: `42`.

Demand-growth reports from LBNL, IEA, and DOE are used as context only. They are
not treated as capacity-auction shock events in the primary test.

## Method

The primary target is the next trading day after the official auction-result
announcement. Same-day ratios are reported as descriptive diagnostics only,
because announcement times are not standardized in the script and some releases
may occur after the market close.

Daily volatility proxy:

```text
rv_t = log_return_t^2
rv_ratio_t = rv_t / median(rv_{t-252} ... rv_{t-1})
```

The baseline is explicitly lagged:

```python
rv.shift(1).rolling(252, min_periods=126).median()
```

For each group and event, the script averages ticker-level next-day `rv_ratio`.
It compares the event mean with 5,000 random non-event trading-date samples
matched by event calendar year. Random candidates exclude a +/-5 trading-day
blackout around the true event dates.

Primary PASS gate: `utility_etf` or `ipp_capacity` must have mean next-day RV
ratio above `2.0`, bootstrap upper-tail `p < 0.05`, and mean next-day RV ratio at
least `0.25` above the same-event market group.

## Result

Verdict: **NULL_NO_ROBUST_CAPACITY_AUCTION_VOL_SPIKE**.

No group passed the primary gate.

| Group | Mean next-day RV ratio | Bootstrap p_upper | Minus market | Gate |
|---|---:|---:|---:|---|
| utility_etf | 3.34 | 0.2452 | 0.42 | fail |
| ipp_capacity | 12.58 | 0.0524 | 9.66 | fail |
| uranium | 2.83 | 0.3965 | -0.09 | not primary |
| market | 2.92 | 0.4971 | 0.00 | control |

Interpretation: IPP names show a large directional next-day volatility spike,
especially around the 2024-07-30 PJM 2025/2026 auction result, but the
year-matched bootstrap misses the pre-specified 5% gate (`p_upper=0.0524`). This
is a near miss and a candidate for a richer exposure-based event study, not a
publishable PASS claim.

## Outputs

- `research_ai_power_capacity_auction_vol.py`
- `research_ai_power_capacity_auction_vol_results.json`
- `data/close_panel.csv`
- `data/capacity_auction_event_asset_panel.csv`
- `data/capacity_auction_event_group_panel.csv`
- `figures/capacity_auction_next_day_rv_ratio.png`
- `codex_review.md`

## Limitations

- Daily closes are too coarse for intraday announcement-time alignment.
- The event list is small, so bootstrap p-values are screening evidence.
- `XLU`, `VPU`, `VST`, `CEG`, `NRG`, and `URA` are proxies; the script does not
  map company revenue or load exposure to PJM/MISO zones.
- Capacity-auction price changes are not pure AI shocks; retirements, fuel
  prices, reliability rules, load forecasts, and local constraints also matter.
