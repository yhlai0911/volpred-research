# K1666 Codex Review

Verdict: `CONDITIONAL_PASS`

Reviewed files:

- `experiments/k1666/K1666.py`
- `experiments/k1666/K1666_results.json`
- `experiments/k1666/README.md`

## Checks

- Lookahead: PASS. Path and HAR features are shifted with `signal = raw_signal.shift(1)`. Expanding OOS fits use `work.iloc[:i]`, so forecast row `i` is not in the training set.
- Randomness: PASS. `SEED = 42` is fixed; no stochastic fitting is used.
- QLIKE direction: PASS. Uses `volpred.stats.model_evaluation.qlike_pointwise(actual, predicted)`.
- Cross-asset inference: PASS. Aggregate results are date-clustered mean losses across SPY/QQQ; no asset-day iid pooled DM is used.
- Results JSON integrity: PASS. The writer uses tmp JSON, parses it with `json.load`, then `os.replace`.
- Proxy honesty: PASS. Results state that daily OHLC GK/C2C proxies are not 5-minute RV.

## Caveats

- The positive OOS result is strongest for the GK range proxy and for stress/post-shock subperiods. The 2010-2019 calm subperiod is directionally positive but does not clear Harvey `t < -3`.
- C2C QLIKE improves, but C2C MSE often worsens badly because the log-variance retransformation overpredicts variance. C2C should not be the headline evidence.
- SPY GK improves in QLIKE but worsens in MSE; QQQ GK is cleaner. The conclusion should remain QLIKE-specific and conditional.

No blocking issue found after these caveats were added to README/results.
