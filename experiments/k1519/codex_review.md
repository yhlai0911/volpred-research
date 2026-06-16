# K1519 Codex Review

- **Reviewer**: Codex
- **Date**: 2026-06-17
- **Verdict**: `CONDITIONAL_PASS`

## Scope

Reviewed `experiments/k1519/k1519.py` and `k1519_results.json` for research integrity, lookahead risk, statistical claim strength, and claim-evidence match.

## Checks

1. **Lookahead**: PASS. Monthly EPU is transformed to a signal only after `month_end + 2 BDay`; expanding quantile threshold is shifted by one month before signal classification. The EPU trigger is therefore predetermined relative to daily state outcomes.
2. **Model fitting**: CONDITIONAL PASS. Both SPY and TAIEX MarkovRegression fits converged with `switching_variance=True`, `search_reps=8`, `em_iter=12`. The model is a volatility-state proxy, not a full Markov-switching GARCH.
3. **Inference**: PASS. Tests use Newey-West HAC `maxlags=21`; eight tests are corrected with BH and Bonferroni.
4. **Claim-evidence match**: PASS. The `NULL` verdict follows directly from corrected p-values: best raw p is SPY log-r² `0.0398`, but BH p is `0.319`; primary high-probability trigger p-values are SPY `0.150`, TAIEX `0.778`.
5. **Overclaim risk**: Controlled. README explicitly avoids claiming full MS-GARCH evidence or tradable forecasting value.

## Required Caveat

Any future article or paper note must describe this as "Markov volatility-state proxy evidence" rather than "Markov-switching GARCH evidence." A full MS-GARCH or time-varying-transition-probability model would be a separate experiment.
