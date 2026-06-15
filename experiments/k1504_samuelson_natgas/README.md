# K1504 — Natural gas seasonality and front-month Samuelson proxy

**Final verdict: CONDITIONAL_PASS.** Natural gas realized volatility shows a
clear calendar-month seasonal pattern in both `NG=F` and `UNG`, but the
free-data front-month expiry-distance proxy does **not** support a Samuelson
maturity-effect claim.

## Research Question

The queued backlog question was:

> Natural gas seasonal volatility and Samuelson effect: use yfinance
> `UNG` / natural gas data to test winter heating-regime volatility and whether
> volatility rises as contract expiry approaches.

K1504 deliberately separates two claims:

1. **Seasonality:** calendar-month realized volatility differs across the year.
2. **Samuelson proxy:** `NG=F` daily volatility should rise when the front-month
   proxy is closer to approximate NYMEX expiry.

The second claim is only a proxy test. A true Samuelson test needs a
contract-level futures panel across multiple maturities.

## Literature Checked Before Implementation

- Samuelson (1965), *Proof that Properly Anticipated Prices Fluctuate
  Randomly*: original maturity-effect hypothesis.
- Mu (2004), *Weather, Storage, and Natural Gas Price Dynamics*: natural gas
  volatility is linked to weather, storage reports, and contract horizon.
- Ergen and Rizvanoghlu (2016), *Asymmetric impacts of fundamentals on the
  natural gas futures volatility*: storage / weather / time-to-maturity effects
  can be season-dependent.
- Ho, Lee, and Tsai (2023), *Competing hypotheses on the Samuelson effect in
  futures markets*: Samuelson effects are not universal across energy contracts.
- CME Rulebook Chapter 220: Henry Hub Natural Gas futures stop trading three
  business days before the delivery month.
- CME / EIA natural gas seasonality material: winter heating and storage cycles
  provide the mechanism for calendar seasonality.

## Relation to Prior K Findings

- `K1461`: already found strong `UNG` month-of-year realized-volatility
  seasonality, with February high and September low in that sample. K1504
  extends the check to `NG=F`, uses a longer local close snapshot, and adds an
  expiry-distance proxy.
- `K1339`: used ETF momentum-regime switches as commodity vol-jump events, but
  correctly warned that ETF momentum is not a true futures-curve regime.
- `research_inventory_seasonality_surprise_regime_conditiona`: low-inventory
  seasonal interactions were NULL for `NG=F` and `UNG`; K1504 does not use
  inventory regimes.

## Data

- Source: local yfinance close snapshot from
  `experiments/research_inventory_seasonality_surprise_regime_conditiona/data/close.csv`.
- Tickers: `NG=F`, `UNG`.
- Clean sample after dropping one weekend-labelled futures row:
  2006-01-03 to 2026-06-12.
- Non-null observations: `NG=F` 5,144; `UNG` 4,820; overlap 4,818.
- Monthly realized-volatility panel: 476 ticker-month rows.
- `NG=F` Samuelson proxy panel: 5,141 daily rows.

## Method

### Seasonality

Monthly realized volatility is computed from daily log returns:

`rv_ann = sqrt(mean(r_t^2)) * sqrt(252)`

Tests:

- One-way ANOVA across 12 calendar months.
- 5,000-label permutation test of the month labels.
- HAC monthly regression of log RV on winter / summer dummies plus
  `lag_log_rv_ann`.

### Samuelson Proxy

For each `NG=F` daily return:

- Approximate delivery month as the nearest natural-gas delivery month whose
  expiry has not passed.
- Approximate expiry as three business days before the first day of the
  delivery month, following CME Rulebook Chapter 220.
- Regress daily `log(abs_return)` on:
  - business days to expiry, or
  - near-expiry dummy (`<=5` business days),
  - lagged `log(abs_return)`,
  - calendar-month fixed effects,
  - year fixed effects.

