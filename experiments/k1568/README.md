# K1568: Federal Register rule-flow proxy and compliance-exposed ETF volatility

**Verdict**: `WEAK_RAW_ONLY`. Federal Register proposed-rule / rule-flow proxies have several raw positive associations with sector ETF forward RV/downside variance, but no positive controlled-HAC cell survives the 144-test Bonferroni/Holm family correction.

## Motivation

Backlog question: can regulatory-compliance burden beta identify RV regimes in mid-cap, small-bank, financial, health-care, industrial, retail, or other compliance-exposed equity proxies?

This experiment deliberately uses a narrow public proxy: daily Federal Register `RULE` and `PRORULE` publication flow. It does **not** observe actual compliance staff hours, legal spend, OIRA paperwork burden, RegData industry restrictions, bank supervisory burden, or firm-level compliance operating leverage.

## Data

- Federal Register API `documents.json`, 2012-01-01 to 2026-06-28:
  - `conditions[type][]=RULE`
  - `conditions[type][]=PRORULE`
  - 78,564 rule/proposed-rule documents cached in `data/federal_register_rule_prorule_documents.csv`.
- yfinance adjusted OHLCV, target/control ETF calendar through 2026-06-26:
  - Targets: `IJR`, `IWM`, `KRE`, `KBE`, `XLF`, `XLV`, `XLI`, `XRT`.
  - Controls: `SPY`, `^VIX`.
- Final aligned panel: 3,641 US trading rows from 2012-01-03 to 2026-06-26.

## Method

- Federal Register documents are assigned to the first target-ETF trading date on or after publication date.
- Rule-flow signals:
  - `rule_flow_stress`: rolling z-score of 5d and 21d `RULE` log-counts.
  - `proposed_rule_flow_stress`: rolling z-score of 5d and 21d `PRORULE` log-counts.
  - `combined_reg_flow_stress`: rolling z-score of combined rule/proposed-rule log-counts.
- Rolling z-score means and standard deviations end at `t-1`.
- Tested predictors are explicitly lagged: `signal_lag1 = signal.shift(1)`.
- Outcomes:
  - forward 5d / 21d log realized variance,
  - forward 5d / 21d log downside semivariance,
  - forward 5d / 21d average volume shock.
- Forward windows are strictly `[t+1, t+H]`.
- Primary regression:
  - `forward_outcome ~ signal_lag1 + own_log_RV21_lag1 + SPY_log_RV21_lag1 + VIX_level_lag1`
  - matching downside/volume lag controls are added for downside and volume outcomes.
- HAC maxlags equals horizon `H`.
- Spearman CI uses moving-block bootstrap with block=`H`, `B=1000`, seed=42.
- Tail AUC CI uses Hanley-McNeil normal approximation.

## Multiple Testing

Primary family:

`8 targets x 2 horizons x 3 outcomes x 3 signals = 144 controlled-HAC p-values`

Bonferroni alpha is `0.000347`. PASS would require a positive controlled-HAC coefficient to survive Bonferroni or Holm correction, with Spearman/AUC diagnostics only supporting the claim.

## Results

No positive primary cell survives Bonferroni or Holm correction.

Top raw cells:

| Cell | Controlled coef | HAC t | p | Spearman rho / CI | Tail AUC / CI | Status |
|---|---:|---:|---:|---:|---:|---|
| XLI 5d downside, `proposed_rule_flow_stress` | +0.505 | +3.19 | 0.0014 | +0.075 [0.019, 0.128] | 0.558 [0.520, 0.596] | raw-only |
| XLV 5d RV, `proposed_rule_flow_stress` | +0.082 | +3.16 | 0.0016 | +0.044 [-0.022, 0.106] | 0.495 [0.454, 0.536] | raw-only |
| XLI 5d RV, `proposed_rule_flow_stress` | +0.065 | +2.87 | 0.0041 | +0.052 [-0.014, 0.106] | 0.558 [0.520, 0.596] | raw-only |
| XLI 21d downside, `proposed_rule_flow_stress` | +0.111 | +2.77 | 0.0056 | +0.096 [-0.003, 0.189] | 0.557 [0.505, 0.609] | raw-only |
| XLV 5d RV, `combined_reg_flow_stress` | +0.067 | +2.70 | 0.0069 | +0.050 [-0.010, 0.105] | 0.554 [0.512, 0.596] | raw-only |

Interpretation: proposed-rule flow is directionally visible in industrials and health care, but the effect is weak, broad-family uncorrected, and mostly not supported by strong rank or tail diagnostics. It should be treated as a hypothesis-generation proxy, not as evidence of a robust compliance-burden volatility signal.

## Literature / Source Context

- Federal Register API documentation and `documents.json` endpoint: <https://www.federalregister.gov/developers/documentation/api/v1>
- QuantGov / RegData data access context: <https://www.quantgov.org/csv-download>
- Dawson and Seater (2013), "Federal Regulation and Aggregate Economic Growth", *Journal of Economic Growth*: <https://doi.org/10.1007/s10887-013-9088-y>
- Hassan et al. (2019), "Firm-Level Political Risk: Measurement and Effects", *Quarterly Journal of Economics*: <https://doi.org/10.1093/qje/qjz021>
- Goldschlag and Tabarrok (2018), "Is regulation to blame for the decline in American entrepreneurship?", *Economic Policy*: <https://doi.org/10.1093/epolic/eix021>

## Outputs

- `k1568.py` — reproducible script.
- `k1568_results.json` — all primary tests, source hashes, verdict, and diagnostics.
- `k1568_analysis_dataset.csv` — merged signal/target panel.
- `fig1_federal_register_rule_flow.png`
- `fig2_hac_tstat_rv_heatmap.png`
- `fig3_combined_signal_vs_kre_downside.png`
- `codex_review.md` — source-level review.

## Lookahead Policy

- Federal Register counts are aligned by publication date to the next target-ETF trading date and then lagged one trading day before prediction.
- Rolling z-score baselines use `.shift(1)` for means and standard deviations.
- Tested signal columns are explicit `*_lag1 = signal.shift(1)`.
- Forward targets use `[t+1, t+H]` via `shift(-i)` for `i=1..H`.
- RV and downside controls are lagged; volume controls use trailing-volume baselines ending at `t-1`.
- yfinance adjusted close/volume are treated as end-of-day public data; the one-day signal lag avoids same-day Federal Register publication timing ambiguity.
