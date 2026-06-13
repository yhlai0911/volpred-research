# k_explainable_ensemble_vol_gate_2026_06_14

## Research Question

Can an explainable tree ensemble improve SPY volatility forecasts over a HAR/GJR-style linear baseline, and should it pass a feature-stability gate before any strategy or production use?

This is a governance-oriented ML experiment. It does not ask whether a model can win one aggregate metric by a large crisis-year outlier; it asks whether the gain is statistically robust and explainable enough to deploy.

## Motivation

`research_program.md` queued this topic as:

- RandomForest/XGBoost/LightGBM-style ensemble on HAR/GJR, macro, ETF, and credit proxies.
- Track walk-forward feature-importance or SHAP rank drift.
- If QLIKE improves but explanations are unstable, mark the model as not deployable.

Nearby VolPred lessons require a high bar:

- Pure XGBoost and neural-volatility attempts have often failed the daily-frequency ML ceiling.
- VIX frequently acts as a sufficient statistic for SPY volatility.
- Prior review incidents show that QLIKE gains can be artifacts if timing, target alignment, or baseline behavior is not audited.

## Literature Preamble

1. CFA Institute (2025), *Ensemble Learning in Investment*: ensembles can improve supervised finance models, but investment use requires explainability and governance.
2. CFA Institute (2025), *Explainable AI in Finance*: financial AI explanations must support validation and stakeholder oversight.
3. Patton (2011), *Journal of Econometrics*: QLIKE is a proxy-robust volatility forecast loss under the relevant assumptions.
4. Corsi (2009), *Journal of Financial Econometrics*: HAR-RV motivates daily/weekly/monthly realized-volatility features.

## Data

- Source: `yfinance`
- Sample request: `2006-01-01` to `2026-06-14`
- Target: SPY forward 5-trading-day mean squared log return
- OOS folds: calendar years `2016` through `2025`
- Training: yearly walk-forward refit, last `2000` eligible rows
- Predictors: HAR/GJR-style SPY volatility features, VIX level/change/spread, and TLT/HYG/LQD/GLD/EEM/XLK/XLF ETF return/volatility proxies

## Leakage Controls

- Feature date `t` predicts SPY variance over `t+1` through `t+5`.
- For every OOS year, a training row is allowed only when its `target_end_date < OOS start`, so forward targets never cross the train/test boundary.
- DM uses `h=5` HAC because the target windows overlap.
- All model forecasts in a fold share the same train-only variance floor/cap: 1% target quantile floor and `5x` 99% target quantile cap. This prevents a trivial QLIKE result from a near-zero forecast in a crisis.

## Models

- Baseline: Ridge regression on HAR/GJR-style features, trained on log variance.
- Ensemble members: RandomForest, XGBoost, and sklearn HistGradientBoosting.
- Environment caveat: `lightgbm` and `shap` were not installed. The experiment therefore uses walk-forward permutation importance as a model-agnostic XAI rank-stability proxy, not literal SHAP values.

## Main Result

Verdict: **NOT_DEPLOYABLE_AVERAGE_GAIN_UNSTABLE_NOT_HARVEY_SIGNIFICANT**.

The ensemble has a lower aggregate QLIKE than HAR/Ridge, but it fails the formal deployment gate:

- Aggregate QLIKE: ensemble `0.704` vs HAR/Ridge `10.668`, raw improvement `93.4%`.
- DM test: `t=-1.45`, `p=0.148`; this fails the Harvey `|t| > 3` threshold.
- Positive yearly improvement: `9/10` years; median yearly improvement `11.4%`.
- Sensitivity excluding 2020: ensemble `0.460` vs HAR/Ridge `0.501`, improvement `8.1%`, DM `t=-1.65`, still not Harvey-significant.
- Feature stability gate fails: adjacent-fold Spearman `0.159`, top-5 Jaccard `0.371`, normalized rank drift `0.289`.

Top aggregate importance features:

1. `vix_daily_var`
2. `spy_ret_10d`
3. `vix_z_63d`
4. `spy_ret_126d`
5. `hyg_ret_22d`

## Interpretation

The honest reading is:

1. The ensemble is directionally useful as a descriptive forecast combiner, especially around the 2020 crisis fold.
2. It does not clear VolPred's formal Harvey-style evidence bar.
3. Its explanation layer is too unstable for deployment, even though VIX remains the top average feature.
4. This supports a governance rule: ML volatility models need both QLIKE/DM evidence and feature-stability evidence before they can be considered production candidates.

## Files

- `k_explainable_ensemble_vol_gate_2026_06_14.py`
- `k_explainable_ensemble_vol_gate_2026_06_14_results.json`
- `walk_forward_predictions.csv`
- `feature_importance_by_fold.csv`
- `fig_qlike_by_year.png`
- `fig_mean_permutation_importance.png`
- `fig_feature_rank_drift.png`

## Reproduce

```bash
uv run python experiments/k_explainable_ensemble_vol_gate_2026_06_14/k_explainable_ensemble_vol_gate_2026_06_14.py
```
