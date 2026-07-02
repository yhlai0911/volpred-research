# K1604 — Sports-betting launch shocks and gambling-stock RV

## Motivation

The 2026-07-01 journal-discovery backlog asked whether **sports-betting
legalization / betting-handle shocks** pull retail risk budget away from financial
markets and amplify realised volatility in gambling-related equities.

This is deliberately different from **K1361**. K1361 tested whether public gaming /
betting baskets transmit volatility to QQQ / ARKK / BTC / SPY in a continuous VAR /
connectedness setup. K1604 tests a narrower event-study question:

> After large U.S. online sports-betting launch dates, do public gambling /
> sportsbook equities show abnormal T+5 or T+22 realised volatility and volume
> relative to broad risk-on controls?

## Literature Checked

- Hollenbeck, Larsen & Proserpio, NBER working paper `w33108`, "Gambling Away
  Stability: Sports Betting's Impact on Vulnerable Households":
  <https://www.nber.org/papers/w33108>
- NBER working paper `w35305`, "Sports Betting Legalization and Food Sufficiency":
  <https://www.nber.org/papers/w35305>
- American Gaming Association state-of-play map / legal landscape:
  <https://www.americangaming.org/research/state-of-play-map/>
- CBS Sports state-by-state sports betting tracker:
  <https://www.cbssports.com/betting/news/u-s-sports-betting-where-all-50-states-stand-on-legalizing-online-sports-betting-sites-proposed-legislation/>
- SportsBettingDime state-by-state legal timeline tracker:
  <https://www.sportsbettingdime.com/guides/legal/sports-betting-state-by-state-legal-tracker/>

The household-finance papers motivate the crowd-out channel. The legal trackers are
used only to manually curate launch dates; they are not treated as an official legal
database.

## Design

- **Events:** major U.S. online/mobile sports-betting launch dates after PASPA.
  Retail-only launches are excluded unless statewide online access began on the same
  date.
- **Betting basket:** `DKNG`, `PENN`, `MGM`, `CZR`, `RSI`, `GENI`, `SRAD`, `BETZ`.
- **Controls:** `SPY`, `IWM`, `QQQ`.
- **Data:** yfinance adjusted close and volume, cached under `data/`.
- **Event windows:**
  - Baseline: trading days `T-30..T-6`.
  - Outcomes: `T+1..T+5` and `T+1..T+22`.
  - `T` is the first trading day on or after the legal launch date.
- **Metric:** event-level equal-weighted betting-basket log ratio minus control-basket
  log ratio. Primary metric is adjusted `post5_rv_log_ratio`.
- **Inference:** one-sample test on event-level differentials; seeded event bootstrap
  CI; same-year matched random-anchor placebo for the primary T+5 RV metric.

## Event Set

The script currently uses 23 online/mobile launch dates:

`NJ 2018-08-06`, `PA 2019-05-31`, `IA 2019-08-15`, `IN 2019-10-03`,
`NH 2019-12-30`, `CO 2020-05-01`, `IL 2020-06-18`, `TN 2020-11-01`,
`VA 2021-01-21`, `MI 2021-01-22`, `AZ 2021-09-09`, `CT 2021-10-19`,
`NY 2022-01-08`, `LA 2022-01-28`, `KS 2022-09-01`, `MD 2022-11-23`,
`OH 2023-01-01`, `MA 2023-03-10`, `KY 2023-09-28`, `ME 2023-11-03`,
`VT 2024-01-11`, `NC 2024-03-11`, `MO 2025-12-01`.

Events are skipped automatically if the yfinance panel does not have enough
pre/post trading days.

## Anti-Lookahead / Reproducibility

- Event dates are fixed before return outcomes are measured.
- All post outcomes begin on the **next trading day** after launch; same-day event
  returns are not used.
- The statistical unit is the event-level basket differential, not pooled
  ticker-event rows.
- Random procedures use `SEED = 42`.

## Success Criteria

Primary PASS requires all of:

- adjusted T+5 RV log ratio mean > 0,
- event-bootstrap 95% CI excludes 0,
- one-sample `t >= 3`,
- matched random-anchor `p_upper < 0.05`.

If the primary test does not pass, the result is `NULL` or `SUGGESTIVE`; secondary
volume or T+22 RV metrics cannot rescue the primary claim.

## Results — 2026-07-02 run

- **Data:** yfinance adjusted close and volume, 2018-01-02 to 2026-07-01.
  All 8 betting tickers and 3 controls downloaded successfully.
- **Events used:** 23 / 23 launch dates had enough pre/post data. Early events use
  the then-listed casino/gambling names (`PENN`, `MGM`, `CZR`) before newer
  sportsbook pure plays become public.
- **Primary T+5 RV result:** `NULL`. Adjusted betting-minus-control RV log ratio
  mean is `+0.0167`, one-sample `t=0.30`, Student-t `p=0.767`, event-bootstrap
  95% CI `[-0.0904, +0.1224]`. The same-year matched random-anchor placebo has
  `p_upper=0.407`, so the observed mean is ordinary relative to non-event anchors.
- **T+22 RV:** directionally positive but weak: mean `+0.0797`, `t=1.33`,
  95% CI `[-0.0336, +0.1986]`.
- **Volume:** no launch-window volume surge. T+5 volume adjusted log ratio is
  `-0.0922`, `t=-1.17`, 95% CI `[-0.2475, +0.0574]`; T+22 volume is positive but
  insignificant (`+0.0715`, `t=0.89`).
- **Codex review:** `CONDITIONAL_PASS` as a bounded public-data screen. Event timing
  is clean, random procedures use `SEED=42`, and the statistical unit is event-level.
  The result cannot test household-level crowd-out directly because no handle
  surprise or household transaction data enters the model.

## Files

- `k1604.py` — experiment script.
- `k1604_results.json` — canonical result artifact.
- `k1604_event_panel.csv` — event-level metrics.
- `k1604_ticker_event_panel.csv` — ticker-event diagnostics.
- `figures/` — result charts.

## Caveats

- This is a public proxy diagnostic, not a household transaction-data replication.
- It tests launch/access dates only; it does not observe state-level betting-handle
  surprises.
- Public sportsbook equities may price legalization before launch, and revenue
  exposure is national rather than state-pure.
- The ticker basket is current/liquid, not a point-in-time revenue-weighted basket.
