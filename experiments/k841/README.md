# K841: TAIFEX night-session VIX-timed hedge, corrected rerun

## Status and supersession

This 2026-07-15 rerun supersedes K841's pre-repair statistics and the old
reader-facing interpretation of its raw drawdowns. The original one-day
Diebold-Mariano helper used `for k in range(h)`. At `h=1` it included only
lag zero, so all seven reported tests used an iid variance estimate instead of
HAC. The corrected analysis delegates the positive squared-return loss streams
to `volpred.stats.model_evaluation.dm_test`; with 2,157 paired days the
canonical Bartlett Newey-West bandwidth is 13.

The rerun also fixes three defects encountered while reconstructing the
strategy returns:

1. A weight first known at the Taiwan open had been applied to the already
   realised previous-close-to-open gap.
2. Night hedges were closed at 05:00 and reopened at 15:00, but the old code
   charged futures cost only when the target ratio changed; S5 also omitted the
   stock rebalance cost already present in S1.
3. A Monday TAIFEX file can contain Friday PM, Saturday AM, and Monday day
   rows. The old first/last-date shortcut dropped the Saturday continuation.

The HAC-only reconstruction keeps the legacy strategy streams unchanged and
therefore isolates the inference defect. The final tables incorporate all four
repairs. These are two distinct comparisons and must not be conflated.

## Research question

Can a daily-VIX-timed TX night-session overlay improve the variance-risk
profile of a 0050.TW position or of an open-rebalanced 8.63/VIX allocation?

K841 is an empirical strategy-risk comparison, not a forecast-model horse
race and not a causal hedge-effectiveness study. Its DM estimand is the mean
difference in positive daily squared returns. Lower loss means lower realised
second-moment risk; it does not by itself rank mean return, Sharpe, utility, or
investor welfare.

## Data and frozen sample

- TAIFEX TX all-contract tick files from
  `/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python`.
- Within each file, the expiry with the highest full-file volume is selected.
  This is an ex-post continuous-contract convention, not an executable roll
  rule; no roll-date sensitivity is claimed.
- VIX and 0050.TW adjusted Open/Close are stored in
  `data/k841_yfinance_snapshot.csv` rather than downloaded during the primary
  run.
- Analysis period: 2017-05-16 through 2026-04-02.
- Paired trading days: 2,157.
- Frozen Yahoo snapshot SHA-256:
  `0465e20e98d0c82814fd36407b84aefe6e2edacfb604a5e4d8b55335e363c8ed`.
- Frozen final analysis-slice SHA-256:
  `452cdfa03edbd0c7d0b2f0a03dfa4024f8a3e842d74b74c58a2f66da4f8aad0d`.

The signal used for a night session is the last VIX close strictly before the
actual TX night-start date. It is therefore at least one US session stale and
can be older around holidays. This experiment does not test an intraday VIX or
VIX-futures signal.

## Strategies and execution timing

| ID | Definition |
|---|---|
| S0 | Buy and hold 0050.TW |
| S1 | 8.63/VIX weight set at the Taiwan open; the prior held weight remains on the overnight gap |
| S2 | S0 plus an always-on TX night hedge |
| S3 | S0 plus a 50% TX night hedge when the as-of VIX signal rises by more than 2 points |
| S4 | S0 plus a TX night hedge when the as-of VIX signal exceeds 20 |
| S5 | S1 plus the S2 night hedge |

The stock trade threshold is five percentage points. Stock turnover costs
0.30% per unit changed. Every active open-to-close night hedge pays the stated
0.01% round-trip futures cost, even when its ratio equals the previous night's
ratio. An unavailable night session carries no overlay position, P&L, or cost;
the stock leg remains invested and the missing night return is never imputed as
zero.

## HAC-only repair on the legacy strategy streams

The frozen legacy evidence reconstructs the committed pre-repair code and
reproduces its published metrics and iid DM statistics before applying the
canonical lag-13 HAC variance. Every t statistic changes, but none crosses the
repository's conservative `|t|>3` reporting screen.

| Comparison | Old iid t | Corrected HAC t | Old `|t|>3` | Corrected `|t|>3` |
|---|---:|---:|:---:|:---:|
| S2 vs S1 | 10.8213 | 6.7855 | yes | yes |
| S2 vs S0 | -7.1306 | -8.1976 | yes | yes |
| S3 vs S0 | -1.9712 | -2.3880 | no | no |
| S3 vs S1 | 14.0087 | 8.2635 | yes | yes |
| S4 vs S0 | -4.4320 | -5.5126 | yes | yes |
| S4 vs S1 | 12.1384 | 7.6436 | yes | yes |
| S5 vs S1 | -0.7583 | -0.4931 | no | no |

