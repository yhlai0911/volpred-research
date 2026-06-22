# K1361 — Gaming / Sports-Betting / Esports Vol Spillover

## Motivation

This task comes from the 2026-06-21 journal-discovery backlog:

> Gaming / sports-betting / esports baskets may have become alternative
> risk-on exposures. Test whether they transmit volatility to QQQ / ARKK /
> BTC during turmoil, or whether they are only diversification sinks.

The narrow VolPred question is not "are gaming stocks volatile?"  It is:

**Do public gaming, esports, and betting proxies lead broad risk-on realized
volatility strongly enough to call them volatility transmitters?**

## Related Project Context

- K628b found broad cross-asset spillover structure, with SPY as the dominant
  transmitter and TLT as a receiver.
- `research_graph_network_spillover_rv_var` tested graph spillover features
  as RV predictors and is the closest methods neighbor.
- K1346 found a yfinance-only lottery-stock basket did not provide a robust
  early-warning signal for SPY / IWM tail volatility.  K1361 therefore avoids
  treating DKNG / HOOD-style retail-risk names as proof of a systemic channel.

## Literature Checked

- Papathanasiou (2026), *Reevaluating Diversification: The Evolving Role of
  Gaming in Market Turmoil*, Journal of Alternative Investments:
  <https://www.pm-research.com/content/iijaltinv/28/4/74>
- Diebold and Yilmaz (2012), *Better to give than to receive: Predictive
  directional measurement of volatility spillovers*, International Journal of
  Forecasting:
  <https://ideas.repec.org/a/eee/intfor/v28y2012i1p57-66.html>
- Barunik and Krehlik (2018), *Measuring the frequency dynamics of financial
  connectedness and systemic risk*, Journal of Financial Econometrics:
  <https://ideas.repec.org/a/oup/jfinec/v16y2018i2p271-296..html>
- Balli, Balli, Dang, and Gabauer (2023), *Contemporaneous and lagged R2
  decomposed connectedness approach*, Finance Research Letters:
  <https://ideas.repec.org/a/eee/finlet/v57y2023ics1544612323005408.html>

## Data

- Source: yfinance adjusted close, cached under `data/`.
- Raw tickers:
  - Gaming ETFs: ESPO, HERO, NERD, GAMR.
  - Betting / trading-app proxy: DKNG, FLUT, HOOD.
  - Risk-on benchmarks: QQQ, ARKK, BTC-USD.
  - Market benchmark / calendar: SPY.
- Baskets are equal-weighted daily log returns using available constituents.
  Gaming requires at least two ETF members.  Betting requires at least two of
  DKNG / FLUT / HOOD.

## Method

The experiment has three layers:

1. **Descriptive connectedness**: generalized Diebold-Yilmaz FEVD from a VAR
   on standardized log 21-day realized variance proxies.
2. **Rolling stress comparison**: 252-trading-day rolling connectedness every
   21 trading days.  Stress windows are the top quartile of SPY 21-day realized
   volatility at the window end; calm windows are the bottom quartile.
3. **Predictive lead tests**: standardized OLS/HAC regressions where
   `source_lag1 = source_log_rv.shift(1)` predicts target log-RV for
   QQQ / ARKK / BTC / SPY, controlling for own lag and broad-market lags.

Rolling return correlations are reported separately as diversification-sink
diagnostics.  They are not causal evidence.

## Lookahead Policy

- All predictive regressions use lagged source volatility:

```python
f"{source}_lag1": log_rv[source].shift(1)
```

- The rolling connectedness block is descriptive; it does not use future
  information for a trading signal.
- Stress labels are contemporaneous diagnostics, not ex-ante timing signals.
- Random procedures use `SEED = 42`.

## Success Criteria

Strong transmitter claim requires both:

1. Gaming or betting net connectedness is higher in stress than calm, has
   positive stress net connectedness, and Welch `t >= 3`.
2. At least two lagged source-volatility regressions have positive HAC
   `t >= 3` on the source lag.

