# K1590 Codex Review

**Date**: 2026-07-01 Asia/Taipei
**Reviewer**: Codex CLI primary path
**Verdict**: CONDITIONAL_PASS

## Scope

Reviewed `experiments/k1590/k1590_diagnostic.py`,
`experiments/k1590/k1590_diagnostic_results.json`, and `README.md`.

Focus areas from task brief:

- yfinance adjusted-close alignment
- VIX-regime Welch t-test assumptions
- skew / kurtosis sample-bias handling
- `|MNA| = abs(log_ret)` as a daily volatility proxy

## Findings

1. **Adjusted-close handling: PASS.** The script calls `yf.download(...,
   auto_adjust=False)` and explicitly selects `Adj Close` when available,
   falling back to `Close` only if needed (`k1590_diagnostic.py:72-98`).
   This satisfies the yfinance default-change guard.

2. **Return alignment: PASS.** Log returns use aligned close columns and
   `mna` is the anchor index. Correlations use a complete-case frame
   (`k1590_diagnostic.py:107-123`, `175-193`). This is sufficient for a
   descriptive diagnostic.

3. **Lookahead: CONDITIONAL_PASS.** The primary VIX-regime split uses
   same-day VIX close to classify same-day `|MNA return|`, but the script
   clearly labels this as descriptive and also reports a lagged VIX
   robustness check (`k1590_diagnostic.py:149-152`, `221-229`). No
   forecasting or signal-return mapping is claimed.

4. **Welch t-test: CONDITIONAL_PASS.** High-VIX `|MNA|` is strongly larger
   than low-VIX `|MNA|` (t=5.13, p=8.79e-7, ratio=3.05), and lagged VIX
   robustness also passes (t=4.77, p=4.33e-6). However, absolute returns are
   heavy-tailed and high-VIX N is 149 vs low-VIX N 924, so Phase 2 should add
   bootstrap or rank-based robustness before any publication-strength claim.

5. **Skew/kurtosis: PASS with caveat.** The script uses SciPy unbiased
   estimators (`bias=False`) for skew and excess kurtosis
   (`k1590_diagnostic.py:127-138`). Results show MNA skew=-2.89 and excess
   kurtosis=66.4. These are descriptive tail diagnostics, not stable
   parameter estimates.

6. **Daily vol proxy: CONDITIONAL_PASS.** `abs(log_ret)` is a defensible daily
   volatility proxy for a GO/NO-GO diagnostic, and limitations explicitly say
   it is not intraday RV (`k1590_diagnostic_results.json:311-318`). Phase 2
   should use realized variance / GARCH / HAR-RV before forecast claims.

7. **README numeric drift: FIXED.** The original README correlation table had
   IWM and VIX-level values inconsistent with `k1590_diagnostic_results.json`,
   and its mean absolute return row used stale values. README now matches the
   results JSON.

## Decision

K1590 may be recorded in `knowledge.json` as a **GO diagnostic** for a Phase-2
merger-arbitrage volatility research line. The knowledge entry must state that
this is descriptive evidence only: it does not establish antitrust causality,
individual deal-spread behavior, OOS forecast skill, or trading profitability.
