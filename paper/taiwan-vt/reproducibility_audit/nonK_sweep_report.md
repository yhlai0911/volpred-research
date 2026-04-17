# Paper 2 (taiwan-vt) — Non-K Forensic Sweep Report

**Date**: 2026-04-17
**Agent**: Non-K Forensic Sweep (worktree agent-a30d366f)
**Task**: Map non-K experiment folders to Paper 2 STILL_NO_SOURCE list (42 numbers)

---

## Non-K Folders Inspected (Paper 2 Assigned)

| Folder | Has Real Data? | Content Summary |
|--------|---------------|-----------------|
| `taiwan_paper_fixes` | NO — planning stub | Status=planning, metrics={}, data_sources=[]. Created 2026-04-16 as placeholder. Title="taiwan_paper_fixes" only. |

---

## Paper 2 STILL_NO_SOURCE Analysis

From `diff_report.md`, Paper 2 has **42 no-source** numbers (51% of all 82). Key gaps:

1. **Section 5 TZ momentum (Table 4)** — ALL Section 5 numbers: TW Sharpe 1.473, JP 1.306, 6-market t-stats (HK=4.12, AU=4.04, SG=4.03, KR=3.83, TW=3.76, JP=3.69), TW+JP 50/50 Sharpe=1.810, Global composite=1.610 (BLOCKER)
2. **Section 5 overnight gap diagnostics** — +10.73bp/-8.91bp conditional means, 87% gap fraction, bootstrap CI [0.65, 2.24]
3. **Section 6 Macro indicators** — import growth r=0.214, OOS improvement 5.6%, DM p=0.043; BCI t=-0.53; leading indicator t=3.74, R²=7.1%
4. **Section 8 Discussion** — TSMC decomposition (Sharpe 1.121, 0.193–0.637 range); VIX+Leading combo DM p=0.0005; sub-period 8.63/VIX Sharpe=0.334; skewed-t parameters (η=5.2, λ=−0.05); currency drag −18%; VIX sufficiency R²+0.003
5. **Cross-market validation** — Europe-to-US null result r=−0.07, India/Indonesia fails
6. **VIXTWN stats** — if any are STILL_NO_SOURCE (per task brief "VIXTWN stats, Granger, TSMC, skew-t")

### Cross-Match: `taiwan_paper_fixes` vs No-Source Numbers

`taiwan_paper_fixes_results.json` is a planning stub (status=planning, metrics={}, data_sources=[]). It contains **no actual computed results**. This folder was created 2026-04-16 as a placeholder and has not been executed.

| No-Source Item | `taiwan_paper_fixes` Match | Verdict |
|---------------|---------------------------|---------|
| TZ momentum Table 4 (all 6-market values) | No data | **NONK_UNDOCUMENTED** — stub has no data |
| Overnight gap +10.73bp/-8.91bp | No data | **NONK_UNDOCUMENTED** — stub has no data |
| Macro Section 6 statistics | No data | **NONK_UNDOCUMENTED** — stub has no data |
| TSMC decomposition | No data | **NONK_UNDOCUMENTED** — stub has no data |
| Currency drag −18% | No data | **NONK_UNDOCUMENTED** — stub has no data |

---

## Additional Non-K Folders with Potential Taiwan Relevance

| Folder | Content | Verdict |
|--------|---------|---------|
| `momentum_overlay_cross_asset_validation` | Tests momentum overlay for QQQ, EEM, GLD, 0050.TW (2016–2025). Sharpe diffs, bootstrap t-stats. 0050.TW: overlay_sharpe=0.463 vs baseline 0.349, bootstrap_t=1.96. Harvey pass=False. | **PARTIAL AMBIGUOUS** — Has 0050.TW data but does NOT cover Paper 2's TZ strategy or Section 5/6 numbers. The 0050.TW Sharpe 0.349 is not a Paper 2 value (Paper 2 claims VT Sharpe ~0.729+ for TWII/0050). |
| `vt_tsmom_cross_asset` | Planning stub — no data | UNRELATED |
| `multi_asset_hybrid_vt` / `multi_asset_hybrid_vt_v2` | SPY+GLD+TLT multi-asset VT (2014–2026). No Taiwan assets. | UNRELATED |
| `rebalance_freq_hybrid_vt` | SPY-only rebalancing frequency test (2013–2026). No Taiwan. | UNRELATED |

---

## Overnight Gap Note

The overnight gap diagnostic numbers (+10.73bp/-8.91bp, bootstrap CI [0.65, 2.24]) may be sourced from **K847** (paper's experiments list), which was identified as covering "stock gap vs SPY pearson = 0.399" in the diff report. However K847 uses 2017–2026 period and measures stock gap. The +10.73bp conditional mean and CI [0.65, 2.24] are still listed as STILL_NO_SOURCE in the diff report. The non-K sweep finds no alternative source.

---

## Summary

| Category | Count |
|----------|-------|
| Non-K folders inspected (Paper 2 assigned + potential) | 1 directly + 4 supplemental |
| Folders with real data | 1 (momentum_overlay — 0050.TW data only) |
| Folders as planning stubs | 1 (`taiwan_paper_fixes`) + 1 (`vt_tsmom_cross_asset`) |
| Matches found for no-source numbers | **0** |
| STILL_NO_SOURCE after sweep | **42** (unchanged) |

**Verdict**: `taiwan_paper_fixes` is a planning stub with no computed results. No non-K folder resolves any of Paper 2's 42 no-source numbers.

**Critical finding**: Paper 2's biggest gap (Section 5 TZ momentum = the paper's Third contribution) has NO backing experiment anywhere in `experiments/`. The closest relevant data is in K847 (overnight gap) and older unnamed experiments not committed to the repo.

---

## Action Recommendations

1. **URGENT (BLOCKER)**: Run TZ momentum experiment for 6 markets (TW/JP/HK/AU/SG/KR) covering 2012–2025 with c2c and o2o strategies. Commit as a proper K experiment.
2. **Execute `taiwan_paper_fixes`**: This placeholder exists specifically to fill Paper 2 gaps — it needs to be populated with actual scripts and run.
3. `momentum_overlay_cross_asset_validation` shows 0050.TW fails Harvey threshold (t=1.96 < 3.3) — may be relevant to Paper 2's robustness discussion.
