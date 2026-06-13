# K480: Regime-Switching Tool Selection

## Status

- Experiment ID: `K480`
- Status: completed, reviewed with caveat
- Created: 2026-03-26
- Source script: `k480_regime_tool_selection.py`
- Results: `k480_regime_tool_selection_results.json`
- Data source: yfinance daily `SPY` OHLC and `^VIX` close

## Research Question

K467 and K476 created a forecasting-versus-tail-risk tradeoff: HAR/range-based models can improve average volatility forecasting, while GJR-GARCH is more reliable in VaR coverage. K480 asks whether model selection by market regime can get both benefits.

The tested idea is:

- calm regime: use HAR, because jumps and overnight gaps are less dominant;
- crisis regime: use GJR, because tail coverage matters more;
- intermediate regime: test fixed and ternary combinations.

## Data And Sample

- Asset: SPY
- Volatility regime proxy: `^VIX`
- Full data range in results: 2005-02-02 to 2026-03-25
- Observations after feature construction: 5,319
- Cross-OOS windows:
  - 2015-2016
  - 2017-2018
  - 2019-2020
  - 2021-2022
  - 2023-2024
- In-sample rolling window: 2,000 observations

Diagnostics from the results file:

- Return skew: -0.304
- Return excess kurtosis: 14.699
- ADF p-value: 2.84e-29
- ARCH-LM p-value: 5.63e-307
- VIX median: 16.80
- VIX max: 82.69

## Methods

The experiment compares six daily variance forecast approaches:

- `GJR`: GJR-GARCH(1,1), Student-t innovations
- `HAR`: HAR log-range forecast scaled to squared-return proxy level
- `Ens_50_50`: equal variance average of GJR and HAR
- `RS_Binary`: VIX < 20 uses HAR; VIX >= 20 uses GJR
- `RS_Ternary`: VIX < 15 uses HAR; 15 <= VIX < 25 uses the ensemble; VIX >= 25 uses GJR
- `Adaptive_63d`: selects GJR or HAR using past 63-day QLIKE

Forecast quality is evaluated by QLIKE against a squared-return proxy. Tail-risk quality is evaluated by 1% and 5% VaR coverage across the five OOS windows, using Kupiec unconditional coverage and Christoffersen independence tests. A VaR cell passes only when both tests pass.

Randomness: the experiment is deterministic aside from upstream data availability and optimizer behavior in `arch_model`.

## Lookahead And Timing Caveat

This experiment is valid as a diagnostic comparison of model switching rules, but not as a fully tradable ex-ante implementation.

The script stores same-day `^VIX` close at `vix_arr[i]` and uses it to select the regime for the same OOS date. The results file also records this limitation: "Uses same-day VIX - in practice need previous-day VIX for true out-of-sample." A production trading version must use `VIX.shift(1)` or an explicitly available intraday signal before applying the same day's return/VaR target.

This caveat weakens any claim that the switching rule is directly tradable. It does not strengthen the switching result; if anything, same-day VIX gives the regime-switching models more information than a real ex-ante rule would have.

## Results

Key results from `k480_regime_tool_selection_results.json`:

| Model | Avg QLIKE Rank | VaR Passes |
| --- | ---: | ---: |
| GJR | 4.2 | 7/10 |
| HAR | 4.4 | 3/10 |
| Ens_50_50 | 1.8 | 3/10 |
| RS_Binary | 4.0 | 4/10 |
| RS_Ternary | 2.0 | 5/10 |
| Adaptive_63d | 4.6 | 4/10 |

The 50/50 ensemble has the best average QLIKE rank, and the ternary regime rule is second. Neither preserves GJR's VaR coverage. The best switching method, `RS_Ternary`, passes 5/10 VaR tests versus GJR's 7/10.

## Conclusion

K480 is a negative result. Regime-switching improves average forecasting ranks relative to GJR in this setup, but it does not solve the joint forecasting and tail-risk requirement. For risk management, GJR remains the stronger baseline in this experiment.

The public article `mile_42b4330c` should state the same-day VIX timing caveat when describing the switching rule.

## Artifacts

- `k480_regime_tool_selection.py`
- `k480_regime_tool_selection_results.json`
- `k480_tradeoff_combo.png`
- `k480_var1_heatmap.png`
- `reviews/paper_review_mile_42b4330c_codex_20260612.md`
