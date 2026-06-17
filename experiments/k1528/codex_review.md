# K1528 Codex Review

**Review date:** 2026-06-17
**Reviewer:** Codex CLI
**Verdict:** PASS for implementation integrity; empirical verdict remains NULL.

## Scope

Reviewed:

- `experiments/k1528/k1528.py`
- `experiments/k1528/k1528_results.json`
- `experiments/k1528/README.md`

## Lookahead Audit

PASS.

- Rolling sentiment beta for month `t` is estimated with `hist = idx[pos - 60:pos]`, which excludes month `t`.
- Month `t` portfolio return is computed from `returns.loc[dt]` after sorting on beta already estimated from `[t-60, t-1]`.
- The fixed universe avoids dynamic membership peeking, but creates survivorship bias. README/results disclose this as a limitation.
- yfinance is called with `auto_adjust=False` and the script explicitly uses `Adj Close`.

## Randomness / Reproducibility

PASS.

- `SEED = 42`.
- Moving-block bootstrap uses `np.random.default_rng(seed)`.
- No stochastic process besides bootstrap.

## Statistical Tests

PASS with caveat.

- Trading comparison uses `volpred.stats.model_evaluation.strategy_dm_test`.
- Harvey threshold is enforced as `|t| > 3`.
- Fama-MacBeth slopes use Newey-West style HAC with lag 3.
- Bootstrap CI uses 6-month moving blocks and 1000 repetitions.
- Caveat: this is a pilot with a current large-cap universe, not a CRSP-grade cross-section.

## Claim/Evidence Match

PASS.

Key results in README match `k1528_results.json`:

- VIX optimism high-low annualized return `-0.0951`, DM `t=1.898`, Fama-MacBeth `t=-2.129`.
- UMCSENT high-low annualized return `+0.0067`, DM `t=-0.180`, Fama-MacBeth `t=-0.287`.
- Overall verdict `NULL`.

## Overclaim Check

PASS.

The README correctly states that the result only rejects this free VIX/UMCSENT
proxy implementation. It does not claim to falsify Hasan/Kumar/Taffler's
proprietary emotion dictionary result.
