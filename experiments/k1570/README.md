# K1570 — Office-CRE refinancing pressure vs regional bank / REIT volatility

| Item | Value |
|---|---|
| Experiment ID | `K1570` |
| Status | `WEAK_PARTIAL` |
| Script | `k1570.py` |
| Results | `k1570_results.json` |
| Sample | 2012-01-03 to 2026-06-26, 3,642 daily rows |
| Seed | 42 |

## Question

Can an office-CRE refinancing-stress proxy lead future volatility in regional banks, REITs, mortgage REITs, and CMBS ETFs?

This is a public-proxy experiment. It does not observe loan-level maturity walls, appraisal marks, bank CRE concentration, or private refinancing negotiations. The test uses only free public data:

- FRED CRE loan delinquency rate, release-lagged;
- FRED 10-year Treasury yield pressure;
- public office REIT market stress;
- yfinance adjusted-close data for regional-bank, REIT, mortgage-REIT, and CMBS proxies.

## Motivation And Literature

The task is motivated by the 2025-2026 CRE concern that remote work lowered office demand while higher rates made refinancing harder. Three sources define the context:

- Federal Reserve, *Financial Stability Report*: motivates monitoring commercial real estate and bank exposure. <https://www.federalreserve.gov/publications/financial-stability-report.htm>
- FRED `DRCRELEXFACBS`: delinquency rate on commercial real estate loans excluding farmland, all commercial banks. <https://fred.stlouisfed.org/series/DRCRELEXFACBS>
- Gupta, Mittal, Peeters, and Van Nieuwerburgh, remote-work / office-CRE evidence. <https://www.nber.org/papers/w30526>

Internal priors:

- `K1332`: listed BDC/private-credit proxies helped `BKLN` and `HYG`, but not `KRE`.
- `K1499`: BDC-RV raw lead-lag was mostly market beta after SPY-vol control; only a narrow HYG short-horizon NAV-discount proxy survived.
- `K1450`: REIT regime story is narrow; VNQ remains equity-like, with the cleanest rate-regime result in `VNQ-TLT` correlation rather than broad RV prediction.

## Data

Market data: yfinance `auto_adjust=True` close prices.

Targets:

- Regional banks: `KRE`, `KBE`
- REITs: `VNQ`, `IYR`, `XLRE`
- Mortgage / CMBS proxies: `REM`, `CMBS`
- Office REIT basket: equal-weight daily return basket of `BXP`, `VNO`, `SLG`, `KRC`, `HIW`, `CUZ`, `DEI`

Controls:

- own lagged 21-day log RV;
- SPY lagged 21-day log RV;
- lagged VIX z-score;
- lagged credit spread stress proxy from `-(HYG - LQD)` 21-day cumulative return.

FRED:

- `DRCRELEXFACBS`, quarterly, 1991-01-01 to 2026-01-01 in cache;
- `DGS10`, daily, 1962-01-02 to 2026-06-25 in cache.

## Method

Signals:

1. `cre_fundamental_pressure`: average z-score of release-lagged CRE delinquency level, one-year delinquency change, and 10Y yield level.
2. `office_market_stress`: average z-score of office REIT 21-day RV and 63-day drawdown.
3. `combined_cre_pressure`: average of the fundamental and office-market signals.

Lookahead controls:

- FRED quarterly CRE delinquency is treated as unavailable until quarter-end plus 50 calendar days, then forward-filled to trading days.
- Every predictive signal is explicitly stored as `*_lag1 = raw.shift(1)`.
- Forward labels use strictly `[t+1, t+H]`:
  - `ret.shift(-1).rolling(H).std().shift(-(H-1))`
  - downside variance uses the same forward window on `min(ret, 0)^2`.
- HAC / Newey-West `maxlags = H` for overlapping 5-day and 21-day labels.

Primary tests:

- 8 targets x 2 horizons x 2 outcomes x 3 signals = 96 primary hypothesis tests.
- Outcomes: `log_fwd_rv`, `log_fwd_downside_var`.
- Regression: outcome on one CRE signal plus own RV, SPY RV, VIX, and credit-stress controls.
- Multiple testing: Bonferroni and Holm.
- Success threshold: positive coefficient, Holm p < 0.05, and Harvey-style `|t| >= 3`.

