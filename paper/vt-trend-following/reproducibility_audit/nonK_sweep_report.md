# Paper 3 (vt-trend-following) — Non-K Forensic Sweep Report

**Date**: 2026-04-17
**Agent**: Non-K Forensic Sweep (worktree agent-a30d366f)
**Task**: Map non-K experiment folders to Paper 3 STILL_NO_SOURCE list (8 numbers)

---

## Non-K Folders Inspected (Paper 3 Assigned)

| Folder | Has Real Data? | Content Summary |
|--------|---------------|-----------------|
| `vt_tsmom_cross_asset` | NO — draft stub | Status=draft, metrics={}, notes=[]. Planning stub only. |
| `rebalance_freq_hybrid_vt` | YES — real data | Rebalancing frequency test (daily/weekly/monthly) for SPY Hybrid VT, OOS 2013–2026 (3079 days). Sharpe: daily=1.064, weekly=0.367, monthly=0.255. |
| `multi_asset_hybrid_vt` | YES — real data | Multi-asset VT (SPY/GLD/TLT), OOS 2014–2026 (3067 days). Multi-Asset Sharpe=0.404, SPY-only Sharpe=1.002. |
| `multi_asset_hybrid_vt_v2` | YES — real data | Same as above with scaled variant. Multi-Asset scaled Sharpe=0.661. SPY-only Sharpe=1.002. |
| `momentum_overlay_cross_asset_validation` | YES — real data | TSMOM/momentum overlay cross-asset validation (QQQ/EEM/GLD/0050.TW), OOS 2016–2025. Verdict: "NO CROSS-ASSET ROBUSTNESS: Momentum Overlay fails Harvey threshold for all tested assets." 0/36 configs pass Harvey t>3.3. |

---

## Paper 3 STILL_NO_SOURCE Analysis

From `diff_report.md`, Paper 3 has **8 cannot-verify** numbers:

1. **Table 5 core numbers** — r=−0.770 (VIX sensitivity vs ΔSharpe), t=15.70, ρ=0.830, average ΔMDDpp=28.7 pp (13-market international panel)
2. **Sector analysis** — r=0.163 (gamma vs ΔSharpe cross-sector), gamma range [0.077, 0.160]
3. **Sub-period stability** — COVID Sharpe 1.295 vs 1.254
4. **Bootstrap CI for MDD retention** — paper claims [86, 97] for SPY (K898 gives different CI [95, 172])
5. **Table 5 VIX sensitivity column** — EFA=−0.653, EWJ=−0.575, etc.

### Cross-Match: Non-K Folders vs No-Source Numbers

#### `momentum_overlay_cross_asset_validation` → Paper 3 Table 5?

Paper 3 Table 5 requires 13-market analysis with cross-sectional correlation r=−0.770 between VIX sensitivity and ΔMDD. The `momentum_overlay_cross_asset_validation` experiment tests 4 assets (QQQ/EEM/GLD/0050.TW) for Harvey threshold.

- Paper 3 Table 5 assets: EFA, EWJ, EWG, EWU, EWA, EWC, VGK, EEM, FXI, EWZ, INDA, EWT, MCHI (13 international)
- `momentum_overlay` assets: QQQ, EEM, GLD, 0050.TW (4 assets, different set)
- Cross-sectional VIX sensitivity r not computed in `momentum_overlay`

**Verdict: UNRELATED** — different asset universe, different metric, different methodology.

#### `vt_tsmom_cross_asset` → Paper 3 hedging analysis?

Planning stub only. **NONK_UNDOCUMENTED** (stub not executed).

#### `rebalance_freq_hybrid_vt` → Paper 3 daily vs monthly hedging?

Contains daily/weekly/monthly rebalancing comparison for SPY Hybrid VT. However Paper 3's Table 3 hedging analysis uses a TSMOM hedge construction (rolling 252-day OLS), not rebalancing frequency. The rebalancing frequency issue (Paper 3 D1 root cause) is partially addressed conceptually by this folder, but the numbers don't directly match Paper 3's reported hedged VT Sharpe (0.737 reported vs K898 0.848).

**Verdict: UNRELATED** — tests different parameter (rebalancing frequency) not the TSMOM hedge construction mismatch.

#### `multi_asset_hybrid_vt`/`v2` → Paper 3 international extension?

Multi-asset covers SPY/GLD/TLT, not the 13-market international set of Paper 3 Table 5. SPY-only Sharpe=1.002 ≈ close to paper's SPY VT Sharpe range but not Table 5.

**Verdict: UNRELATED** — SPY/GLD/TLT only, not international markets.

---

## K1045-Pattern Check

Note from task brief: Paper 3 had "5 STILL_NO_SOURCE (sector 11 SPDR, COVID sub-period, Table 6 bootstrap, split-sample)" before K1192. Let me verify:

- **Sector analysis (r=0.163)**: No non-K folder covers sector-level gamma analysis (11 SPDR sector ETFs). `vt_tsmom_cross_asset` stub was presumably created for this.
- **COVID sub-period**: `rebalance_freq_hybrid_vt` covers 2013–2026 but doesn't report COVID-specific sub-period Sharpe values.
- **Bootstrap CI [86,97]**: `momentum_overlay` has bootstrap_t values but no MDD retention CI for Paper 3's specific test.

---

## Summary

| Category | Count |
|----------|-------|
| Non-K folders inspected (Paper 3 assigned) | 5 |
| Folders with real data | 4 |
| Folders as planning/draft stubs | 1 (`vt_tsmom_cross_asset`) |
| Matches found for no-source numbers | **0** |
| STILL_NO_SOURCE after sweep | **8** (unchanged) |

**Verdict**: 4 of 5 Paper-3-assigned non-K folders have real data, but none of them address Paper 3's specific missing analysis (13-market international panel, sector gamma analysis, sub-period bootstrap). All 4 active folders test different questions (rebalancing frequency, multi-asset composition, 4-asset cross-validation). `vt_tsmom_cross_asset` is a stub not yet executed.

**Key insight**: `momentum_overlay_cross_asset_validation` delivers a DECISIVE NULL for Paper 3's momentum overlay claim across 4 assets (0/36 Harvey pass). This is arguably relevant to Paper 3's Section 4 (TSMOM contribution) but doesn't resolve the missing Table 5 numbers.

---

## Action Recommendations

1. Run a proper 13-market international VT experiment matching Paper 3 Table 5's exact asset set (EFA/EWJ/EWG/EWU/EWA/EWC/VGK/EEM/FXI/EWZ/INDA/EWT/MCHI, Jan 2007–Mar 2026) — this is the BLOCKER.
2. Execute `vt_tsmom_cross_asset` for sector analysis (11 SPDR sector ETFs).
3. `momentum_overlay_cross_asset_validation` null result (t=0.93 avg) may support Paper 3's claim that TSMOM contribution is minimal across assets — cite as supporting evidence.
