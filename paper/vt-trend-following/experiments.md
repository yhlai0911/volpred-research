# Paper 3: Supporting Experiments Index

**Paper**: Is Volatility Targeting Just Trend Following? Decomposing the Benefits of Volatility Targeting
**Target Journal**: Journal of Portfolio Management / Financial Analysts Journal
**Status**: R1 review — 7 HIGH, needs revision
**Current body**: `body_v3.tex` / `main_v3.tex`
**Last Updated**: 2026-04-18

---

## Canonical Experiments (v3 body references these as authoritative)

| K | Title | Contribution | Path |
|---|-------|--------------|------|
| K55 | VT–TSMOM cross-asset panel (N=22) | Tables 1 & 2 primary numbers (gamma, alpha, TSMOM_orth, cross-sectional r=0.564) | `experiments/vt_tsmom_final_n22.json` (paper folder + storage) |
| K54 / K71 | FF5 + MOM + BAB factor controls | Table 4 M1–M5 alpha/t-stats, AIC, R² | `experiments/ff5_factor_controls.json` (paper folder + storage) |
| K79 | VIX threshold sensitivity + 5-asset MDD | Discussion sensitivity range (TSMOM_t 7.98–10.91); secondary 5-asset MDD retention robustness | `experiments/paper3_fixes.json` (paper folder) |
| K898 | 5-asset dual-mechanism supplement (2005–2026) | Section 3.3 Table 3 dual-mechanism decomposition (daily signal; supersedes v2 numbers for SPY/50-50/DIA/QQQ/IWM); TSMOM contribution back-calc (5.3%) | `experiments/k898_paper3_table3_supplement_results.json` (paper folder) + `experiments/k898/` |
| K1178 | Canonical 13-market Table 5 replication | v3 canonical Table 5 numbers: avg ΔMDD=24.9pp, t=10.25, r=−0.806 (VIX sens vs ΔMDD), ρ=−0.835 | `experiments/k1178/` |
| K1192 | Canonical block-bootstrap MDD retention (Table 6) | v3 canonical bootstrap CIs: SPY [93,182], 50/50 [76,190], DIA [82,154], QQQ [89,210], IWM [87,184]; point estimates 95.6–109.0% | `experiments/k1192/` |
| K1193 | Split-sample robustness (gamma 2007–16 vs TSMOM 2017–26) | v3 canonical r=0.793 (p<0.001), CI [0.589, 0.919], Spearman ρ=0.749 | `experiments/k1193/` |

---

## Supporting Discussion Experiments (cited in Section 4–5)

| K | Title | Contribution | Path |
|---|-------|--------------|------|
| K488 / K503 | 12/VIX formula irreducibility | Discussion claim: 12/VIX as continuous mean-reversion trade | `experiments/k488/`, `experiments/k503/` |
| K499 | Monthly rebalancing optimal; transaction cost breakeven | Daily breakeven 3.4 bps; monthly breakeven 14.9 bps | `experiments/k499/` |
| K507 | 50/50 allocation irreducibility | Dynamic allocation fails Harvey threshold | `experiments/k507/` |
| K518 | 5 trend-following strategies fail Harvey t>3.0 | Direct test: SMA, Faber, Golden Cross, Dual Mom, MA+VT all fail | `experiments/k518/` |
| K533 | Prediction accuracy ≠ allocation optimality | Strengthens core thesis that VT value is in risk-scaling, not direction | `experiments/k533/` |
| K568 | 427 VT configurations sweep | 12/VIX is return-optimal among 427 configs | `experiments/k568/` |
| K697 | VIX predictive power: magnitude vs direction | r=0.570 magnitude, r=0.042 direction; supports Section 4.2 VIX-as-risk-scaling argument | `experiments/k697/` |

---

## Reconciliation Experiments (flagged in review_v2 H5)

These show methodology boundary conditions — paper acknowledges via footnote/discussion.

| K | Title | Contribution | Path |
|---|-------|--------------|------|
| K687 | Post-correction strategy ranking (50/50 SPY+GLD, VT-on-blend) | Shows VT-on-blend does NOT beat BH 50/50 (Sharpe 0.438 < 0.545); reconciles methodology gap — paper evaluates per-asset VT then blends | `experiments/k687/` |
| K688 | CRRA utility with properly lagged signals | 12/VIX does NOT win at any gamma for SPY/GLD blend; boundary condition for Cederburg rebuttal | `experiments/k688/` |

---

## Superseded Experiments (kept for audit trail; not cited in v3)

| K | Title | Status | Path |
|---|-------|--------|------|
| K901 | Original 13-market international VT (wrong asset set EWH/EWY; missing EWC/VGK/INDA/MCHI) | **SUPERSEDED by K1178** (per audit BLOCKER D5) | `experiments/k901/` |
| K901b | 13-market nosource rescan stub | Incomplete | `experiments/k901b/` |

---

## Table → Experiment Mapping (current v3 body)

