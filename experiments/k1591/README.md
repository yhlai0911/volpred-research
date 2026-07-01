# k1591 - Ex-ante macro regimes for GLD leverage direction

## Question

Can the gold component of the leverage-direction manuscript be rebuilt as a
pre-specified, externally defined regime result rather than an unconditional
claim that GLD has inverted leverage?

## Motivation

Stage 1 reframing downgraded the manuscript's old gold claim because the
canonical table now shows GLD near zero unconditionally. Stage 2 therefore
requires a new regime design that does not choose regimes from ex-post GLD
gamma signs. This experiment uses only lagged external instruments:

- VIX stress threshold
- DXY 63-trading-day trend
- Treasury basis/curve movement, proxied by 10Y minus 13-week yield

The literature motivation is safe-haven and gold asymmetric-volatility work:
Baur and Lucey (2010), Baur and McDermott (2010), Baur (2012), Chevallier and
Ielpo (2017), and Chang et al. (2021).

## Method

Data:

- GLD and VIX: pinned manuscript snapshot
  `paper/leverage-direction/data/spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv`
- DXY, 10Y yield, 13-week yield: yfinance cache written under
  `experiments/k1591/data/`
- Effective sample after lag construction: 2010-04-07 to 2026-06-26
  (`n=4,091`), with train ending 2018-12-31 and holdout starting 2019-01-01

Regime rule:

- `safe_haven_stress`: lagged VIX >= 20, DXY not in a 63-day uptrend, and
  Treasury basis not steepening
- `liquidation_stress`: lagged VIX >= 20, DXY in a 63-day uptrend, and
  Treasury basis steepening
- `neutral`: all other days

All regime inputs are shifted one trading day before classification.

Primary model:

`GLD r_t^2 = c + beta_pos * 1(r_{t-1} >= 0) r_{t-1}^2 + beta_neg * 1(r_{t-1} < 0) r_{t-1}^2 + controls`

Controls are lagged 5-day and 22-day realized variance. The reported asymmetry
coefficient is `gamma_diff = beta_neg - beta_pos`. Negative values mean
positive shocks have the larger volatility response, matching the inverted
news-impact interpretation used in the gold literature. HAC standard errors use
5 lags.

Validation:

- Holdout estimates are computed separately for 2019-2026.
- A 1,000-draw contiguous block bootstrap with 10-day blocks estimates the
  holdout safe-minus-liquidation contrast.
- A rolling 504-day, quarterly-step GJR-GARCH gamma diagnostic is reported as
  a secondary check only.

## Outputs

- `k1591.py` - experiment script
- `k1591_results.json` - full machine-readable results
- `tables/k1591_daily_panel.csv` - lagged regime panel
- `tables/k1591_regime_summary.csv` - primary and rolling summaries
- `tables/k1591_rolling_gjr_gamma.csv` - rolling GJR diagnostic
- `figures/k1591_holdout_regime_asymmetry.png` - holdout asymmetry chart

## Conclusion

Command:

```bash
uv run python experiments/k1591/k1591.py
```

Result status: `directionally_supportive`, but not statistically strong enough
for a headline claim.

Holdout 2019-2026 primary regression:

| Regime | Days | gamma_diff | HAC t | Interpretation |
|---|---:|---:|---:|---|
| safe_haven_stress | 166 | -0.0870 | -0.66 | Directionally inverted |
| liquidation_stress | 239 | +0.0428 | +0.27 | Directionally standard |
| neutral | 1,486 | +0.1295 | +0.51 | No reliable separation |
| all holdout | 1,891 | +0.0509 | +0.29 | No unconditional gold effect |

Block bootstrap contrast:

- Safe-haven minus liquidation median: `-0.1385`
- 95% CI: `[-0.7105, 0.3940]`
- Negative in 69.8% of valid bootstrap draws

Rolling GJR diagnostic:

- Full holdout rolling GJR mean gamma is negative (`-0.0545`, 93.3% negative),
  but the ex-ante stress regimes have only 4 safe-haven windows and 3
  liquidation windows, so this diagnostic is not a regime-level proof.

Manuscript implication:

- This experiment supports a cautious regime-dependent design: externally
  defined safe-haven stress days lean toward inverted news impact, while
  liquidation stress days lean toward standard news impact.
- It does not justify restoring an unconditional gold inverted-leverage claim.
- Train-period liquidation stress has only 27 observations, so the regime rule
  needs additional robustness, preferably with gold futures and/or institutional
  flow data, before it can be a central JBF contribution.