HAC max lag is 5 for daily regressions. The experiment uses a standard weekday
calendar, not a full CME holiday calendar.

## Results

### A. Calendar-Month Seasonality Is Present

| Ticker | n months | ANOVA F | p | permutation p | Peak | Trough | Peak / trough | Winter / non-winter |
|---|---:|---:|---:|---:|---|---|---:|---:|
| `NG=F` | 246 | 3.204 | 0.00044 | 0.0012 | Jan 0.812 | Mar 0.437 | 1.86x | 1.21x |
| `UNG` | 230 | 2.450 | 0.00665 | 0.0084 | Jan 0.603 | Aug 0.390 | 1.55x | 1.22x |

This is the part that passes. It replicates the K1461 direction that natural
gas-linked volatility has strong calendar structure, now including `NG=F`.

### B. Seasonal Dummies Do Not Survive a Strong Incremental Interpretation

After adding lagged monthly log RV, the seasonal dummy evidence is weaker:

| Ticker | Dummy | Coef | HAC t | p | `|t|>3` |
|---|---|---:|---:|---:|---|
| `NG=F` | winter | -0.080 | -1.86 | 0.062 | No |
| `NG=F` | summer | -0.112 | -2.97 | 0.003 | No |
| `UNG` | winter | +0.008 | +0.22 | 0.826 | No |
| `UNG` | summer | -0.063 | -1.79 | 0.073 | No |

So the safe interpretation is descriptive seasonality, not a standalone
forecasting upgrade.

### C. The Samuelson Proxy Fails

The front-month expiry-distance proxy does not support the maturity-effect
claim:

| Test | Expected sign | Coef | HAC t | p | `|t|>3` |
|---|---|---:|---:|---:|---|
| business days to expiry | negative | +0.0036 | +1.28 | 0.200 | No |
| near-expiry `<=5bd` | positive | +0.0217 | +0.58 | 0.564 | No |

Bucket diagnostics point the same way:

| Bucket | n | Annualized RMS vol | Mean abs return |
|---|---:|---:|---:|
| near `0-5bd` | 1,405 | 57.3% | 2.59% |
| mid `6-14bd` | 2,160 | 53.8% | 2.48% |
| far `15+bd` | 1,576 | 72.0% | 2.97% |

Near minus far log absolute return is `-0.040`, bootstrap 95% CI
`[-0.134, +0.052]`, with `P(near > far)=0.199`. This is not Samuelson evidence.

## Interpretation

K1504 supports a narrow statement:

> Natural gas-linked volatility has strong calendar-month seasonality in the
> 2006-2026 free-data sample.

K1504 does **not** support:

> Natural gas futures volatility rises near expiry.

The available `NG=F` continuous series is too coarse for a contract-level
Samuelson test, and its expiry-distance proxy does not show the expected
pattern. A proper follow-up needs front / second / third nearby futures
settlement data or options-implied vol by maturity.

## Limitations

- `NG=F` is a Yahoo continuous front-month proxy, not a contract-level panel.
- Yahoo roll timing may differ from CME active-contract convention.
- Business-day counts use a weekday calendar, not full CME holidays.
- The experiment uses close-to-close returns only; no intraday, options, or
  term-structure panel is used.
- Seasonal labels are known ex ante, but this experiment does not prove a
  tradable strategy.

## Files

- `k1504.py` — reproducible script.
- `k1504_results.json` — machine-readable results.
- `data/natgas_close.csv` — cached close data.
- `data/monthly_realized_vol.csv` — monthly RV panel.
- `data/ng_front_month_expiry_panel.csv` — daily expiry-distance proxy panel.
- `figures/k1504_monthly_seasonality.png`
- `figures/k1504_samuelson_bdays_to_expiry.png`
- `codex_review.md` — source-level review.

Reproduce:

```bash
uv run python experiments/k1504_samuelson_natgas/k1504.py
```