| Table / Figure | Caption | Source Experiment(s) |
|----------------|---------|----------------------|
| Table 1 | VT Alpha Decomposition: CAPM vs CAPM + TSMOM (N=22) | K55 (`vt_tsmom_final_n22.json`) |
| Table 2 | Cross-Sectional Predictors of VT's TSMOM Loading (N=22) | K55 + K1193 (split-sample row) |
| Table 3 | Dual Mechanism Decomposition: Sharpe Ratio and MDD | K898 (5-asset canonical supplement) |
| Table 4 | Factor Model Controls: SPY 12/VIX Strategy (M1–M5) | K54 / K71 (`ff5_factor_controls.json`) |
| Table 5 | International VT: US VIX as Broad MDD Protection (N=13) | K1178 (canonical) |
| Table 6 | Block Bootstrap CIs for MDD Retention | K1192 (canonical) |
| Figure 1 | VT Return Decomposition: Sharpe vs MDD channels | K898 data → `figures/fig1_return_decomposition.pdf` |
| Figure 2 | Cross-Asset VT: ΔSharpe vs ΔMDD (N=13) | K1178 data → `figures/fig2_cross_asset_scatter.pdf` |

---

## Outstanding / PENDING Experiments

The following experiments were proposed in `reproducibility_audit/undocumented_k_additions_for_experiments_md.md` but have NOT been executed. They are not required by v3 body (K1178/K1192/K1193 canonical updates superseded most), but listed for completeness:

| Proposed K | Content | Target Section | Priority |
|------------|---------|----------------|----------|
| K1179 | 11 SPDR sector ETFs (XLB/XLE/XLF/XLI/XLK/XLP/XLU/XLV/XLY/XLRE/XLC); sector gamma vs TSMOM loading | Section 3.4 "equity-sector boundary condition" | OPTIONAL (v3 already cites r=0.163 NS as boundary) |
| K1180 | 50/50 SPY/GLD sub-period stability (pre-COVID, COVID, post-COVID, OOS) | Section 3.6 | OPTIONAL |
| K1181 | v2 Table 6 bootstrap with paper's original (unclear) formula | BODY_V2 ERRATA | **OBSOLETE** — K1192 canonical replaces v2 Table 6 |
| K1182 | Split-sample K55 (gamma 2007–16, TSMOM beta 2017–26) | Section 3.3 | **COMPLETED as K1193** |

Sector analysis numbers in v3 (`r = 0.163`, `N = 11`) currently untraceable; they appear to be summary statistics mentioned in text without a dedicated K experiment. **PENDING: K1179 needed before submission if reviewer requests traceability for sector boundary claim.**

---

## Known Divergences (documented in forensic notes)

| Number in paper | K experiment | Status |
|-----------------|--------------|--------|
| Table 3 Hedged VT Sharpe v2 values (0.737, 0.937) | K898 (0.848, 0.830) | **v3 forensic note** — v3 uses K898 canonical, marks v2 values superseded |
| "1.4% TSMOM contribution" v2 claim | K898 back-calc 5.3% | **v3 forensic note** — v3 reports 5.3% with caveat, 1.4% not traceable |
| Table 6 v2 CIs [86,97] etc. | K1192 [93,182] etc. | **v3 forensic note** — v3 uses K1192 canonical, v2 CIs flagged unreproducible |
| Table 5 v2 ρ=0.830 (GJR γ vs ΔSharpe) | K1178 ρ=0.187 (NS) | **v3 removes** — not reproducible; v3 footnote documents removal |
| Table 4 M5 N=3,740 vs K54 N=5,049 | K54 full sample with IWD-QQQ splice pre-2011 | **H2 PENDING** — reconcile BAB proxy documentation before submission |

---

## Known Issues (from audit_step1_2.md + nosource_rescan_report.md)

- **A.1**: Table 3 → K898 provides verified data (daily signal; paper spec = monthly). v3 uses K898 numbers.
- **A.2**: Table 5 13-market asset list → K1178 canonical (asset set corrected).
- **A.3**: Table 6 bootstrap → K1192 canonical.
- **B.1**: Sample period inconsistency (2005 vs 2007 vs 1998 across tables). **PENDING** — needs body edit to reconcile in main-thread revision.
- **B.2**: Table 4 M5 N=3740 vs K54 N=5049 (BAB proxy). **PENDING** — either clarify N or re-run with AQR BAB factor.
- **B.3**: MDD retention reported for 5 equity assets only; no non-equity extension. **PENDING**.
- **C.1**: "1.4%" TSMOM Sharpe contribution — v3 reports 5.3% with forensic caveat.
- **H5**: K687/K688/K697 reconciliation — K687/K688 methodology note must appear in Section 4 (VT-per-asset vs VT-on-blend); K697 should be cited in Section 4.2.

See `reproducibility_audit/diff_report.md` and `reproducibility_audit/README.md` for the full audit trail.