S3 vs S0 is nominally different at 5%, but remains below the pre-specified
multiple-testing screen. The legacy loss arrays are stored separately from the
final returns and are recomputed cell by cell in the methodology regression
test; they are not hand-transcribed summary statistics.

## Final corrected results

### Performance diagnostics

| Strategy | CAGR | Annual vol | Sharpe | Raw MDD |
|---|---:|---:|---:|---:|
| S0 | 19.47% | 19.74% | 1.0006 | -33.83% |
| S1 | 8.48% | 8.87% | 0.9628 | -15.01% |
| S2 | 10.49% | 16.77% | 0.6790 | -36.03% |
| S3 | 16.74% | 19.29% | 0.8995 | -33.65% |
| S4 | 12.37% | 18.04% | 0.7374 | -34.60% |
| S5 | -0.19% | 8.56% | 0.0205 | -26.84% |

Raw MDD is descriptive only. Several strategies differ in realised volatility
by more than 20%, so their raw MDD levels cannot establish timing or hedge
skill. The same limitation applies to the COVID subperiod; there is no
exposure-matched or phase-randomisation claim here.

### Canonical squared-return risk-loss DM

| Comparison | Role | HAC t | p | ACF(1) | `|t|>3` |
|---|---|---:|---:|---:|:---:|
| S2 vs S1 | cross-exposure diagnostic | 6.9707 | 4.18e-12 | 0.3199 | yes |
| S2 vs S0 | same-base overlay ablation | -7.6263 | 3.60e-14 | -0.1167 | yes |
| S3 vs S0 | same-base overlay ablation | -2.1031 | 0.0356 | 0.0580 | no |
| S3 vs S1 | cross-exposure diagnostic | 8.3627 | <2.22e-16 | 0.3288 | yes |
| S4 vs S0 | same-base overlay ablation | -5.1323 | 3.12e-7 | -0.1520 | yes |
| S4 vs S1 | cross-exposure diagnostic | 7.9821 | 2.22e-15 | 0.2965 | yes |
| S5 vs S1 | same-base overlay ablation | -0.7483 | 0.4544 | 0.1777 | no |

Positive t means the first strategy has higher mean squared-return risk loss;
negative t means lower risk loss. Only comparisons with the same base exposure
are claim-bearing. S2/S3/S4 versus S1 mix a full-stock base with an
open-delevered base and are retained only to supersede the old published cells.

## Conclusion

The h=1 iid defect materially distorted all seven DM magnitudes but did not
reverse any `|t|>3` classification. On the fully corrected return construction,
the always-on and high-VIX night overlays reduce squared-return risk relative
to their S0 base, while the spike overlay does not clear the conservative
screen and S5 does not differ from S1 on this risk proxy. That is not evidence
that the overlays improve total strategy performance: their mean returns,
costs, exposure, and utility differ.

The durable K841 finding is narrower than the old article wording. A stale
daily-VIX signal can label risk but cannot be called a real-time night hedge.
The experiment does not prove that TAIFEX night hedging is generally
unworkable; a tradable intraday VIX/VIX-futures signal and an ex-ante TX roll
rule remain untested.

## Reproduction and review

Run from the repository root:

```bash
uv run python experiments/k841/k841_futures_realtime_vt.py
uv run --extra dev python -m pytest experiments/k841/test_k841_methodology_repair.py -q
uv run python scripts/experiment_gates.py run --path experiments/k841
```

Primary artifacts:

- `k841_futures_realtime_vt.py`: frozen-input rerun and atomic outputs.
- `k841_futures_realtime_vt_results.json`: complete metrics, DM diagnostics,
  ACFs, lag sensitivity, caveats, and supersession metadata.
- `k841_strategy_returns.npz`: dated final returns and every final pointwise
  loss pair.
- `k841_legacy_dm_losses.npz`: dated positive squared-return losses rebuilt
  from the committed legacy program for HAC-only attribution.
- `test_k841_methodology_repair.py`: timing, cost, weekend-session, artifact,
  and cell-by-cell inference regressions.
- `review_certification_20260715.md` and `review_verdict.json`: independent
  byte-bound methodology review.

## References

- Diebold, F. X., and Mariano, R. S. (1995), “Comparing Predictive Accuracy,”
  *Journal of Business & Economic Statistics* 13(3), 253–263.
- Newey, W. K., and West, K. D. (1987), “A Simple, Positive Semi-Definite,
  Heteroskedasticity and Autocorrelation Consistent Covariance Matrix,”
  *Econometrica* 55(3), 703–708.
- Harvey, D., Leybourne, S., and Newbold, P. (1997), “Testing the Equality of
  Prediction Mean Squared Errors,” *International Journal of Forecasting*
  13(2), 281–291.
- Harvey, C. R., Liu, Y., and Zhu, H. (2016), “… and the Cross-Section of
  Expected Returns,” *Review of Financial Studies* 29(1), 5–68.
