# Index Inclusion Event Study: Stock, Sector, and Peer RV

## Purpose

This experiment tests whether large U.S. index-inclusion events are followed by
detectable changes in realized volatility, jump frequency, and same-sector
return co-movement for:

- the included stock,
- the corresponding sector ETF,
- a hand-built same-sector peer set.

The task was motivated by 2026 index-methodology discussion around mega-cap IPOs
and fast-entry mechanisms. The realized sample is deliberately framed as a
recent inclusion/reconstitution proxy, not as a direct 2026 mega-IPO fast-entry
test. By 2026-06-24, S&P DJI had publicly declined to add a mega-cap-only
fast-track rule, and Nasdaq's 2026 fast-entry rule did not yet provide a rich
realized event sample with post-inclusion price history.

## Pre-Experiment Context

Relevant internal context checked before design:

- `docs/error_log.md`: event-window designs must avoid centered or
  forward-looking rolling statistics.
- `storage/memory/knowledge.json`: no direct prior K item on index-inclusion
  fast-entry RV spillovers; adjacent work includes sector-vol and ETF
  liquidity-clientele diagnostics.
- `research_program.md`: backlog line for index inclusion fast-entry mechanism
  event study.
- `.claude/skills/autonomous-research/references/experiment-preamble.md`.

References checked before design:

- MacKinlay (1997), "Event Studies in Economics and Finance."
- Harris and Gurel (1986), "Price and Volume Effects Associated with Changes in
  the S&P 500 List."
- Shleifer (1986), "Do Demand Curves for Stocks Slope Down?"
- S&P DJI June 2026 consultation result on treatment of mega-cap companies.
- Nasdaq-100 Index May 2026 fast-entry methodology FAQ.
- iShares 2026 discussion of mega-cap AI IPOs, ETFs, and index inclusion.

## Data

Market data are yfinance adjusted close series downloaded with
`auto_adjust=True`.

- Download window: `2023-01-01` to `2026-06-24` exclusive.
- Realized return window after differencing: 2023-01-04 to 2026-06-23.
- Candidate events: 16.
- Valid events after data filters: 16.
- Event dates: 2024-03-18, 2024-06-24, 2024-09-23, 2024-12-23, 2025-03-24,
  2025-05-19.
- Index split: 13 S&P 500 additions and 3 Nasdaq-100 annual reconstitution
  additions.

Primary event sources:

- S&P DJI 2024-03-01: SMCI and DECK set to join S&P 500.
- S&P DJI 2024-06-07: KKR, CRWD, and GDDY set to join S&P 500.
- S&P DJI 2024-09-06: PLTR, DELL, and ERIE set to join S&P 500.
- Invesco QQQ/Nasdaq-100 reconstitution summary for PLTR, MSTR, and AXON.
- S&P DJI 2025-03-07: DASH, TKO, WSM, and EXE set to join S&P 500.
- S&P DJI 2025-05-12: COIN set to join S&P 500.

## Method

For each event, the effective inclusion date is treated as event day 0.

- Pre window: trading days `[-30, -1]`.
- Short post window: `[0, +20)`.
- Full post window: `[0, +60)`.
- Normalization and jump thresholds use only the pre-event window.
- Jump threshold: absolute daily log return above two times the pre-event daily
  standard deviation.
- RV: mean squared daily log return annualized by 252.
- Peer RV: average RV across valid same-sector peers.
- Correlation: average pairwise correlation among the included stock and valid
  same-sector peers.
- Cross-sectional dispersion: average daily cross-sectional return variance
  among the included stock and valid same-sector peers, annualized.

This is not a predictive trading strategy. No event signal is multiplied by
same-day returns. The anti-lookahead guard is the event-window split itself:
pre-event denominators and thresholds exclude event-day and post-event returns.

## Formal Tests

The primary metric is:

```text
log(included stock post60 RV / included stock pre RV)
- log(peer average post60 RV / peer average pre RV)
```

