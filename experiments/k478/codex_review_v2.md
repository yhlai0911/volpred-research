# K478-v2 Codex Remediation Review

Verdict: **PASS for corrected experiment artifacts; HOLD for old article republication**

Reviewed files:

- `experiments/k478/k478_entropy_vol.py`
- `experiments/k478/k478_entropy_vol_results.json`
- `experiments/k478/make_figs.py`
- `experiments/k478/README.md`

## Checks

- Lookahead: PASS. Predictors are shifted by one trading day, and expanding OLS now admits training row `j` only when `j + 21 < forecast_pos`.
- Forward target: PASS. `rv21_fwd[t]` is explicitly `sum(ret2[t+1] ... ret2[t+21])`.
- DM/HAC: PASS. Pairwise losses are aligned by common forecast date, the loss differential is documented as `baseline_loss - challenger_loss`, and Newey-West HAC lag is 21.
- Output path: PASS. The runner writes to `experiments/k478/k478_entropy_vol_results.json`.
- Figures: PASS. The DM figure labels winner direction from corrected common-sample QLIKE gain; VIX is no longer mislabeled as a baseline win.

## Production Implication

The original NULL conclusion survives, but `mile_96ec845f` should not be republished unchanged. Corrected DM-HAC weakens the VIX statement from clean 5% significance to borderline 10% evidence (`p=0.065`), while entropy models remain non-improving.
