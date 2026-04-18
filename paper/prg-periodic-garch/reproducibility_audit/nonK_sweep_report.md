# Paper 6 (prg-periodic-garch) — Non-K Forensic Sweep Report

**Date**: 2026-04-17
**Agent**: Non-K Forensic Sweep (worktree agent-a30d366f)
**Task**: Map non-K experiment folders to Paper 6 STILL_NO_SOURCE items (2 items: DIV-6 TAIFEX DM=-4.07, DIV-7 Spearman ρ=0.726)

---

## Paper 6 STILL_NO_SOURCE Summary

From `diff_report.md`, Paper 6 has 2 STILL items:
- **DIV-6**: TAIFEX DM PRG vs Separate = -4.07 (no source found; K883 gives -3.303)
- **DIV-7**: TAIFEX Spearman ρ = 0.726 (K874d gives 0.537; K883 spearman_fullday not verified)

Additionally:
- **NOTE-1**: TAIFEX MCS "PRG only" at 10% level — unverified (no MCS data in K874d or K883)
- **DIV-8**: TAIFEX DM PRG vs HAR = 2.63 (K884 gives 2.305; source unclear)

---

## Non-K Folders Inspected (Paper 6 Assigned)

| Folder | Has Real Data? | Content Summary |
|--------|---------------|-----------------|
| `realized_garch_pilot` | NO — planning stub | Status=planning, metrics={}, data_sources=[]. Created 2026-04-16. |
| `pairs_trading_garch` | YES — real data | GARCH-Enhanced Pairs Trading (labeled K115 internally). SPY/QQQ, GLD/GDX, XLE/USO, GLD/SLV, TLT/IEF — cointegration tests. None are cointegrated (all p>0.05). Period 2010–2024, OOS 2023–2024. |

---

## Cross-Match: Non-K Folders vs No-Source Numbers

### `pairs_trading_garch` → Paper 6 TAIFEX DM/Spearman?

`pairs_trading_garch` tests cointegration and pairs trading for US market pairs (SPY/QQQ, GLD/GDX, etc.). This is entirely unrelated to:
- TAIFEX periodic GARCH session decomposition
- PRG vs Separate GARCH DM tests
- Spearman ρ between TAIFEX GARCH forecasts and realized volatility

**Verdict: UNRELATED** — tests US equity pairs cointegration, not TAIFEX session-specific vol forecasting.

### `realized_garch_pilot` → Paper 6 TAIFEX analysis?

Planning stub only. Created as a placeholder that likely intended to supplement Paper 6's realized-GARCH baseline. No actual data.

**Verdict: NONK_UNDOCUMENTED** (stub not executed).

---

## Additional Non-K Check for TAIFEX-Related Content

| Folder | Verdict |
|--------|---------|
| `vix_term_structure_vol_pred` | UNRELATED — Tests VIX term structure for US SPY forecasting (OOS 2021–2025). No TAIFEX content. |
| `vix_term_structure_vol_pred_v2` | UNRELATED — Same, v2 robustness. Conclusion: "VIX term structure does NOT add OOS predictive power for monthly vol beyond VIX level alone." |
| `garch_midas_test` | AMBIGUOUS — Tests GARCH-MIDAS (Engle-Ghysels-Sohn 2013) on SPY with RV and industrial production as mixing variable. In-sample DM t=-2.31 (GARCH-MIDAS vs GJR), OOS DM t=0.66 (no win). This is a SPY experiment, not TAIFEX. Not relevant to Paper 6's TAIFEX DM values. |

---

## K-Uppercase Folder Check for Paper 6

`K1033` (A4f Refit Frequency — Paper 9), `K1129` (GAS-t Commodity — Paper 7/vix-sufficiency) — none are Paper 6 TAIFEX experiments.

---

## Summary

| Category | Count |
|----------|-------|
| Non-K folders inspected (Paper 6 assigned + potential) | 2 directly + 3 supplemental |
| Folders with real data | 1 (`pairs_trading_garch`) |
| Folders as planning stubs | 1 (`realized_garch_pilot`) |
| Matches found for no-source numbers | **0** |
| STILL_NO_SOURCE after sweep | **2** (DIV-6 TAIFEX DM=-4.07, DIV-7 Spearman ρ=0.726) |
| Additional unverified | **2** (NOTE-1 MCS, DIV-8 DM vs HAR=2.63) |

**Verdict**: No non-K folder resolves Paper 6's TAIFEX-specific DM and Spearman gaps. The `pairs_trading_garch` folder is unrelated (US pairs, labeled K115 internally). `realized_garch_pilot` is an empty stub.

---

## Action Recommendations

1. **Run K874c or K874e** — check if these experiments (cited in diff_report as possible sources for TAIFEX Separate GARCH comparison) exist and contain DM=-4.07.
2. **Add `spearman_fullday` to K883 JSON** — the Spearman ρ=0.726 may be computed but not saved to K883 results JSON.
3. `realized_garch_pilot` stub should be executed if it was designed to produce the missing TAIFEX values.
4. No non-K quick wins for Paper 6.
