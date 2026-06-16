# Codex Review: mile_b722be0e / K998

Date: 2026-06-16
Task: `paper_review_mile_b722be0e`
Article: `mile_b722be0e`
Experiment: `experiments/k998/k998.py`

## Verdict

CONDITIONAL_PASS_RESOLVED

The article's null-result direction is supported after fixes. K998 does not provide a tradable VRP timing signal: Granger tests are significant at short horizons, Newey-West controlled `|t|` statistics stay below the Harvey `|t| > 3` hurdle, lookahead-clean OOS R2 is mostly negative, and the variance-swap signal Sharpe is negative.

## Critical Findings

1. Fixed h-step OOS R2 target-overlap lookahead. The original expanding-window loop trained on pairs whose target dates could be after the forecast origin for `h>1`. The corrected loop only uses training pairs with `target_date <= forecast_origin`.
2. Fixed article-method mismatch in the variance-swap direction. Code uses `g_{t-1}` above the expanding median to sell variance and below median to buy variance; the article previously described the opposite.
3. Fixed overclaim around Clark-West. The code computes a simplified one-sided DM/CW-style squared-error test, not the full Clark-West nested-model adjustment. Article wording now says simplified CW-style.

## Checks Passed

1. VRP proxy uses lagged VIX: `(VIX_{t-1}/100)^2/252 - r_t^2`.
2. Rolling A4f refits use windows ending before the OOS segment being filtered.
3. Strategy signal uses `g_{t-1}` for payoff at `t`.
4. Predictive regressions use Newey-West HAC standard errors and apply the Harvey `|t| > 3` threshold.
5. Published article numbers now match `k998_results.json` after rerun:
   - Granger F: 66.17, 32.03, 17.95, 2.12.
   - Controlled NW t: -2.15, -1.91, -1.61, -1.40.
   - OOS R2 g-only: 0.011, -0.033, -0.068, -0.011.
   - Strategy Sharpe: -1.06 vs always-sell +0.85.

## Remaining Caveats

1. VRP is a daily proxy, not option-level model-free VRP.
2. The OOS period includes COVID, which dominates VRP tail noise.
3. The single-asset SPY result should not be generalized to cross-asset VRP without a separate experiment.
4. Remote `feed-sync --apply` was not retried in this task because the same command timed out twice earlier in the hourly tick; local canonical feed/report files were updated with `publish_draft.py --update`.
