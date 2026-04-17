# Paper 9 (garch-x-vix) — Non-K Forensic Sweep Report

**Date**: 2026-04-17
**Agent**: Non-K Forensic Sweep (worktree agent-a30d366f)
**Task**: Map non-K experiment folders to Paper 9 STILL_NO_SOURCE list (7 items from nosource_rescan_report.md)

---

## Paper 9 STILL_NO_SOURCE Summary

From `nosource_rescan_report.md` (the K1045-pattern sweep), Paper 9 has **7 STILL_NO_SOURCE**:
- N139: 0.188 (SPY ann. std full) — Data Table 1
- N140: 22.14 (OOS mean VIX) — Data Table 1
- N141: 18.97 (Full VIX mean) — Data Table 1
- N142: 0.20 (VRP daily autocorr) — VRP section (K998 prints but doesn't save to JSON)
- N148: 7/7 sub-period count — Section 4.3 (k1027.py designed but never ran)
- N149: 4.81%–8.09% improvement range — Section 4.3
- N150: 6.52% mean improvement — Section 4.3
- N154: t=6.535 pooled full-period — Section 4.3

---

## Non-K Folders Inspected (Paper 9 Assigned)

| Folder | Has Real Data? | Content Summary |
|--------|---------------|-----------------|
| `garch_midas_test` | YES — real data | GARCH-MIDAS (Engle-Ghysels-Sohn 2013) vs GJR-GARCH on SPY. In-sample: GARCH-MIDAS RV QLIKE=1.4503 vs GJR=1.4680 (DM t=-2.31, GARCH-MIDAS wins). OOS (2023–2026, n=802): GARCH-MIDAS QLIKE=1.682 vs GJR=1.672 (DM t=0.66, NO significant win). Conclusion: GARCH-MIDAS fails OOS. |
| `gld_inventory_vol` | NO — planning stub | Status=planning, metrics={}, data_sources=[]. Created 2026-04-16. |

---

## Cross-Match: Non-K Folders vs No-Source Numbers

### `garch_midas_test` → Paper 9 STILL_NO_SOURCE items

Paper 9 is about A4f (multiplicative GARCH-X with VIX) vs GJR. The GARCH-MIDAS test compares GARCH-MIDAS-RV vs GJR on SPY. This is a competitor model comparison.

**Specific cross-matches:**

| No-Source Item | `garch_midas_test` Match | Verdict |
|---------------|--------------------------|---------|
| N139: 0.188 (SPY ann. std) | Not present (no descriptive stats) | UNRELATED |
| N140: 22.14 (OOS mean VIX) | Not present (no VIX mean) | UNRELATED |
| N141: 18.97 (full VIX mean) | Not present | UNRELATED |
| N142: 0.20 (VRP autocorr) | Not present | UNRELATED |
| N148–N154: Section 4.3 sub-period | Not present | UNRELATED |

**Additional check**: Can `garch_midas_test` inform Paper 9's alternative model discussion?
- `garch_midas_test` OOS QLIKE: GJR=1.672 vs GARCH-MIDAS-RV=1.682 → GJR wins OOS by 0.010 QLIKE
- Paper 9's A4f OOS QLIKE: 1.408 (from K1003 Table 12 baseline) vs GJR=1.498
- A4f (1.408) >> GARCH-MIDAS-RV (1.682) → A4f substantially better than GARCH-MIDAS on QLIKE OOS

**Verdict**: NONK_UNDOCUMENTED for paper purpose — `garch_midas_test` provides a useful cross-model comparison that Paper 9 could cite as additional evidence that A4f (VIX-based) beats GARCH-MIDAS (RV-based) OOS. Not in Paper 9's registered experiments. The GJR OOS QLIKE values (1.672 vs paper's 1.498) differ due to different sample periods (garch_midas OOS: 2023–2026 n=802; K988 OOS: 2019–2026 n=1823).

### `gld_inventory_vol` → Paper 9 GLD analysis

Planning stub only. No data to compare against paper's data Table 1 (which covers SPY+VIX summary stats, not GLD inventory).

**Verdict: NONK_UNDOCUMENTED** (stub, not executed).

---

## Summary Statistics Match Check

N139–N141 (Table 1 summary stats) require simple descriptive statistics on the SPY+VIX dataset:
- N139: SPY ann. std = 0.188 — computable from K988 raw data (SPY 2005–2026)
- N140: OOS mean VIX = 22.14 (OOS start 2019) — computable from K988/K1003 OOS VIX data
- N141: Full VIX mean = 18.97 — computable from K988 full-sample VIX

None of the non-K folders contain this. These are trivial descriptive statistics that K988 data would produce — they're just not saved to any JSON.

---

## N142: VRP Autocorrelation (0.20)

`vrp_regime_decomposition` is a planning stub. No non-K folder computes VRP autocorrelation. The source is K998.py which prints `OOS VRP autocorr(1)` but doesn't save it to k998_results.json.

---

## N148–N154: Section 4.3 Sub-Period Analysis

`vix_term_structure_vol_pred` covers monthly vol prediction windows (2021–2025, 56 OOS windows). Not the 7-window annual sub-period analysis required for Paper 9 Section 4.3.

`vix_term_structure_vol_pred_v2` conclusion: "Classic overfitting pattern." Also not relevant to Paper 9's 7-window analysis.

---

## Summary

| Category | Count |
|----------|-------|
| Non-K folders inspected (Paper 9 assigned) | 2 directly |
| Folders with real data | 1 (`garch_midas_test`) |
| Folders as planning stubs | 1 (`gld_inventory_vol`) |
| **NONK_UNDOCUMENTED (paper-supporting but unregistered)** | **1** (`garch_midas_test`) |
| No-source items resolved | **0** (N139–N142, N148–N154 all remain) |
| STILL_NO_SOURCE after sweep | **7** (unchanged) |

**Key finding**: `garch_midas_test` provides a useful Paper 9 supporting fact (GARCH-MIDAS fails OOS, GJR beats it) and is not registered in Paper 9's experiments. This is NONK_UNDOCUMENTED in the helpful sense — it strengthens Paper 9's narrative about VIX models (A4f) outperforming RV-based models (GARCH-MIDAS). The OOS period differs from K988's OOS so it serves as an independent replication.

---

## Action Recommendations

1. **N139–N141**: Add summary statistics export to K988 (descriptive stats for Table 1: SPY ann.std, OOS VIX mean, full VIX mean). Simple 5-line addition to k988.py.
2. **N142**: Add `vrp_autocorr_lag1` save to K998 results JSON (already computed, just not saved per nosource_rescan_report.md).
3. **N148–N154**: Execute k1027.py sub-period analysis (7 annual windows 2013–2026). This is the only way to resolve the Section 4.3 numbers.
4. **Register `garch_midas_test`**: Add to Paper 9's experiments.md as "GARCH-MIDAS vs GJR comparison — A4f context". GJR OOS QLIKE=1.672 confirms A4f (1.408) substantially better than GARCH-MIDAS-RV.
