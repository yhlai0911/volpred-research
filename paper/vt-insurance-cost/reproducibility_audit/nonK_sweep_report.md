# Paper 4 (vt-insurance-cost) — Non-K Forensic Sweep Report

**Date**: 2026-04-17
**Agent**: Non-K Forensic Sweep (worktree agent-a30d366f)
**Task**: Map non-K experiment folders to Paper 4 unverifiable items (2 numbers)

---

## Paper 4 Audit Status

Paper 4 (vt-insurance-cost) is rated **submission-ready (96% coverage, R3 SEVERE=0)**.

From `diff_report.md`, only **2 unverifiable items** remain:
- UV-1: Footnote 2012–2024 sub-period correlation ρ = 0.04
- UV-2: Footnote 2012–2024 rebalancing premium = 48 bps

No "STILL_NO_SOURCE" items in the original Paper 4 audit sense — these are footnote-level sensitivity checks.

---

## Non-K Folders Inspected (No Dedicated Paper 4 Folders)

Paper 4 (vt-insurance-cost) had no dedicated non-K experiment folders in the task brief mapping. The following general non-K folders were inspected for any potential Paper 4 relevance:

| Folder | Content | Paper 4 Relevance |
|--------|---------|------------------|
| `transaction_cost_analysis` | SPY Hybrid VT breakeven analysis, 2013–2026. Breakeven cost at various tc levels. | AMBIGUOUS — overlaps Paper 4 direct cost decomposition topic but tests breakeven bps (not insurance premium decomposition) |
| `var_position_sizing` | VaR-based position sizing vs 12/VIX, 2013–2026. No-tc and with-tc strategies. | UNRELATED — different question (VaR-based sizing vs vol targeting) |
| `drawdown_duration_analysis` | SPY drawdown duration metrics for Hybrid VT vs Buy&Hold. | UNRELATED — MDD metrics, not insurance premium |
| `vix_death_zone_enhanced` | VIX zone-based enhancements, OOS 2018–2026. | UNRELATED — not related to cost decomposition |

### `transaction_cost_analysis` Detailed Check

Keys: `['experiment', 'date', 'config', 'buy_and_hold', 'breakeven_bps', 'results_by_cost']`
- `breakeven_bps`: computed for SPY Hybrid VT
- Does NOT contain ρ (correlation) or 48 bps rebalancing premium calculation

**Verdict: UNRELATED** to UV-1/UV-2 (footnote 2012–2024 sub-period correlation and rebalancing premium).

---

## UV-1/UV-2 Analysis

Both footnote items require a **sub-period analysis of K846** restricted to 2012–2024:
- K846 covers 2006–2024 full sample
- K846 `corr_spy_gld` = 0.057 (full period), but footnote claims ρ = 0.04 for 2012–2024 sub-period
- K846 rebalancing premium = 53.67 bps (empirical, full period), but footnote claims 48 bps for 2012–2024

No non-K folder computes K846 restricted to 2012–2024. The footnote values are either: (a) hand-computed from K846 raw data, or (b) from an unreported sensitivity run.

---

## Summary

| Category | Count |
|----------|-------|
| Non-K folders inspected (potential Paper 4) | 4 |
| Folders with real data | 4 |
| Matches found for unverifiable items | **0** |
| UV items remaining after sweep | **2** (unchanged, both footnote-level) |

**Verdict**: Paper 4 is near-submission-ready. The 2 unverifiable footnote items (UV-1/UV-2) are not resolved by any non-K folder. These are low-priority footnote sensitivity checks that require a minor extension of K846 to 2012–2024 sub-period.

---

## Action Recommendations

1. **LOW PRIORITY**: Extend K846 analysis to add 2012–2024 sub-period breakdowns. Add `corr_spy_gld_2012_2024` and `rebalancing_premium_2012_2024_bps` to K846 results JSON.
2. No non-K sweep quick wins for Paper 4.
