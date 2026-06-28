# K1555: Tariff-Uncertainty USD Risk-Premium Wedge Proxy

- Experiment ID: `K1555`
- Status: `COMPLETE`
- Created: 2026-06-28
- Script: `experiments/k1555/k1555.py`
- Results: `experiments/k1555/k1555_results.json`

## Motivation

Kalemli-Ozcan, Soylu, and Yildirim (2026), "Global Trade, Tariff
Uncertainty, and the US Dollar", argue that tariff uncertainty can overturn the
standard macrotrade prediction that unilateral tariffs appreciate the tariffing
country's currency. In their mechanism, tariff volatility enters exchange rates
through a risk-premium wedge and can cause immediate US dollar depreciation.

K1555 asks a narrower public-data question: do major 2025-2026 tariff-policy
events first show up in FX realized volatility / USD drawdown and then spill over
to EM and commodity ETF risk?

This is an event-calendar proxy diagnostic, not a replication of the paper's
model, tariff-volatility state variable, or exchange-rate risk-premium estimates.

## Literature Preamble

- Kalemli-Ozcan, Soylu, and Yildirim (2026), "Global Trade, Tariff Uncertainty,
  and the US Dollar", AEA Papers and Proceedings 116:47-52.
  Source: https://www.aeaweb.org/articles?id=10.1257/pandp.20261039
- NBER working paper version: "Global Trade, Tariff Uncertainty and the U.S.
  Dollar", NBER WP 34728.
  Source: https://www.nber.org/papers/w34728
- USTR presidential tariff actions page for 2025 reciprocal-tariff actions.
  Source: https://ustr.gov/trade-topics/presidential-tariff-actions
- CFR 2025 trade calendar for April 2025 tariff escalation / pause milestones.
  Source: https://www.cfr.org/articles/trade-calendar-2025
- White House April 2, 2025 reciprocal tariff executive action.
  Source: https://www.whitehouse.gov/presidential-actions/2025/04/regulating-imports-with-a-reciprocal-tariff-to-rectify-trade-practices-that-contribute-to-large-and-persistent-annual-united-states-goods-trade-deficits/

## Data

- Price source: yfinance adjusted daily OHLCV.
- USD proxies: `UUP`, `DX-Y.NYB`.
- FX/EM FX proxies: `FXY`, `FXE`, `CEW`, `EMLC`.
- Spillover proxies: `EEM`, `DBC`, `GLD`.
- Requested period: 2024-01-01 through 2026-06-28.
- Event source: hand-curated public tariff-policy calendar embedded in
  `k1555.py` and exported to `data/tariff_events.csv`.

GDELT DOC headline-intensity probes were not used as evidence because prior
project experience and the current session both encountered rate limiting for
large timeline queries. The result JSON records this as a blocked source.

## Method

1. Map tariff-policy event dates to the next available trading day.
2. Build two raw signals:
   - absolute tariff-policy uncertainty intensity;
   - signed tariff direction, where escalation is positive and de-escalation is
     negative.
3. Apply signals with an explicit one-trading-day lag:
   `event_abs_signal = raw_event_abs.shift(1)`.
4. Compute next 1, 5, and 22 trading-day outcomes:
   - FX basket realized volatility;
   - USD drawdown (`-UUP` forward return);
   - EM/EM-FX left-tail pressure;
   - commodity basket realized volatility.
5. Standardize each forward outcome against trailing realized windows only. The
   abnormal z-score baseline never rolls over forward targets.
6. Compare applied event rows with non-event control rows outside post-event
   windows using Welch tests and seed-42 event-date bootstrap.

## Lookahead Policy

- Event dates are public policy announcement dates.
- Raw event indicators are shifted by one trading day before use:
  `event_abs_signal = raw_event_abs.shift(1)`.
- Forward targets start only on the applied signal date.
- Abnormal target baselines use trailing windows ending before the applied day;
  no forward target enters its own baseline.
- Bootstrap seed is fixed at 42.

## Success Criteria

- `PASS`: event windows show a coherent lead-lag pattern: FX 1-day abnormal RV
  positive, USD drawdown positive, and EM/commodity spillover positive at 5 or 22
  days, with at least two target tests near Harvey-style t >= 3 or bootstrap CIs
  excluding zero.
- `CONDITIONAL_PASS`: direction is coherent but evidence is event-count limited
  or only one leg is statistically strong.
- `NULL`: event rows are available but the FX/USD/EM spillover pattern is mixed
  or weak.
- `UNDERPOWERED`: too few usable event rows exist for a serious inference.

## Result

Verdict: `CONDITIONAL_PASS`.

Headline findings:

- Usable applied tariff-event rows: 9.
- FX 1-day abnormal realized volatility is directionally positive:
  event-minus-control z-score `+1.138`, Welch t `1.67`, p `0.133`.
- USD drawdown is the strongest leg:
  - 1-day USD drawdown z-score `+1.748`, Welch t `2.84`, p `0.021`;
  - event-date bootstrap CI for the event mean is positive.
- 5-day USD drawdown remains positive but weaker:
  event-minus-control z-score `+0.806`, Welch t `1.57`, p `0.155`.
- EM / EM-FX left-tail spillover is not supported:
  5-day z-score `-0.098`, 22-day z-score `-0.453`.
- Commodity RV is weak and mixed:
  5-day z-score `+0.377`, 22-day z-score `-0.012`.
- No target clears the Harvey-style t >= 3 gate.

Interpretation: the public ETF/FX proxy is consistent with the AEA/NBER idea
that tariff uncertainty can pressure the USD and lift FX volatility, but K1555
does not confirm the full FX-to-EM/commodity spillover channel. Treat this as a
partial, event-count-limited diagnostic.

The conclusion should be read as a public ETF/FX proxy event study. A positive
result would motivate a richer tariff-intensity feed; a null result would not
refute the AEA/NBER mechanism.

## Files

- `k1555.py`: reproducible experiment script.
- `k1555_results.json`: numeric output and event diagnostics.
- `k1555_event_effects.png`: event-minus-control target effect chart.
- `data/prices.csv`: adjusted OHLCV snapshot.
- `data/tariff_events.csv`: event calendar and mapped trading dates.
- `data/daily_targets.csv`: joined signal/target panel.
- `codex_review.md`: source/result review.