Diagnostics:

- Spearman block bootstrap for primary cells, block size `H`, `B=1000`, seed 42.
- Top-decile event study for combined pressure and 21-day forward log RV, moving-block bootstrap `B=1000`.

## Results

Verdict: `WEAK_PARTIAL`.

Only two primary cells survive Holm plus Harvey, both on `CMBS` 5-day forward RV:

| Target | Horizon | Outcome | Signal | Coef | HAC t | p | Holm p |
|---|---:|---|---|---:|---:|---:|---:|
| CMBS | 5 | log forward RV | combined CRE pressure | +0.214 | +4.30 | 1.73e-05 | 0.00166 |
| CMBS | 5 | log forward RV | office market stress | +0.166 | +4.04 | 5.38e-05 | 0.00511 |

No `KRE`, `KBE`, broad REIT, mortgage REIT, or office REIT basket coefficient survives the primary multiple-testing gate.

The nearest raw positive but non-surviving cells:

| Target | Horizon | Outcome | Signal | HAC t | Holm p |
|---|---:|---|---|---:|---:|
| REM | 5 | log forward RV | CRE fundamental pressure | +2.39 | 1.00 |
| KBE | 5 | log forward RV | combined CRE pressure | +2.10 | 1.00 |
| KRE | 5 | log forward RV | office market stress | +1.94 | 1.00 |

Spearman diagnostics show broad positive raw rank correlations for combined pressure and forward RV, e.g. `KRE h=21 rho=0.223`, `VNQ h=21 rho=0.331`, `REM h=21 rho=0.390`, and `OFFICE_REIT_BASKET h=21 rho=0.367`. These raw correlations do not establish incremental predictability because the HAC regressions control own volatility, SPY volatility, VIX, and credit stress.

Top-decile event diagnostics are also directionally high but mostly unconditional:

| Target | h=21 top-decile exp(log RV) ratio | Log-RV diff CI | Bootstrap p |
|---|---:|---|---:|
| KRE | 1.81x | [-0.258, +0.747] | 0.328 |
| KBE | 1.93x | [-0.144, +0.796] | 0.222 |
| VNQ | 2.11x | [+0.138, +0.905] | 0.004 |
| IYR | 2.16x | [+0.184, +0.940] | 0.000 |
| XLRE | 2.51x | [+0.096, +1.030] | 0.016 |
| REM | 4.15x | [+0.394, +1.485] | 0.000 |
| CMBS | 2.02x | [+0.282, +0.985] | 0.000 |
| Office basket | 1.69x | [+0.037, +0.918] | 0.038 |

Interpretation: CRE pressure states coincide with high future REIT/CMBS volatility, but once the regression controls for lagged own volatility and broad market risk, the incremental lead-lag claim narrows to short-horizon `CMBS` RV.

## Verdict

`WEAK_PARTIAL`.

The data do not support a broad claim that office-CRE refinancing pressure robustly predicts regional-bank or REIT volatility. The only family-corrected positive result is narrow: office/combined CRE pressure leads `CMBS` 5-day forward RV. This is plausible but should be treated as a public-market CMBS-proxy finding, not as direct evidence about bank loan books or the office-refinancing wall.

## Limitations

- FRED CRE delinquency is quarterly and slow-moving; release-lagging is conservative but reduces signal timeliness.
- Office REIT prices are themselves market variables; office-market stress can partly proxy general risk aversion despite SPY/VIX controls.
- `CMBS` ETF trading history and liquidity may differ from actual conduit CMBS spreads.
- There is no direct bank-level CRE exposure weighting in this experiment.
- Top-decile event results are descriptive; primary inference is the HAC regression with multiple-testing correction.

## Reproduce

```bash
uv run python experiments/k1570/k1570.py
```

Expected runtime with cache is about 15 seconds. Use `--refresh` to re-download yfinance and FRED data.

## Files

- `k1570.py`
- `k1570_results.json`
- `k1570_analysis_dataset.csv`
- `fig1_cre_pressure_signals.png`
- `fig2_hac_tstat_heatmap.png`
- `fig3_top_decile_event.png`
- `data/` cached yfinance/FRED CSV files with hashes recorded in results JSON
