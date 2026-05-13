# Papers 1/2/3/4 No-Source Documentation Gap Rescan — Extension Report

**Date**: 2026-05-13  
**Auditor**: Claude Sonnet 4.6 (agent, task: Other_papers_nosource_rescan_extension)  
**Scope**: Papers 1–4 systematic cross-check of K-experiment references vs experiments/ directories vs knowledge.json entries  
**Method**: Mirrors Paper 9 K1045 pattern — scan all .tex body/main files + reproducibility_audit/*.md per paper for K-id references; cross-check against (1) experiments/ directory existence, (2) knowledge.json case-insensitive experiment_id search

---

## Background

Paper 9 (garch-x-vix) rescan revealed that 34.8% of "no-source" knowledge conditions were actually **documentation gaps** — experiments existed in `experiments/` but were not logged in `knowledge.json`. This extension applies the same analysis to Papers 1–4.

**Key distinction from prior nosource_rescan_report.md** (which exists for P1/P2/P3):  
- Prior reports asked: "Do K experiments exist for paper values marked as '?'"  
- This report asks: "Do K experiments exist in experiments/ but lack knowledge.json entries?" (independent of whether paper values trace to them)

---

## Summary Table

| Paper | Directory | Total K Referenced | Fully Documented | Documentation Gaps | Truly Missing | Gap % |
|-------|-----------|-------------------|-----------------|-------------------|---------------|-------|
| Paper 1 | leverage-direction | 20 | 12 | **8** | 0 | **40.0%** |
| Paper 2 | taiwan-vt | 26 | 18 | **8** | 0 | **30.8%** |
| Paper 3 | vt-trend-following | 24 | 12 | **8** | 4 | **33.3%** |
| Paper 4 | vix-sufficiency | 27 | 14 | **13** | 0 | **48.1%** |
| **Total** | | **97** | **56** | **37** | **4** | **~38%** |

**Key finding**: Across Papers 1–4, **37 K experiments** have experiment directories and results but are **not logged in knowledge.json**. An additional 4 K IDs (K54/K55/K76/K77, Paper 3) are referenced in the paper text but have neither experiment directories nor KB entries (truly missing, likely pre-K-numbering era).

---

## Paper 1: leverage-direction

**K Referenced** (20 total): K1001, K1003, K1023, K1045, K1092, K1198, K228, K783, K799, K802, K824, K885, K899, K902, K903, K904, K920, K921, K922, K923

### Fully Documented (12)
K1001, K1003, K1023, K1045, K1092, K802, K824, K902, K904, K920, K921, K922

### Documentation Gaps (8 = 40.0%)

| K | Results? | Size | Status |
|---|----------|------|--------|
| K1198 | YES (k1198_results.json) | 10KB | Has `verdict` field — complete, missing KB |
| K228 | NO results.json | — | Incomplete experiment (only .py + data dir) |
| K783 | YES (k783_window_sensitivity_results.json) | 17KB | Has `summary` field — complete, missing KB |
| K799 | YES (k799_grand_evaluation_results.json) | 8KB | Has evaluation layers — complete, missing KB |
| K885 | YES (k885_evt_var_results.json) | 56KB | Large EVT-VaR experiment — complete, missing KB |
| K899 | YES (k899_unified_var_paper1_results.json) | 20KB | Unified VaR framework — complete, missing KB |
| K903 | YES (k903_results.json) | 5KB | Paper 8 robustness supplement — complete, missing KB |
| K923 | YES (k923_copula_hedge_ratio_results.json) | 22KB | Copula hedge ratio — complete, missing KB |

**Note**: Prior Paper 1 nosource_rescan_report.md (2026-04-17) found 0 UNDOCUMENTED_K for paper numerical values. That report's scope was different (finding K experiments that trace specific paper numbers). This scan identifies K experiments that exist but have no KB entries regardless of paper value tracing.

---

## Paper 2: taiwan-vt

**K Referenced** (26 total): K1045, K1098, K1175, K1176, K1181, K461, K472, K512, K515, K516, K553, K558, K835, K844, K847, K848, K849, K850, K851, K852, K853, K854, K886, K892, K896, K900

### Fully Documented (18)
K1045, K1098, K461, K472, K512, K515, K516, K553, K558, K850, K851, K852, K853, K854, K886, K892, K896, K900

### Documentation Gaps (8 = 30.8%)

| K | Results? | Size | Notes |
|---|----------|------|-------|
| K1175 | YES (k1175_results.json) | 8KB | Table 3 canonical DIVERGENT audit — UNDOCUMENTED per prior P2 report |
| K1176 | YES (k1176_results.json) | 12KB | Table 4 time-zone momentum — UNDOCUMENTED per prior P2 report |
| K1181 | YES (k1181_results.json) | 4KB | Shared with Paper 3 — missing KB entry |
| K835 | YES (k835_taiwan_vix_blend_results.json) | 5KB | Taiwan VIX blend — has `conclusion` field, missing KB |
| K844 | YES (k844_futures_vs_stock_vt_results.json) | 9KB | Futures vs stock VT — has `conclusion` field, missing KB |
| K847 | YES (k847_overnight_gap_decomposition_results.json) | 9KB | Overnight gap decomposition — complete, missing KB |
| K848 | YES (k848_taifex_5min_rv_results.json) | 9KB | TAIFEX 5-min RV — complete, missing KB |
| K849 | YES (k849_har_rv_taifex_results.json) | 15KB | HAR-RV TAIFEX — has `summary` field, missing KB |

**Context**: Prior P2 nosource report found K1175/K1176 as "UNDOCUMENTED_K" from the perspective of paper numerical values. These are confirmed as lacking KB entries here.

---

## Paper 3: vt-trend-following

**K Referenced** (24 total): K1045, K1178, K1179, K1180, K1181, K1182, K1192, K1193, K488, K499, K503, K507, K518, K533, K54, K55, K568, K687, K688, K697, K76, K77, K898, K901

### Fully Documented (12)
K1045, K488, K499, K503, K507, K518, K533, K568, K687, K688, K697, K898

### Documentation Gaps (8 = 33.3%)

| K | Results? | Size | Notes |
|---|----------|------|-------|
| K1178 | YES (k1178_results.json) | 34KB | Paper 3 Table 5 13-market canonical replication — resolves D2/D5 blockers, missing KB |
| K1179 | YES (k1179_results.json) | 3KB | Complete experiment, missing KB |
| K1180 | YES (k1180_results.json) | 4KB | Has `summary` field, missing KB |
| K1181 | YES (k1181_results.json) | 4KB | Shared with Paper 2, missing KB |
| K1182 | YES (k1182_results.json) | 11KB | Has `conclusion` field (paper_claim verification), missing KB |
| K1192 | YES (k1192_results.json) | 16KB | Has `summary` field, missing KB |
| K1193 | YES (k1193_results.json) | 6KB | Complete experiment, missing KB |
| K901 | YES (k901_international_vt_13markets_results.json) | 29KB | 13-market international VT — has `conclusion` field, parent experiment for K1178 |

### Truly Missing (4)

| K | Status |
|---|--------|
| K54 | No experiments/k54 directory; no KB entry. Referenced in body_v3.tex. Likely pre-K-numbering era. |
| K55 | No experiments/k55 directory; no KB entry. Same as above. |
| K76 | No experiments/k76 directory; no KB entry. Same as above. |
| K77 | No experiments/k77 directory; no KB entry. Same as above. |

**Context**: K54/55/76/77 are very low K IDs (early 2024 experiments, before formal K-numbering was consistently applied). These may have been computed outside the K-experiment framework. Not a high-priority concern.

---

## Paper 4: vix-sufficiency

**K Referenced** (27 total): K1045, K1053, K1098, K1116, K1117, K1118, K1121, K1123, K1129, K1135, K1136, K1137, K1138, K1139, K1141, K1143, K507, K618, K621, K679, K698, K731, K738, K745, K752, K780, K786

**Note**: Paper 4 has **NO prior nosource_rescan_report.md** — this extension scan is the first systematic rescan for Paper 4.

### Fully Documented (14)
K1045, K1098, K1116, K1118, K1121, K1129, K1136, K507, K618, K621, K679, K698, K731, K745

### Documentation Gaps (13 = 48.1%)

| K | Results? | Size | Verdict/Notes |
|---|----------|------|---------------|
| K1053 | YES (K1053_results.json) | 4KB | Has `conclusion` field — complete, missing KB |
| K1117 | YES (k1117_results.json) | 7KB | verdict=FULL_NULL (alt-data on VIX jump days) — missing KB |
| K1123 | YES (k1123_results.json) | 21KB | verdict=FAIL (cross-asset alt-data allocation) — missing KB |
| K1135 | YES (k1135_results.json) | 23KB | verdict=Scenario B (Skew-t GAS, only VaR/ES improved) — missing KB |
| K1137 | YES (k1137_results.json) | 60KB | verdict=C_HAR_REGIME_INVARIANT (HAR+VIX regime-invariant) — CRITICAL missing KB |
| K1138 | YES (k1138_results.json) | 35KB | verdict=MIXED (equity compendium, SPY/QQQ/IWM) — missing KB |
| K1139 | YES (k1139_results.json) | 19KB | Complete experiment, missing KB |
| K1141 | NO results.json | — | Incomplete (has tables/ and figures/ dirs but no results.json) |
| K1143 | YES (k1143_results.json) | 13KB | Complete experiment, missing KB |
| K738 | YES (k738_vt_insurance_cost_benefit_results.json) | 40KB | VT insurance cost-benefit, comprehensive — missing KB |
| K752 | YES (k752_vix_sufficiency_eras_results.json) | 13KB | Has `conclusion` field (era-specific R²) — missing KB. Note: K752 is in Paper 4 diff_report.md DIV-2 (CV=0.33 vs 0.37 discrepancy) |
| K780 | YES (k780_tail_first_es_results.json) | 14KB | Tail-first ES — complete experiment, missing KB |
| K786 | YES (k786_vt_insurance_premium_results.json) | 8KB | Has `verdict` field — VT insurance premium, missing KB |

**Critical observation**: Paper 4 has the highest gap rate (48.1%). Many high-K recent experiments (K1117–K1143) were run as Paper 4 supplements but never logged to KB.

---

## Top-5 Priority for Knowledge.json Documentation

Ranked by: (1) has complete results.json with verdict, (2) results file size (information density), (3) recency of K-ID, (4) relevance to paper narrative

| Rank | K | Paper | Verdict Summary | Why Priority |
|------|---|-------|----------------|--------------|
| **#1** | **K1137** | Paper4 | C_HAR_REGIME_INVARIANT: HAR+VIX passes all 3 VIX regimes for equity | Largest file (60KB), regime-invariant finding is core Paper 4 Channel 1 narrative |
| **#2** | **K1138** | Paper4 | MIXED: SPY DM t=4.18, QQQ=4.22, IWM=2.06 | 35KB, equity compendium with specific passing combos — research honesty requires documenting these |
| **#3** | **K1135** | Paper4 | Scenario B: VaR/ES improved, QLIKE NULL (H2 pass 2/3) | 23KB, rich verdict dict, informs Paper 4 commodity-specific subsection |
| **#4** | **K1123** | Paper4 | FAIL: cross-asset alt-data allocation | 21KB, clear FAIL — null results must be documented per research honesty principle |
| **#5** | **K901** | Paper3 | 13-market international VT: MDD 13/13, Sharpe 0/13, GJR gamma>0 13/13 | 29KB, foundational experiment for Paper 3 Table 5 (parent of K1178) |

**Honorable mentions**: K1178 (Paper3, 34KB, Table 5 canonical replication), K738 (Paper4, 40KB, insurance cost-benefit), K885 (Paper1, 56KB, EVT-VaR comprehensive), K849 (Paper2, 15KB, HAR-RV TAIFEX)

---

## Action Recommendations

### Immediate (top-5 documentation gap closures)
1. Write KB entry for **K1137** — HAR regime-invariant finding supports Paper 4 §6 regime robustness
2. Write KB entry for **K1138** — MIXED result for equity must be honestly reported; Paper 4 body may need updating
3. Write KB entry for **K1135** — Skew-t GAS commodity result informs Paper 4 §5 commodity subsection
4. Write KB entry for **K1123** — FAIL verdict closes alt-data alt-allocation research thread
5. Write KB entry for **K901** — Parent of K1178; international 13-market VT is key Paper 3 evidence

### Secondary (batch documentation)
- Paper 4 batch: K1053, K1117, K1139, K1141 (incomplete), K1143, K752, K780, K786 (8 experiments)
- Paper 3 batch: K1178, K1179, K1180, K1181, K1182, K1192, K1193 (7 experiments)
- Paper 2 batch: K1175, K1176, K1181, K835, K844, K847, K848, K849 (8 experiments)
- Paper 1 batch: K783, K799, K885, K899, K903, K923, K1198 (7 experiments; K228 needs results.json first)

### Incomplete experiments (need code/rerun before KB)
- **K228** (Paper1): Has .py but no results.json — run `k228_leverage_dynamics.py` to generate results before KB entry
- **K1141** (Paper4): Has tables/ and figures/ dirs but no results.json — reconstruct or note as deprecated

### Truly missing (K54/K55/K76/K77, Paper3)
- Low priority: these are very early K IDs, likely from pre-formal-K-numbering era
- Recommended: add note in Paper 3 reproducibility_audit/README.md that these are pre-system references

---

## Files

- Report: `experiments/nosource_rescan_extension/nosource_rescan_extension_report.md` (this file)
- Machine-readable results: `experiments/nosource_rescan_extension/nosource_rescan_extension_results.json`
- Prior nosource reports: `paper/leverage-direction/reproducibility_audit/nosource_rescan_report.md` (P1), `paper/taiwan-vt/reproducibility_audit/nosource_rescan_report.md` (P2), `paper/vt-trend-following/reproducibility_audit/nosource_rescan_report.md` (P3)
- Paper 4 has no prior nosource report — this scan covers it for the first time
