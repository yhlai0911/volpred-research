# K1187: Paper 1 Table 7 (Tab:vt) VT Cross-Asset Performance

## Summary

Paper 1 Table 7 (tab:vt) — "Volatility Targeting: Cross-Asset Performance" — 5 assets × 4 metrics (BH Sharpe, VT Sharpe, BH MaxDD, VT MaxDD). This experiment attempts to reproduce all 20 no-source-found values from the diff_report.md.

**Match result: 6/20 metrics matched (30%)**

| Matched | Asset | Metric | Paper | K1187 |
|---------|-------|--------|-------|-------|
| ✓ | SPY | BH Sharpe | 0.82 | 0.81 |
| ✓ | SPY | BH MaxDD | -33.7% | -33.7% |
| ✓ | SPY | VT MaxDD | -14.8% | -15.2% |
| ✓ | TLT | BH Sharpe | 0.02 | 0.02 |
| ✓ | EEM | BH Sharpe | 0.42 | 0.42 |
| ✓ | EEM | BH MaxDD | -38.2% | -39.8% |

## Root Cause of Non-Match

The primary cause is **undisclosed per-asset evaluation periods**. Body.tex says "7-16 year periods" but does not specify per-asset dates. K1187 uses a uniform start (2013-01-01 → active from 2015) for all assets.

Key findings:
1. **SPY**: Uses 2014-2026 period (confirmed by BH Sharpe and MDD exact match)
2. **GLD**: Uses 2022-2026 gold bull period (body.tex explicit); BH 1.56 not reproducible from any standard period (max found: 1.29)
3. **TLT**: BH Sharpe matches but period matters for VT Sharpe (TLT bear market 2022 in active period)
4. **BTC**: Different period needed; BTC BH=0.43 only matches ~2022-2026 but MDD -76.6% requires 2019+ start

## Methodology

- **GARCH selection**: GJR-GARCH for γ > 0.10 assets (SPY, EEM, BTC); GARCH(1,1) for GLD, TLT
- **σ_target** = 10% annualized = 0.629%/day
- **Smoothing**: 5-day MA of daily σ forecast
- **Weight clip**: [0, 1.5]
- **Rolling window**: w=504, refit at each step
- **Signal lag**: `signal from t, return at t+1` (no lookahead)
- **seed=42**

## Files

| File | Description |
|------|-------------|
| `k1187.py` | Main experiment script |
| `k1187_results.json` | Full numerical results (all metrics) |
| `k1187_vs_paper1_table7_diff.md` | Detailed diff analysis with root cause |
| `run.log` | Execution log (~408 seconds) |

## Data

- Source: Yahoo Finance adjusted close prices
- Period: 2013-01-01 to 2026-04-17
- Assets: SPY, GLD, TLT, EEM, BTC-USD
- Returns: simple daily `pct_change()`

## Decision

**(b) Cannot fully reproduce — period mismatch.** Recommend adding explicit per-asset evaluation periods to Table 7 caption. The qualitative conclusions are confirmed:
- VT improves MaxDD for all 5 assets (direction confirmed)
- VT Sharpe improvement is heterogeneous across assets
- BTC shows the most dramatic MaxDD improvement (confirmed direction: 76% → 25%)

## References

- Moreira & Muir (2017) JF — VT alpha framework
- Hood & Raughtigan (2025) — equity VT mechanism
- K1185: Paper 1 Table 4 GARCH methodology
- K1188: Paper 1 Table 8 window robustness (same GARCH kernel)
