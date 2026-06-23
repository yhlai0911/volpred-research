# Friday / Triple-Witching Closing-Window Concentration Proxy

## Verdict

**INSUFFICIENT_TRIPLE_WITCHING_SAMPLE / not article-ready.**

The available local free data can only support a short SPY 5-minute diagnostic:
2026-01-14 to 2026-06-22, 106 usable sessions, 20 Fridays, 6 monthly OPEX days,
and only 2 triple-witching proxy days. The test does not support a positive
claim that Friday/OPEX/triple-witching closing-window concentration predicts
next-session RV or reversal.

## Motivation

The backlog asks whether Friday, monthly options expiration, or triple-witching
closing-auction concentration predicts next-day realized volatility and
reversal. True NYSE/Nasdaq closing-auction prints, MOC imbalance feeds, and
multi-year minute bars are not available locally. This experiment therefore
uses the final 30 minutes of local SPY 5-minute bars as a proxy.

## Prior Work

- Goyal, Jegadeesh, and Wu, "Price Impact: Continuous Trading, Closing
  Auctions, and Opening Auctions", SSRN/JFQA.
- Stoll and Whaley, "Program Trading and Expiration-Day Effects", Financial
  Analysts Journal, 1987.
- Stoll and Whaley, "Expiration-Day Effects: What Has Changed?", Financial
  Analysts Journal, 1991.
- Feinstein and Goetzmann, "The Effect of the Triple Witching Hour on Stock
  Market Volatility", Federal Reserve Bank of Atlanta Economic Review, 1988.
- K1341: Russell/S&P reconstitution daily ETF proxy did not validate a clean
  dislocate-then-revert pattern.

## Data

- Source: local `data/intraday/SPY_5min_2026-*.csv` yfinance-style snapshots.
- Ticker: SPY only.
- Effective sample: 2026-01-14 to 2026-06-22.
- Usable sessions after regular-session quality filters: 106.
- Calendar events: 20 Fridays, 6 monthly OPEX, 2 triple-witching proxy days.
- Event alignment: third-Friday OPEX is aligned to the same trading day, or to
  the prior trading day within 3 calendar days if the nominal Friday is closed.

## Method

For each day, the script computes:

- final-30-minute volume share;
- final-30-minute RV share from 5-minute squared log returns;
- final-30-minute range-variance share;
- next-session open-to-close squared return;
- next-session 5-minute RV;
- next-session reversal payoff: `-sign(oc_ret_t) * oc_ret_{t+1}`.

Lookahead controls:

- calendar labels are known ex ante;
- high-concentration threshold uses
  `close30_vol_share.shift(1).rolling(40, min_periods=20).quantile(0.80)`;
- next-session targets are created with `.shift(-1)` but are never used as
  same-day signals;
- continuous regressions use close-window z-score dated t against target t+1.

Tests:

- Welch event-vs-control comparisons;
- 5,000-rep bootstrap CI with seed 42;
- Newey-West HAC regressions with 5 lags;
- Harvey-style publication gate: `|t| > 3`.

## Results

Closing-window concentration:

| Group | N | Close-30m volume share | t |
|---|---:|---:|---:|
| Friday | 20 | 16.58% vs 16.26% control | 0.26 |
| Monthly OPEX | 6 | 14.04% vs 16.46% control | -1.12 |
| Triple-witching proxy | 2 | 18.82% vs 16.27% control | 1.35 |

Close-30m RV share is descriptively high on the 2 triple-witching proxy days
(`17.69%` vs `6.76%` control), but `N=2` blocks inference.

Predictive tests:

| Signal | Target | N signal | Difference | t |
|---|---|---:|---:|---:|
| high close concentration | next OC r² | 25 | -5.15e-6 | -0.27 |
| high close concentration | next 5-min RV | 25 | -6.81e-6 | -0.78 |
| high close concentration | next reversal payoff | 25 | +0.00211 | 1.32 |

Continuous regressions:

- next OC r² on close30 volume-share z: HAC t = 1.30.
- next 5-min RV on close30 volume-share z: HAC t = 0.65.
- next reversal payoff on close30 volume-share z: HAC t = 1.20.

No predictive result clears the Harvey `|t| > 3` gate.

## Interpretation

This is a negative/underpowered screen. The local 5-minute sample shows why the
mechanism is worth a better data test, but it cannot validate a tradable or
publishable Friday/OPEX/triple-witching volatility signal.

A publishable follow-up needs multi-year 5-minute SPY/QQQ/IWM and large-cap
bars, or true exchange auction volume / MOC imbalance data.

## Reproducibility

```bash
uv run python experiments/research_friday_triple_witching_closing_auction_concentra/research_friday_triple_witching_closing_auction_concentra.py
```

Core outputs:

- `research_friday_triple_witching_closing_auction_concentra.py`
- `research_friday_triple_witching_closing_auction_concentra_results.json`
- `daily_panel.csv`
- `figures/close30_volume_share_timeseries.png`
- `figures/calendar_group_concentration.png`
