# TIPS Breakeven Volatility and Corporate Bond ETF Risk

## Purpose

This experiment tests whether volatility of TIPS breakeven inflation changes
adds predictive information for corporate bond ETF risk. It is intentionally
orthogonal to the existing breakeven-inflation level regime idea: the treatment
variable here is realized volatility of daily T5YIE/T10YIE changes over 21 and
63 trading days, not the level of expected inflation.

## Motivation and Prior Context

Targeted project-memory search before execution found adjacent but distinct
results: private-credit proxies improved BKLN/HYG volatility forecasts in one
earlier experiment, while several corporate-credit narrative and macro stress
proxies were weak or null. The project backlog also contains a separate BEI
level-regime idea for SPY/TLT, so this task focuses on corporate credit and
breakeven volatility.

Literature and data references checked before design:

- Ceballos, "Inflation Volatility Risk and the Cross-section of Corporate Bond
  Returns" (SSRN).
- Kang and Pflueger, "Inflation Risk in Corporate Bonds".
- FRED T5YIE/T10YIE breakeven inflation series and ICE BofA OAS series.

## Design

Data sources:

- FRED: `T5YIE`, `T10YIE`, `BAMLH0A0HYM2`, `BAMLC0A0CM`.
- yfinance adjusted close: `LQD`, `HYG`, `BKLN`, `SPY`, `^VIX`.

Feature construction:

- BEI level controls: T5YIE, T10YIE, slope, and daily changes.
- BEI volatility treatment: 21d/63d average realized volatility and curve-slope
  volatility of daily T5YIE/T10YIE changes.
- Market controls: VIX level/change and SPY 22d realized variance.
- All non-target features are shifted by one trading day with `raw.shift(1)`.

Targets:

- LQD/HYG/BKLN 5d and 22d forward realized variance.
- LQD/HYG/BKLN 5d and 22d forward downside variance.
- HY and IG OAS 5d and 22d forward spread-change variance.

OOS comparison:

- Baseline: own lagged target variance plus BEI level/change and market controls.
- Augmented: baseline plus BEI volatility features.
- Expanding OLS on log target, refit every 21 observations.
- At forecast date `t`, the training set excludes any row whose forward target
  window would not have ended by `t-1`.
- QLIKE orientation is `actual / predicted - log(actual / predicted) - 1`.
- DM/HAC test is applied to baseline loss minus augmented loss; positive t-stat
  favors BEI-vol augmented forecasts. Harvey-style practical threshold: `|t| > 3`.

## Run

```bash
uv run python experiments/research_tips_breakeven_volatility_corporate_bond_return/research_tips_breakeven_volatility_corporate_bond_return.py
```

## Required Outputs

- `research_tips_breakeven_volatility_corporate_bond_return.py`
- `research_tips_breakeven_volatility_corporate_bond_return_results.json`
- `results.json`
- `summary_table.csv`
- `figures/bei_vol_timeseries.png`
- `figures/oos_qlike_dm_tstats.png`
- `codex_review.md`

## Initial Success Criteria

Evidence for a publishable edge requires more than a single positive chart. The
augmented model should show positive OOS QLIKE improvement with Harvey-level DM
support across multiple ETF targets or horizons after controlling for BEI
levels, VIX, SPY risk, and the target's own lagged realized variance.

## Results

Final run: 2026-06-24 local session.

Aggregate OOS result:

- Valid OOS cells: 16.
- Positive Harvey-level QLIKE cells: 0.
- Negative Harvey-level QLIKE cells: 0.
- Median QLIKE improvement from adding BEI-vol features: -3.17%.
- Mean QLIKE improvement from adding BEI-vol features: -8.97%.
- Verdict: `null_or_mixed_negative`.

ETF cells had a few positive short-horizon QLIKE improvements, especially HYG
and BKLN 5d future realized variance, but the QLIKE DM t-statistics were only
about 1.5 to 1.8 and did not clear the conservative threshold. Longer-horizon
and downside-variance cells were mixed to negative. The short FRED OAS sample
was negative across HY and IG spread-change variance cells.

| Asset | Target | Horizon | OOS N | QLIKE Improvement % | QLIKE DM t |
|---|---|---:|---:|---:|---:|
| LQD | future_rv | 5 | 2124 | 7.40 | 1.53 |
| LQD | future_downside_var | 5 | 2030 | -2.48 | -0.81 |
| LQD | future_rv | 22 | 2107 | -13.25 | -0.94 |
| LQD | future_downside_var | 22 | 2107 | -20.24 | -1.06 |
| HYG | future_rv | 5 | 2124 | 25.59 | 1.76 |
| HYG | future_downside_var | 5 | 2034 | 6.38 | 1.36 |
| HYG | future_rv | 22 | 2107 | 7.70 | 1.23 |
| HYG | future_downside_var | 22 | 2107 | 2.53 | 0.40 |
| BKLN | future_rv | 5 | 2124 | 19.09 | 1.63 |
| BKLN | future_downside_var | 5 | 1890 | 3.96 | 0.63 |
| BKLN | future_rv | 22 | 2107 | -3.86 | -0.46 |
| BKLN | future_downside_var | 22 | 2107 | -13.93 | -0.96 |
| HY_OAS | spread_change_var | 5 | 224 | -9.37 | -1.11 |
| HY_OAS | spread_change_var | 22 | 214 | -72.13 | -1.75 |
| IG_OAS | spread_change_var | 5 | 220 | -12.61 | -1.60 |
| IG_OAS | spread_change_var | 22 | 214 | -68.33 | -1.89 |

Interpretation: lagged breakeven volatility is not a robust standalone
corporate-credit risk predictor after controlling for BEI levels, BEI changes,
VIX, SPY risk, and own lagged risk. The result should be recorded as a null or
mixed-negative finding, not promoted into a publishable strategy or article
without a new mechanism or stricter sample design.

## Limitations

- FRED corporate OAS CSV endpoints returned only 2023-06-26 onward in this
  session, so OAS spread-variance tests are short-sample diagnostics.
- ETF tests use adjusted-close ETF returns, not intraday or option-implied
  volatility.
- Overlapping targets are handled with HAC inference and OOS train-window
  embargoing, but multiple cells still require conservative interpretation.
