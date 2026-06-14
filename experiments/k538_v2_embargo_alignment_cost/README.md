# K538 v2 embargo/alignment/cost refit

- Experiment ID: `k538_v2_embargo_alignment_cost`
- Parent task: `experiment_fix_k538_embargo_alignment_cost`
- Source experiment: `experiments/k538/`
- Created: 2026-06-15
- Data source: yfinance adjusted close snapshots saved under `data/`

## Motivation

Codex 24h review of article `mile_b70e8480` found three source-level issues in the
original K538 meta-labeling experiment:

1. The stated 22-day embargo was implemented through calendar-aligned split dates,
   leaving only 20-21 trading rows between train and test.
2. The classifier label used `excess_ret.shift(-1)`, while strategy evaluation applied
   predictions to same-index returns.
3. The 10 bps transaction cost was charged as a flat binary switch cost, not as a
   cost proportional to actual portfolio turnover.

This experiment reruns the same basic K538 question after correcting those three
items. It does not overwrite the original published K538 artifact.

## Method

- Row definition: features at row `t` are shifted to use information available at
  `t-1`; the label and strategy return are both evaluated on return day `t`.
- Label: `1` if `VT_return_t > B&H_return_t`, else `0`.
- Models: Logistic Regression, XGBoost, Random Forest.
- Features: same 16-feature set as K538.
- Cross-OOS: 3 periods with exactly 22 intervening trading rows between the final
  train row and first test row.
- Transaction cost: 10 bps per absolute change in SPY exposure. The VT baseline is
  also charged daily rebalancing turnover.
- Randomness: `SEED=42`; tree models use `n_jobs=1` for reproducibility.
- Data snapshots: `data/*_auto_adjust_2006_2025.csv`; reruns read these snapshots
  before falling back to yfinance.

References inherited from K538:

- Lopez de Prado (2018), *Advances in Financial Machine Learning*, Chapter 3.
- Prado (2018), "The 10 Reasons Most Machine Learning Funds Fail".
- Luo et al. (2023), "Meta-Labeling: Theory and Framework".

## Results

Sample: 2007-07-18 to 2025-12-31, 4,645 daily samples.

Feature-label correlations remain weak, but the strict old wording `|r| < 0.02` is
not valid under corrected alignment. The maximum absolute correlation is `0.030977`.

Cross-OOS average Sharpe:

| Model | AUC | Meta | VT net | B&H | Meta beats VT | Meta beats B&H |
|---|---:|---:|---:|---:|---:|---:|
| Logistic | 0.4704 | 1.292 | 1.054 | 1.328 | 2/3 | 1/3 |
| XGBoost | 0.5010 | 1.276 | 1.054 | 1.328 | 2/3 | 1/3 |
| Random Forest | 0.4958 | 1.342 | 1.054 | 1.328 | 3/3 | 1/3 |

Walk-forward:

| Model | VT usage | Switches | Meta Sharpe | VT net Sharpe | B&H Sharpe |
|---|---:|---:|---:|---:|---:|
| Logistic | 58.2% | 704 | 0.771 | 0.868 | 0.890 |
| XGBoost | 66.6% | 1,223 | 0.701 | 0.868 | 0.890 |
| Random Forest | 0.0% | 0 | 0.890 | 0.868 | 0.890 |

## Conclusion

The corrected refit preserves the qualitative K538 article conclusion: daily
meta-labeling does not learn a stable useful switch. The corrected numbers are
materially different, especially because VT now pays rebalancing turnover cost and
the label/return alignment changed, but the best walk-forward Random Forest simply
degenerates to buy-and-hold.

Article action: no retraction. The existing errata is directionally sufficient. A
full revision should replace the old K538 magnitudes with this v2 result set and
remove the strict `|r| < 0.02` claim.

## Artifacts

- `k538_v2_embargo_alignment_cost.py`
- `k538_v2_embargo_alignment_cost_results.json`
- `k538_v2_cross_oos_sharpe.png`
- `k538_v2_walkforward_behavior.png`
- `data/*_auto_adjust_2006_2025.csv`
