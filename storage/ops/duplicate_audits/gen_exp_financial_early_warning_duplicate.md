# Duplicate Audit: gen_exp_financial_early_warning

**Task**: `gen_exp_金融股早期預警系統_K757_發現_Fubon_TSMC_Granger`

**Decision**: stale duplicate; do not re-run as a new experiment.

## Evidence

- `experiments/k1029/README.md` already extends K757 into a financial-stock early warning test:
  - Fubon / financial ETF Granger-cause 0050 and TSMC volatility in sample.
  - VIX-controlled partial Granger survives.
  - GARCH-X worsens OOS QLIKE versus baseline.
  - VT overlay improvement is marginal and risk-reduction driven.
- `experiments/k1432/README.md` is the stricter closure:
  - Builds a 5-stock Taiwan financial stress index.
  - Tests AR(1), HAR-RV, HAR-RV+VIX baselines against stress-augmented models.
  - Uses 2021-2026 OOS expanding-window forecasts and DM/HAC/HLN tests.
  - Verdict is `NULL`; stress augmentation significantly worsens several OOS forecasts.

## Fix Applied

- `research_program.md` now marks this open item as completed and references K1029 + K1432.
- `docs/error_log.md` records the stale checkbox / generator lesson.

## Reopen Condition

Only reopen this line if new data changes the identification problem, for example:

- Intraday Taiwan financial-stock / TSMC data.
- Private flow, order imbalance, or dealer balance-sheet stress data.
- A pre-registered design that is materially different from K1432's OOS HAR-RV/VIX comparison.