Secondary metrics include included-stock RV log ratio, sector ETF RV log ratio,
peer average RV log ratio, jump-rate delta, pairwise-correlation delta, and
cross-sectional-dispersion log ratio.

For each metric:

- event-level mean, median, standard deviation, and t-statistic;
- event-level bootstrap 95% confidence interval with seed 42;
- event-date clustered bootstrap 95% confidence interval as a dependence
  sensitivity.

Evidence for a positive event diagnostic requires:

- primary metric mean > 0,
- primary metric t-stat > 3,
- primary bootstrap lower bound > 0,
- at least one corroborating jump or correlation metric with comparable support.

## Run

```bash
uv run python experiments/research_index_inclusion_fast_entry_mechanism_sector_rv/research_index_inclusion_fast_entry_mechanism_sector_rv.py
```

## Required Outputs

- `README.md`
- `research_index_inclusion_fast_entry_mechanism_sector_rv.py`
- `research_index_inclusion_fast_entry_mechanism_sector_rv_results.json`
- `results.json`
- `per_event_table.csv`
- `event_window_panel.csv`
- `summary_table.csv`
- `figures/event_window_normalized_sqret.png`
- `figures/summary_event_effects.png`
- `figures/per_event_stock_minus_peer_rv.png`
- `codex_review.md`

## Results

Final run: 2026-06-24 local session.

Aggregate verdict: `weak_or_mixed_event_diagnostic`.

Key results:

| Metric | N | Mean | t-stat | Bootstrap 95% CI | Date-cluster CI |
|---|---:|---:|---:|---:|---:|
| Included stock RV log ratio, post60/pre | 16 | 0.0566 | 0.39 | [-0.2313, 0.3242] | [-0.2719, 0.3063] |
| Peer RV log ratio, post60/pre | 16 | 0.0459 | 0.32 | [-0.2263, 0.3183] | [-0.3861, 0.3464] |
| Included stock minus peer RV log ratio | 16 | 0.0107 | 0.07 | [-0.2753, 0.3396] | [-0.1544, 0.2012] |
| Included stock jump-rate delta | 16 | 0.0219 | 1.37 | [-0.0073, 0.0531] | [-0.0060, 0.0511] |
| Pairwise-correlation delta | 16 | 0.0568 | 1.64 | [-0.0103, 0.1230] | [-0.0338, 0.1411] |
| Cross-sectional dispersion log ratio | 16 | -0.0809 | -0.60 | [-0.3261, 0.1849] | [-0.4494, 0.2725] |

The included stocks do not show a robust RV increase relative to their
same-sector peers. The primary differential is nearly zero and fails both the
event-level t-stat gate and the bootstrap interval gate. Jump frequency and
pairwise correlation have positive means, but their confidence intervals cross
zero and their t-statistics are far below the Harvey-style threshold.

Interpretation: recent large index-inclusion and Nasdaq-100 reconstitution
events show weak/mixed descriptive diagnostics, not a publishable claim that
index inclusion mechanically raises stock-specific or sector-peer RV over the
next 60 trading days.

## Data Notes

- yfinance returned no usable adjusted-close series for `PARA` and `SKX` in
  this run; both were optional peers and were dropped by the peer validity
  filter. All 16 candidate events still had at least 7 valid peers.
- Nasdaq-100 events are annual reconstitution additions, not fast-entry events.
- `MSTR` peer selection mixes software, crypto-linked equities, and brokerage
  proxies because its business exposure is unusual.

## Interpretation Limits

- This is not a causal fast-entry rule test. It is a recent-public-event proxy
  study motivated by the fast-entry discussion.
- Same-sector peer sets are manual public proxies, not official GICS peer
  universes.
- Daily close-to-close returns cannot isolate closing-auction pressure,
  ETF-create/redeem flow, securities lending, or intraday liquidity.
- Several events share the same effective dates, so event-level t-tests can
  overstate independence; date-cluster bootstrap intervals are reported as a
  sensitivity.
- The sample is small and concentrated in 2024-2025 U.S. large-cap additions.
