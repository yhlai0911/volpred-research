# K1335 — VIX Term-Slope as Rule-Based VT Overlay

**Date**: 2026-06-15
**Worktree**: `.claude/worktrees/k1335` (branch `k1335-vix-term-slope-vt`)
**Status**: PENDING_REVIEW (awaiting Codex review per K1259 protocol)

## Motivation

VolPred online strategies (Conservative VT, Defensive VT) gate equity exposure on VIX *level* thresholds (e.g. VIX > 20 → cash). Term-structure literature shows VIX/VIX3M slope contains additional regime information beyond VIX level (Johnson 2017; Chang 2016; Wang & Yen 2017). Prior internal K entries flag predictive content of VIX/VIX3M ratio:

- `a308a9d5`: VIX/VIX3M ↔ 22d realized vol Pearson 0.51 (p<0.001, n≈2000)
- `cc2e3e65 / 9c09902f` (P35/P36): backwardation lift 3.39x for 5d regime change; incremental over VIX level
- `46c8488e` (P37): backwardation preemptive overlay passes Harvey t=4.31

**Gap**: No clean head-to-head OOS audit comparing rule-based **VIX-level threshold** VT vs rule-based **slope (VIX/VIX3M ratio) threshold** VT, with bootstrap Sharpe CI and matched fee/lag conventions. K1335 fills that gap. If slope rule's OOS Sharpe ≥ level rule with MDD ≤ level rule, candidate for `slope_vt_overlay_v1` strategy lifecycle.

## Data

| Series | Ticker | Range used | Source |
|---|---|---|---|
| SPY adjusted close | `SPY` | 2010-01-01 → 2026-06-13 | yfinance |
| VIX daily close | `^VIX` | 2010-01-01 → 2026-06-13 | yfinance |
| VIX3M daily close | `^VIX3M` | 2010-01-01 → 2026-06-13 | yfinance |
| Cash rate | (set to 0) | — | conservative assumption; impacts all strategies equally |

VIX3M history starts December 2007 so 2010 start has > 2 years buffer.

## Method

**Slope signal**:

```
slope_t = VIX_t / VIX3M_t
```

`slope > 1.0` = backwardation (short end above long end) = stress regime.
`slope < 1.0` = contango = calm regime.

**Strategies** (all daily rebalanced; weight = 1.0 risk-on, 0.0 cash):

| Strategy | Rule | Threshold |
|---|---|---|
| A — Buy & Hold | weight = 1.0 always | — |
| B — VIX level | weight = 1.0 if VIX_{t-1} < th; else 0.0 | th = 20 (IS-tuned grid 18/20/22/25) |
| C1 — Slope 1.0 | weight = 1.0 if slope_{t-1} < 1.0; else 0.0 | 1.0 (textbook backwardation cutoff) |
| C2 — Slope 0.95 | as C1 with th = 0.95 | 0.95 (early-warning sensitivity) |
| C3 — Slope 1.05 | as C1 with th = 1.05 | 1.05 (late-trigger sensitivity) |

**Lookahead policy** (critical — K547 / K1137 lesson):

- Decision at trading day open `t` uses VIX & VIX3M close `t-1` (`shift(1)`).
- Position held over day `t`, P&L = `weight_t * SPY_ret_t` where `SPY_ret_t = SPY_close_t / SPY_close_{t-1} - 1`.
- This avoids the "VIX 16:15 ET vs SPY 16:00 ET" 15-min look-ahead documented in K547.

**Transaction cost**: 10 bps per side applied on absolute weight change (`tc = 0.0010 * |w_t - w_{t-1}|`).

**Splits**:
- IS: 2010-01-01 → 2017-12-31 (≈ 2,015 obs) — used only to tune VIX-level threshold from {18, 20, 22, 25} maximizing IS Sharpe.
- OOS: 2018-01-01 → 2026-06-13 (≈ 2,130 obs) — frozen evaluation.

**Metrics (OOS only for headline)**:
annualized return, annualized vol, Sharpe (rf=0), MDD, Calmar, average turnover (sum |Δw| / years), VaR95, ES95, hit rate.

**Statistical test**: Sharpe-diff between best slope rule and tuned VIX-level rule via stationary bootstrap (Politis-Romano, mean block 5) over OOS daily PnL, 2000 replicates, seed 42. Reports 95% CI and two-sided p-value.

## Success criteria (verdict mapping)

- **PASS**: best slope rule OOS Sharpe ≥ VIX-level Sharpe **and** MDD no worse than 5% absolute (i.e. `MDD_slope ≥ MDD_level - 0.05`) **and** bootstrap p < 0.10.
- **CONDITIONAL_PASS**: slope ≥ level on Sharpe but tied/worse on MDD, or vice versa.
- **NULL**: indistinguishable (CI straddles 0 and metric gaps < 0.1 Sharpe).
- **FAIL**: slope rule strictly worse on both Sharpe and MDD.

## Anti-bias checks

1. Identical lag (`shift(1)`) for both signals.
2. Identical TC, identical cash rate (0), identical weight cap (1.0).
3. Slope thresholds **not** tuned on OOS — three fixed values from literature (0.95 / 1.00 / 1.05).
4. VIX-level threshold tuned only on IS; OOS uses frozen value.
5. Bootstrap seed fixed (42) and recorded.

## Outputs

- `K1335.py` — full reproducible script
- `K1335_results.json` — schema in task brief
- `K1335_fig_equity.png` — cumulative equity curves (5 strategies, OOS log scale)
- `K1335_fig_slope_dist.png` — slope distribution histogram + IS/OOS thresholds
- `K1335_fig_drawdown.png` — underwater curves OOS
- `K1335_fig_regime_returns.png` — daily SPY return conditional on slope/level bucket

## Reproducibility

```
cd .claude/worktrees/k1335
uv run python experiments/K1335/K1335.py
```

Caches yfinance pulls to `experiments/K1335/_cache.parquet` on first run.

## References (prior internal)

- K547 / K547b — VIX timing 15-min lookahead
- K1137 — rolling VIX regime off-by-one
- `a308a9d5` — VIX/VIX3M predictive content
- `cc2e3e65` — backwardation regime-change lift
- `5fe7f259` — TS-enhanced Hybrid VT null (different framing: continuous overlay vs binary rule)
- `4effdd09` — backwardation 8.6% time

External: Johnson (2017) JFE; Chang et al. (2016) JBF; Wang & Yen (2017) IRFA.

## Monetization angle

If PASS, candidate strategy `slope_vt_overlay_v1` enters strategy_lifecycle pipeline (per `docs/strategy-registry.md` gate). Differentiated from existing VT lineup which is uniformly VIX-level based. Reader-facing article ("backwardation as risk-off bell") goes to feed under daily_article cluster.
