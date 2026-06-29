# K478-v2: Entropy-Based Volatility Prediction

Status: **NULL after source-review fix**
Original article under review: `mile_96ec845f`
Corrected rerun timestamp: see `k478_entropy_vol_results.json`

## Why This Rerun Exists

The 24h source review found that the original K478 pipeline had three production blockers:

1. Expanding OLS used forward-label rows whose 21-day target had not fully realized at the forecast origin.
2. DM tests used the default one-step HAC convention despite a 21-trading-day overlapping target.
3. The DM figure mislabeled the winner direction for VIX.

This v2 rerun keeps the original research question but fixes the timing and inference contract.

## Data

- Source: `yfinance`
- Assets: SPY and `^VIX`
- Daily rows: 5,283
- Sample: 2005-01-03 to 2025-12-31
- IS/OOS split: OOS starts 2023-01-01
- OOS rows: 752; valid 21-day forward-target forecasts: 731 for full-sample models

## Method

Target is future realized variance:

`rv21_fwd[t] = sum(ret2[t+1] ... ret2[t+21])`

Lookahead defence:

- `rv21_lag`, `vix_lag`, and all entropy predictors are shifted by one trading day.
- Expanding OLS training row `j` is eligible for forecast row `i` only if `j + 21 < i`.
- Pairwise DM tests align losses by common forecast date before comparing models.
- DM loss differential is `baseline_loss - challenger_loss`; positive DM t means the challenger has lower loss.
- Newey-West HAC lag is 21, matching the overlapping target horizon.

Entropy features:

- Sample Entropy: `m=2`, `r_mult=0.2`
- Permutation Entropy: order 3, delay 1, normalized
- Shannon Entropy: 20 histogram bins

No random procedure is used.

## Corrected OOS Results

QLIKE is lower-is-better.

| Model | Features | OOS QLIKE | n | Common-sample QLIKE gain vs M1 | DM-HAC p |
|---|---:|---:|---:|---:|---:|
| M1 | lagged RV21 | 0.338564 | 731 | baseline | baseline |
| M2 | RV21 + Sample Entropy | 0.383941 | 159 | +17.37% | 0.448 |
| M3 | RV21 + Permutation Entropy | 0.347587 | 731 | +2.67% | 0.136 |
| M4 | RV21 + Shannon Entropy | 0.342450 | 731 | +1.15% | 0.408 |
| M5 | RV21 + all entropy | 419.413748 | 159 | +128108.91% | 0.276 |
| M6 | VIX | 0.278925 | 731 | -17.62% | 0.065 |
| M7 | VIX + all entropy | 2300.824325 | 159 | +703229.79% | 0.161 |

Interpretation:

- No entropy-augmented model beats the lagged-RV baseline on corrected DM-HAC inference.
- M3 and M4 are worse than baseline on average, but not significantly after 21-lag HAC.
- Sample-entropy models remain too sparse (`n=159`) and unstable for production claims.
- VIX is still economically best, but the corrected 21-lag DM p-value is 0.065, so the production wording must be "borderline at 10%, not 5% significant."

## IS Diagnostics

Granger-like IS tests:

- Sample Entropy: F=0.428, p=0.513
- Permutation Entropy: F=5.113, p=0.0238
- Shannon Entropy: F=0.995, p=0.319

Permutation entropy has a weak in-sample trace, but its OOS QLIKE worsens by 2.67% and DM-HAC does not reject equal predictive accuracy. This is a classic in-sample shadow that does not survive the OOS forecast test.

## Article Implication

The null conclusion survives, but the old `mile_96ec845f` article should **not** be republished unchanged. Correct framing is:

- Entropy complexity signals do not add robust OOS value beyond lagged realized volatility.
- VIX remains the strongest average predictor in this setup.
- VIX's corrected DM evidence is borderline after 21-day HAC, not a clean 5% result.

## Files

- `k478_entropy_vol.py`: corrected experiment runner
- `k478_entropy_vol_results.json`: corrected canonical results
- `make_figs.py`: regenerated article figures with fixed DM direction labels
- `k478_qlike_comparison.png`
- `k478_dm_pvalues.png`
- `k478_granger_summary.png`