If only stress correlations rise, the correct verdict is diversification sink
only, not volatility transmitter.

## Results

Verdict: `DIVERSIFICATION_SINK_PLUS_WEAK_LEAD_NULL_TRANSMITTER`.

Sample: 2019-08-15 to 2026-06-18, 1,720 daily observations after the betting
basket and 21-day volatility window become available.

### Full-sample connectedness

The full-sample Diebold-Yilmaz table does **not** classify gaming or betting
as net transmitters.  SPY and QQQ are the dominant net sources in this public
proxy system.

| Series | From others | To others | Net |
|---|---:|---:|---:|
| GAMING_ETF | 0.6219 | 0.5447 | -0.0772 |
| BETTING_FINTECH | 0.4043 | 0.2370 | -0.1672 |
| QQQ | 0.6420 | 0.7919 | +0.1498 |
| ARKK | 0.6245 | 0.6571 | +0.0326 |
| BTC | 0.2432 | 0.1317 | -0.1115 |
| SPY | 0.5989 | 0.7723 | +0.1735 |

### Stress vs calm connectedness

Stress windows are rolling-window endpoints where SPY 21-day realized vol is
above 19.30%; calm is below 10.50%.

| Series | Stress net | Calm net | Diff | Welch t | Bootstrap 95% CI |
|---|---:|---:|---:|---:|---:|
| GAMING_ETF | -0.1405 | -0.1529 | +0.0124 | +0.14 | [-0.1434, +0.1811] |
| BETTING_FINTECH | -0.0935 | -0.1019 | +0.0084 | +0.10 | [-0.1509, +0.1636] |

Interpretation: both baskets remain net receivers during stress.  The small
stress-minus-calm net increase is statistically negligible and does not support
a transmitter claim.

### Lagged volatility lead tests

Only 1 of 8 source-target tests clears the Harvey `t >= 3` bar:

| Lead test | Standardized coef | HAC t |
|---|---:|---:|
| BETTING_FINTECH -> ARKK | +0.0176 | +3.13 |

One isolated lead test is not enough for the predefined strong-claim rule
(requires at least two target passes plus transmitter evidence).

### Diversification sink diagnostic

Rolling return correlations with every risk-on benchmark rise sharply in SPY
stress windows:

| Pair | Stress - calm corr | Welch t |
|---|---:|---:|
| GAMING_ETF vs QQQ | +0.1305 | +21.40 |
| GAMING_ETF vs ARKK | +0.1473 | +27.42 |
| GAMING_ETF vs BTC | +0.3242 | +30.15 |
| GAMING_ETF vs SPY | +0.1275 | +14.46 |
| BETTING_FINTECH vs QQQ | +0.1634 | +10.68 |
| BETTING_FINTECH vs ARKK | +0.1566 | +8.70 |
| BETTING_FINTECH vs BTC | +0.1954 | +14.56 |
| BETTING_FINTECH vs SPY | +0.1438 | +9.41 |

This supports the weaker statement: gaming/betting proxies diversify less in
stress periods.  It does not establish that they lead or transmit volatility.

## Figures

- `figures/k1361_fevd_heatmap.png`
- `figures/k1361_rolling_net_connectedness.png`
- `figures/k1361_stress_corr_diffs.png`

## Limitations

- Current listed proxies are survivorship-biased and miss delisted gaming /
  betting names.
- FLUT's yfinance history may reflect symbol/listing continuity rather than a
  pure NYSE-only history; it is treated only as a public betting-equity proxy.
- BTC is aligned to the SPY trading calendar, so weekend crypto moves enter
  the next US trading-session return.
- Close-to-close 21-day variance is a public-data proxy, not intraday RV or
  option-implied volatility.
- Rolling stress/calm tests use overlapping windows and are diagnostic.
- No trading strategy, option-pricing, or causal spillover claim is made.

## Reproduce

```bash
uv run python experiments/k1361/K1361.py
```

Use `--refresh` to ignore cached yfinance files.
