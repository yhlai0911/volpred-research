# Data-Driven VC Screening Public-Proxy Diagnostic

## Purpose

This experiment tests a deliberately narrow public-data proxy for the
data-driven VC screening mechanism in Bonelli's RFS article *Data-Driven
Investors*. The paper's mechanism is private-market VC screening automation and
startup financing. Free public data do not observe that mechanism directly, so
this run asks only:

> Do lagged SEC registration-statement bursts forecast future volatility,
> downside variance, or dispersion in listed innovation proxies?

This is not a replication of the RFS paper and not a causal test of VC
automation.

## Data

- Price source: yfinance adjusted close, `auto_adjust=True`.
- Price sample: 2018-01-02 through 2026-07-02, `n_price_rows=2136`.
- Listed innovation proxies: `ARKK`, `IPO`, `IGV`, `SOXX`, `AIQ`.
- Market controls: `QQQ`, `SPY`.
- Public financing-window proxy: SEC EDGAR `master.gz` full-index counts of
  `S-1`, `S-1/A`, `F-1`, and `F-1/A` filings.
- SEC proxy sample: 2018-01-01 through 2026-07-02.
- Total registration count: `33576`.
- Innovation-name registration count: `1766`.
- Mean trading-bucket intensity: `3.8004` registration statements per 1,000
  EDGAR filings.
- Random seed: `42`.

Literature/context sources are embedded in the results JSON:

- Bonelli, *Data-Driven Investors*, The Review of Financial Studies.
- CFA Institute Research Foundation (2025), *AI in Asset Management*.
- Gompers et al. (2008), *Venture Capital Investment Cycles: The Impact of
  Public Markets*.
- Peters (2017), *Volatility and Venture Capital*.

## Method

SEC registration attention is bundled into trading-day buckets. A Monday bucket
includes weekend filings after the prior trading day and through Monday. Every
model uses:

```python
attention_z_lag1 = attention_z.shift(1)
```

The primary OOS test forecasts 5- and 21-trading-day forward close-to-close
variance for each listed innovation proxy. The baseline model uses lagged own
RV, lagged absolute/negative return, and lagged market RV. The augmented model
adds lagged SEC registration attention.

Forward-label leakage is explicitly blocked. For a prediction on row `t`, a
training row is allowed only if:

```python
target_end_pos < prediction_pos
```

Loss comparison uses Patton QLIKE on realized close-to-close variance. DM tests
compare pointwise QLIKE losses as:

```python
dm_test(loss_augmented, loss_baseline, h=horizon)
```

Negative DM `t` means the augmented model has lower loss.

Primary PASS gate: at least two OOS cells must have lower augmented QLIKE and
DM `t <= -3.0`. This did not happen.

## Results

Verdict: **NULL_PUBLIC_PROXY_DIAGNOSTIC**.

No OOS cell passed the Harvey-style `|t| >= 3` threshold. Six of ten cells had
directionally lower QLIKE after adding SEC attention, but the strongest case was
still below the research threshold.

| Ticker | Horizon | QLIKE improvement | DM t | Harvey pass |
|---|---:|---:|---:|---|
| ARKK | 5d | `+0.05%` | `-0.14` | no |
| ARKK | 21d | `-0.24%` | `+0.28` | no |
| IPO | 5d | `+0.97%` | `-1.28` | no |
| IPO | 21d | `-1.58%` | `+1.46` | no |
| IGV | 5d | `+2.22%` | `-2.08` | no |
| IGV | 21d | `+3.21%` | `-1.69` | no |
| SOXX | 5d | `-3.13%` | `+1.22` | no |
| SOXX | 21d | `-4.29%` | `+0.93` | no |
| AIQ | 5d | `+0.17%` | `-0.12` | no |
| AIQ | 21d | `+0.65%` | `-0.20` | no |

Aggregate HAC diagnostics also failed the directional gate. The coefficient on
lagged SEC attention was negative for innovation basket RV, IPO downside
variance, and innovation dispersion at both horizons. The closest diagnostic was
21d innovation dispersion with beta `-0.0155`, HAC `t=-1.94`, `p=0.052`, which
is the opposite direction of a positive volatility-spillover claim.

The rolling top-decile attention contrast is also opposite to the proposed
volatility-amplification story: 5d innovation basket RV averaged `0.00119` on
shock days versus `0.00194` otherwise, Welch `t=-6.87`.

## Interpretation

The public SEC-registration proxy does not support a publishable claim that
financing-window bursts or data-driven VC screening attention robustly forecast
future volatility in public innovation ETFs. The cleanest honest statement is:

> Under a reproducible SEC S-1/F-1 public proxy, there is no Harvey-strength OOS
> evidence that financing-gate attention improves volatility forecasts for
> ARKK/IPO/IGV/SOXX/AIQ.

This null does not refute Bonelli's private-market mechanism. It only says the
free public proxy is not strong enough for a VolPred article claim without
private VC deal data, VC-backed IPO cohort labels, or richer funding/news feeds.

## Outputs

- `research_data_driven_vc_screening_shock_public_innovation.py`
- `research_data_driven_vc_screening_shock_public_innovation_results.json`
- `data/innovation_etf_adjusted_close.csv`
- `data/sec_registration_attention_daily.csv`
- `data/sec_registration_attention_trading_day.csv`
- `data/oos_predictions.csv`
- `figures/attention_oos_summary.png`
- `codex_review.md`

## Limitations

- SEC registration attention is not VC screening automation.
- ETF proxies are public-market baskets, not point-in-time VC-backed startup
  cohorts.
- Company-name keyword counts are a rough innovation diagnostic, not a validated
  sector classifier.
- Daily close-to-close variance can miss intraday announcement-time effects.
- Stronger work would need Crunchbase/PitchBook/Preqin deal data, VC-backed IPO
  labels, and timestamped funding/news feeds.
