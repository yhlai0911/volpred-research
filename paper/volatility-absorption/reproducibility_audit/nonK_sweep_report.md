# Paper 8 (volatility-absorption) — Non-K Forensic Sweep Report

**Date**: 2026-04-17
**Agent**: Non-K Forensic Sweep (worktree agent-a30d366f)
**Task**: Map non-K experiment folders to Paper 8 no-source items

---

## Paper 8 Audit Status

Paper 8 (volatility-absorption: "The Volatility Absorption Hypothesis") is in R1 review with 5 SEVERE issues. No `reproducibility_audit/diff_report.md` exists for Paper 8 — this audit directory was just created by the non-K sweep. Paper 8 has not been through the systematic reproducibility audit process yet.

---

## Non-K Folders Inspected (Paper 8 Assigned per Task Brief)

| Folder | Has Real Data? | Content Summary |
|--------|---------------|-----------------|
| `vt_crowding_simulation` | NO — planning stub | Status=planning, metrics={}, data_sources=[]. Created 2026-04-16. Note: also listed under Paper 5. |
| `btc_liquidation_abm` | NO — planning stub | Status=planning, metrics={}, data_sources=[]. Created 2026-04-16. |

---

## Additional Non-K Folders with Potential Paper 8 Relevance

Paper 8 is about "Volatility Absorption Hypothesis" — likely covering topics of volatility regime dynamics, crowding effects, or VT feedback mechanisms.

| Folder | Content | Paper 8 Relevance |
|--------|---------|------------------|
| `emd_garch_vol` | EMD (Empirical Mode Decomposition) GARCH vol for SPY/GLD/TLT. Keys: n_oos, qlike, dm_test. Has real results. | AMBIGUOUS — tests novel signal decomposition, could be relevant to "absorption" mechanism |
| `entropy_vol_regime` | Draft stub | Not executable yet |
| `regime_survival_analysis` | Draft stub | Not executable yet |
| `transfer_entropy_vix` | Draft stub | Not executable yet |
| `order_flow_vol` | Draft stub | Not executable yet |
| `dynamic_leadlag_network` | Draft stub | Not executable yet |
| `dynamic_leadlag_network_robustness` | Draft stub | Not executable yet |
| `cross_asset_info_topology` | Draft stub | Not executable yet |
| `hawkes_vol_jump` | Draft stub | Not executable yet |
| `hurst_fingerprint` | Draft stub | Not executable yet |
| `rough_vol_pilot` | YES — real data (SPY Hurst estimates). H=0.49 (variogram), roughness_test: p-value from H test. | AMBIGUOUS — Hurst exponent relevant to "absorption" (rough vol = long-memory dynamics) |

---

## Assessment

Since Paper 8 has no `diff_report.md`, we cannot perform a cross-match with specific no-source numbers. The paper is in active revision (R1, 5 SEVERE issues).

The two designated non-K folders (`vt_crowding_simulation`, `btc_liquidation_abm`) are empty stubs. This is concerning if they were intended to provide core paper results.

**Key concern**: The paper's title "Volatility Absorption Hypothesis" suggests a novel theoretical framework. If the core empirical evidence for this hypothesis is missing from experiment JSONs, the non-K sweep cannot rescue it — a full reproducibility audit of Paper 8 is needed first.

---

## Summary

| Category | Count |
|----------|-------|
| Non-K folders inspected | 2 directly + ~10 supplemental |
| Folders with real data | 2 (emd_garch_vol, rough_vol_pilot — supplemental) |
| Folders as planning stubs | 2 directly + 8 supplemental |
| Matches found | **CANNOT ASSESS** (no diff_report.md for Paper 8) |

**Verdict**: Paper 8 needs a full `diff_report.md` before non-K sweep can be meaningful. Both designated non-K folders are empty stubs. Several potentially relevant non-K experiments (emd_garch_vol, rough_vol_pilot) exist but without Paper 8's specific no-source list, match quality cannot be determined.

---

## Action Recommendations

1. **FIRST**: Run Paper 8 through the standard reproducibility audit to generate `diff_report.md` with specific no-source list.
2. Execute `vt_crowding_simulation` and `btc_liquidation_abm` if they were intended to support Paper 8.
3. Check `emd_garch_vol` results against Paper 8's specific claims about volatility decomposition.
4. Run Paper 8 through the K1045-pattern scan (search for undocumented K experiments backing Paper 8 numbers).
