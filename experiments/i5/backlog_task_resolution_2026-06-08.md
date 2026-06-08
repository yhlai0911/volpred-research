# Backlog Task Resolution — `research_regime_switching_correlation_hedging`

- **Task ID**: `research_regime_switching_correlation_hedging`
- **Resolved at**: 2026-06-08 台灣時間
- **Resolver**: Codex CLI
- **Resolution**: `duplicate_already_covered`

## Why this task is closed

The pending backlog item asks for a research experiment on regime-switching correlation hedging under the futures-hedging methodology track.

That topic is already covered by the existing repo experiment `I5`, which now has the required triplet:

- `experiments/i5/README.md`
- `experiments/i5/i5_regime_hedge_ratio.py`
- `experiments/i5/i5_regime_hedge_ratio_results.json`

`I5` directly tests whether hedge ratios should change across volatility regimes by using `VIX` as the regime classifier for the `SPY / ES=F` hedge pair.

## Existing result already answers the question

From `I5`:

- Regime-specific OHR range: `0.9521` to `0.9735`
- Static OHR: `0.9668`
- Static vs regime-aware variance reduction: both `0.9575`
- DM-style comparison: `t = 0.62`, not significant
- Conclusion: regime-aware hedging adds no meaningful value for this high-correlation equity-index hedge

This is substantively the same research question as `research_regime_switching_correlation_hedging`.

## Interpretation

The evidence says:

1. correlation-regime differences exist statistically,
2. but the OHR is economically stable,
3. and for `SPY / ES=F`, static OHR already captures almost all hedge value.

So the honest resolution is not to open a new experiment with a new K-id, but to mark this backlog item satisfied by `I5`.

## When this topic should be reopened

Only reopen as a new experiment if the scope is materially different, for example:

- lower-correlation cross-hedges
- commodity or FX hedge pairs
- explicit Markov-switching or state-space correlation models
- transaction-cost-aware regime switching

Absent that differentiation, creating another experiment would be duplicate evidence rather than new research.
