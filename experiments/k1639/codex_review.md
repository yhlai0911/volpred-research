# Codex Review - K1639

Verdict: `CONDITIONAL_PASS_NULL_HIERARCHICAL_DOES_NOT_BEAT_SIMPLE_BASELINES`

## Scope Reviewed

- `experiments/k1639/k1639.py`
- `experiments/k1639/k1639_results.json`
- Generated CSV and PNG outputs under `experiments/k1639/data/` and `experiments/k1639/figures/`

## Checks

- Re-ran the experiment from the script entry point.
- Confirmed JSON parses with `python -m json.tool`.
- Confirmed source compiles with `python -m py_compile`.
- Confirmed output files are non-empty.
- Checked lookahead convention: day `i` return is evaluated with `returns.iloc[i - LOOKBACK : i]`, excluding day `i`.
- Confirmed seed is fixed at `SEED = 42` and bootstrap settings are reported in results.

## Findings

No blocking issue found.

The substantive result is a null, not an implementation failure. ERC risk parity has the highest net Sharpe at 0.743. HERC-ERC is the best hierarchy method by Sharpe at 0.685, but its paired moving-block bootstrap Sharpe difference versus ERC is not positive: observed -0.058, 95% CI [-0.209, +0.091].

NCO minimum-variance and Schur-block MV are statistically worse than ERC by bootstrap Sharpe difference. Schur-block MV and minimum variance reduce MDD, but this comes with concentration in low-volatility sleeves and lower return.

## Limitations to Preserve

- Do not present `schur_block_mv` as a full reproduction of Cotton's Schur Complementary Allocation.
- Do not claim HRP/HERC "beats risk parity" from this experiment.
- The result is ETF-panel specific and uses monthly close-to-close execution with 5 bps per dollar traded.
