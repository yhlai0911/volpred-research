# research_rp_f1168bab52

## Motivation

Backlog question:

> Does return-extrapolation bias create an asymmetric IV-RV term-structure premium? Specifically, after a negative trailing 20-day SPY return, does short-horizon implied variance carry a larger premium over future realized variance than medium-horizon implied variance?

This experiment tests a reduced-form, free-data version using VIX (roughly 1M), VIX3M (roughly 3M), and future SPY realized variance.

## Literature And Prior-K Context

External references checked:

- Chordia, Lin, and Xiang (2025), "Return Extrapolation and Volatility Expectations", JFQA. https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/return-extrapolation-and-volatility-expectations/4A0B8AFCB3A4F3996600C26A3EF689DC
- Bekaert and Hoerova (2014), "The VIX, the Variance Premium and Stock Market Volatility", Journal of Econometrics. https://ideas.repec.org/a/eee/econom/v183y2014i2p181-192.html
- Bollerslev, Tauchen, and Zhou (2009), "Expected Stock Returns and Variance Risk Premia", Review of Financial Studies. https://ideas.repec.org/a/oup/rfinst/v22y2009i11p4463-4492.html
- Carr and Wu (2009), "Variance Risk Premiums", Review of Financial Studies. https://ideas.repec.org/a/oup/rfinst/v22y2009i3p1311-1341.html

Related VolPred priors:

- Existing knowledge has repeated findings that VIX/VIX3M term-structure signals can be informative in-sample, but often fail as an incremental OOS forecast or VT overlay.
- VRP directional timing has repeatedly been fragile; true variance premium harvesting generally needs option-level implementation rather than SPY direction timing.
- Error log constraints used here: explicit lagging for VIX signals, forward-label OOS cutoff, and Patton QLIKE/DM checks.

## Data

- Market data: `yfinance` adjusted close for `SPY`, `^VIX`, `^VIX3M`
- Macro controls: local FRED files `DGS10`, `DGS2`, `T10YIE`
- Daily sample: 2006-07-17 to 2026-06-16, `n=5012`
- Monthly origins: 2006-07-31 to 2026-06-16, `n=240`

## Design

All signals are lagged by one trading day at the month-end origin:

- `IV_1M = (VIX_{t-1}/100)^2`
- `IV_3M = (VIX3M_{t-1}/100)^2`
- negative-return regime: sum of SPY log returns over `t-20..t-1 < 0`
- future `RV_21`: annualized mean squared SPY log return over `t+1..t+21`
- future `RV_63`: annualized mean squared SPY log return over `t+1..t+63`
- premium: `IV_h - future RV_h`

OOS forecasts use expanding regressions. To avoid forward-label leakage, a row can enter the training set only if its realized-variance label end date is strictly before the forecast origin.

## Results

Verdict: `MIXED_DIAGNOSTIC_NOT_TRADABLE`.

### Regime Means

| Metric | Negative past20 | Positive past20 | Diff | Welch p | HAC t |
|---|---:|---:|---:|---:|---:|
| 1M premium | -21.97 vol-pts^2 | 96.92 | -118.89 | 0.385 | -0.98 |
| 3M premium | 163.79 | 91.32 | +72.48 | 0.430 | +1.14 |
| 1M-3M slope | -185.76 | 5.61 | -191.37 | 0.024 | -1.75 |

The raw sign is opposite the simple hypothesis: after negative trailing returns, the short-vs-medium premium slope is lower, not higher. The unadjusted Welch p-value for the slope is below 5%, but HAC inference is not Harvey-strength.

### Conditional Regressions

- FMB-style monthly slope regression: `neg20` coefficient `+0.0059`, HAC `t=0.55`, `p=0.582`
- pooled two-maturity panel interaction `short_maturity x neg20`: coefficient `-0.0231`, HAC `t=-1.82`, `p=0.069`

Controls remove the apparent raw slope effect. This is diagnostic, not a robust term-structure anomaly.

### OOS Forecasts

| Target | OOS n | Augmented MSE R2 vs VIX-only | QLIKE DM t | QLIKE direction |
|---|---:|---:|---:|---|
| 21d RV from VIX | 140 | +4.50% | +3.97 | augmented worse |
| 63d RV from VIX3M | 137 | +1.56% | +3.91 | augmented worse |

MSE improves slightly, but Patton QLIKE strongly rejects the augmented model in the wrong direction. Since realized variance forecasts are evaluated under QLIKE as the primary volatility loss, this is not a forecast PASS.

### Trading Rule

Monthly VT rule:

- baseline: `12% / VIX1M`, 1.5x cap
- asymmetric rule: use `12% / VIX3M` when lagged past20 return is negative, otherwise `12% / VIX1M`
- cost: 10bp per 1x turnover

Results:

| Strategy | Sharpe | MaxDD | CAGR |
|---|---:|---:|---:|
| Buy-and-hold | 0.792 | -56.5% | 12.2% |
| VIX1M VT | 0.909 | -25.3% | 8.2% |
| VIX3M VT | 0.902 | -25.2% | 7.5% |
| asymmetric rule | 0.881 | -26.5% | 7.9% |

The asymmetric rule reduces Sharpe by `-0.028` and worsens max drawdown by `-1.24pp` relative to VIX1M VT. It is not a deployable rule.

## Conclusion

This free-data experiment does **not** validate the hypothesis that negative-return extrapolation creates a tradable short-horizon IV-RV premium amplification. The raw regime slope is suggestive but disappears under controls; OOS QLIKE is worse; and the corresponding VT overlay loses to the simpler VIX1M baseline.

The correct interpretation is narrow: VIX/VIX3M may contain diagnostic term-structure information, but this reduced-form monthly implementation does not produce a robust OOS forecast or trading improvement.

## Limitations

- VIX and VIX3M are index proxies, not model-free variance swap rates.
- Monthly two-maturity panel is small; the FMB-style slope is only a two-point term-structure contrast.
- Daily close-to-close RV is a free-data proxy, not high-frequency realized variance.
- Option-level variance premium tests would require SPX option-chain data and proper variance swap replication.

## Artifacts

- Script: `research_rp_f1168bab52.py`
- Results: `research_rp_f1168bab52_results.json`
- Figure 1: `fig_premium_by_regime.png`
- Figure 2: `fig_oos_and_strategy.png`

## Reproduction

```bash
uv run python experiments/research_rp_f1168bab52/research_rp_f1168bab52.py
```
