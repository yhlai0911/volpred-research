# Paper 3: Results Index

**Paper**: Is Volatility Targeting Just Trend Following?
**Results Last Updated**: 2026-04-18

This directory indexes results backing each Table and Figure in `body_v3.tex`. The actual JSON payloads are stored in `paper/vt-trend-following/experiments/` (for K55/K54/K79/K898) and `experiments/kXXX/` (for K1178/K1192/K1193). This README acts as the single source of truth for traceability.

---

## Tables → Source Mapping

| Table | Description | Source File |
|-------|-------------|-------------|
| Table 1 | VT Alpha Decomposition: CAPM vs CAPM + TSMOM (N=22) | `../experiments/vt_tsmom_final_n22.json` (K55) |
| Table 2 | Cross-Sectional Predictors of VT's TSMOM Loading (N=22) | `../experiments/vt_tsmom_final_n22.json` (K55) + `../../../experiments/k1193/k1193_results.json` (split-sample row) |
| Table 3 | Dual Mechanism Decomposition: Sharpe Ratio and MDD | `../experiments/k898_paper3_table3_supplement_results.json` (K898, 5-asset canonical) |
| Table 4 | Factor Model Controls: SPY 12/VIX Strategy (M1–M5) | `../experiments/ff5_factor_controls.json` (K54 / K71) |
| Table 5 | International VT: US VIX as Broad MDD Protection (N=13) | `../../../experiments/k1178/k1178_results.json` (K1178 canonical) |
| Table 6 | Block Bootstrap CIs for MDD Retention | `../../../experiments/k1192/k1192_results.json` (K1192 canonical) |

---

## Figures

| Figure | Description | File |
|--------|-------------|------|
| Figure 1 | VT Return Decomposition: Sharpe Ratio vs MDD channels | `../figures/fig1_return_decomposition.pdf` |
| Figure 2 | Cross-Asset VT: ΔSharpe vs ΔMDD for 13 International Markets | `../figures/fig2_cross_asset_scatter.pdf` |

Figure generator: `../figures/generate_figures.py` (reads K898 + K1178 JSONs).

---

## Key Numbers in `body_v3.tex` and Their Canonical Sources

### Abstract

| Claim | Value | Source |
|-------|-------|--------|
| K1192 canonical MDD retention: SPY | 103.7% | `experiments/k1192/k1192_results.json` |
| K1192 canonical MDD retention: 50/50 | 95.6% | `experiments/k1192/k1192_results.json` |
| K1192 canonical MDD retention: DIA | 106.2% | `experiments/k1192/k1192_results.json` |
| K1192 canonical MDD retention: QQQ | 109.0% | `experiments/k1192/k1192_results.json` |
| K1192 canonical MDD retention: IWM | 102.2% | `experiments/k1192/k1192_results.json` |
| 90% CI lower bounds | 76–93% | `experiments/k1192/k1192_results.json` |
| Cross-sectional r (γ vs TSMOM_orth, N=22) | 0.564, p=0.006 | `experiments/vt_tsmom_final_n22.json` |
| Split-sample r | 0.793, p<0.001 | `experiments/k1193/k1193_results.json` |
| Sector r (N=11) | 0.163, NS | PENDING K1179 — text-only, no JSON source |
| International avg ΔMDD | 24.9pp, t=10.25 | `experiments/k1178/k1178_results.json` |
| International VIX sens vs ΔMDD | r=−0.806, ρ=−0.835 | `experiments/k1178/k1178_results.json` |
| 5 canonical TF strategies fail Harvey t>3.0 | — | `experiments/k518/` |

### Section 3 (Methodology + Results)

| Claim | Source |
|-------|--------|
| Table 1 full 22-asset panel | K55 JSON |
| Table 2 panel A: r=0.564, p=0.006, CI [0.263, 0.772] | K55 JSON `cross_sectional_analysis.beta_tsmom_orth_vs_gamma` |
| Table 2 panel B split-sample: r=0.793, CI [0.589, 0.919], ρ=0.749 | K1193 JSON (replaces earlier r=0.487 claim) |
| Table 3 SPY B&H Sharpe, VT Sharpe, Hedged VT Sharpe, Pure TSMOM | K898 JSON `table3.SPY` |
| Table 3 50/50 row | K898 JSON `table3.50/50` |
| Table 3 MDD retention all 5 assets | K898 JSON `mdd_retention_all_assets` + K1192 canonical updates |
| Table 4 M1–M5 alpha/t/R²/AIC/N | K54/K71 JSON `strategy_results.12_VIX_VT.full_sample` |
| Section 3.4 sector boundary (r=0.163 NS, N=11) | PENDING K1179 — currently text-only |

### Section 4 (International + Discussion)

| Claim | Source |
|-------|--------|
| Table 5 all 13 markets VT/BH/ΔSharpe/ΔMDD | K1178 JSON |
| Table 5 cross-section r=−0.806 / ρ=−0.835 | K1178 JSON |
| Table 5 average ΔMDD 24.9pp, t=10.25 | K1178 JSON |
| Table 6 bootstrap CIs (all 5 assets) | K1192 JSON |
| Table 6 MDD retention fraction formula (Eq. mdd_retention_boot) | K1192 `definition_a` (paper-canonical definition) |
| VIX predictive power r=0.570 / 0.042 | K697 JSON |
| Daily bps breakeven 3.4 / monthly 14.9 | K499 JSON |
| 12/VIX return-optimal among 427 configs | K568 JSON |

### Section 5 (Forensic Notes)

Each forensic note in `body_v3.tex` Section 5 cross-references the canonical K and the superseded v2 value:

1. **ρ = 0.830 (GJR γ vs ΔSharpe)** — removed in v3, K1178 gives ρ = 0.187 (NS).
2. **"1.4% TSMOM contribution"** — v3 reports 5.3% back-calc from K898.
3. **Table 6 point estimates 90–97%** — superseded by K1192 canonical (95.6–109.0% with CI extending above 100%).
4. **Split-sample r = 0.487** — superseded by K1193 canonical r = 0.793.

---

## Reproduction

```bash
# Audit paper numbers against canonical JSONs
uv run python paper/vt-trend-following/reproduce.py

# Re-run specific canonical experiments
uv run python experiments/k1178/k1178.py     # Table 5
uv run python experiments/k1192/k1192.py     # Table 6
uv run python experiments/k1193/k1193.py     # Table 2 panel B split-sample

# K898 (from paper folder to preserve local JSON copy)
cd paper/vt-trend-following && uv run python experiments/k898_paper3_table3_supplement.py && cd ../..
```

See `../scripts/README.md` for full dependency list and reproduction sequence.

---

## Known Divergences (cross-reference)

See:

- `../reproducibility_audit/diff_report.md` — D1–D8 full forensic trail
- `../reproducibility_audit/audit_step1_2.md` — Step 1 & 2 audit commentary
- `../reproducibility_audit/nosource_rescan_report.md` — which claims had no source JSON
- `../reproducibility_audit/undocumented_k_additions_for_experiments_md.md` — K1178/K1192/K1193 origin notes

Nearly all previously-untraceable items have been resolved by K898/K1178/K1192/K1193 canonical runs. Outstanding items (all marked PENDING in `../experiments.md`):

- **Table 4 M5 N=3,740 vs K54 N=5,049** (BAB proxy reconciliation) — H2
- **Period inconsistency** (2005/2007 start dates across tables) — B.1
- **Non-equity MDD retention extension** — B.3
- **Sector r=0.163 traceability** (Section 3.4) — needs K1179 or explicit text-only footnote
