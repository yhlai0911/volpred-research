# Paper 1 — Supporting Experiments Index

**Paper**: Leverage Direction Matters: Cross-Asset Evidence on GARCH Model Selection and Volatility Targeting
**Target Journal**: Journal of Banking and Finance (JBF)
**Current body**: `body_v3.tex` / `main_v3.tex`
**Last Updated**: 2026-05-25

This file is the canonical table/figure → experiment K-id mapping. Companion
docs: `README.md` (paper status), `data_sources.md` (data provenance),
`results/README.md` (canonical JSONs index), `scripts/README.md` (regen entry
points), `reproduce.py` (verifier).

---

## Canonical table provenance

| Table / Figure | Caption / Claim | Source Experiment(s) | Provenance JSON | Status |
|---|---|---|---|---|
| Table 1 | Descriptive statistics across 7 primary assets | K902 | `experiments/k902_paper1_tables_supplement_results.json::table1_descriptive_stats` | MATCH (per K902 rerun) |
| Table 2 | Subperiod descriptive stats | (no dedicated K) | — | UNTRACEABLE (structural data-limit) |
| Table 3 | GARCH family parameter estimates | K799 + K902 | `experiments/k799_grand_evaluation_results.json` + `k902_*_results.json` | MATCH |
| Table 4 | VaR 1% Attribution Analysis (SPY 2020-2025, 1508 days) | K1185 | `../experiments/k1185/k1185_results.json` | MATCH (canonical replication of 4-config stack) |
| Table 5 | Cross-OOS QLIKE / VaR panel (SPY) | K799 / K802 / K824v2 (cherry-pick — R1 C3) | `experiments/k{799,802,824v2}_*_results.json` | Partial (R1 C3: standardisation pending K899) |
| Table 6 | VaR panel across 7 assets | K829 | (path TBD; ref in body §4.2) | UNTRACEABLE in current report — K829 result not yet shimmed |
| Table 7 | Subperiod VaR robustness | K829 subset | — | UNTRACEABLE |
| Table 8 | Window Size Robustness: GJR-GARCH QLIKE for SPY (5 windows × 3 OOS) | K1188 | `../experiments/k1188/k1188_results.json` | MATCH 15/15 within ±0.10; closes prior `STILL_NO_SOURCE` |
| Table 9 | Asymmetric volatility regression | K902 | `k902_*_results.json::asymmetry_regression` | MATCH |
| Table 10 | Tail risk moments (kurtosis, ES) | K902 + K1209 batch 2 | `k902_*_results.json` + K1209 references | MATCH |
| Table 11 | Tail-risk per asset (T-TABLE11 proposed extension) | (proposal §4) | — | UNTRACEABLE (T-TABLE11 not yet built) |
| Table 12 | VT cumulative returns / Sharpe / MDD | K273 → K276 propagation | `experiments/k276/k276_jbf_updates.py` outputs | MATCH (with rounding noted at 0.985→0.99) |
| Table 13 | Cross-asset Sharpe / MDD detail | K273 / K276 | as Table 12 | MATCH |
| Table 14 | Crisis-period breakdown | K273 + (no dedicated K) | — | UNTRACEABLE |

---

## Canonical figure provenance

Full status per figure (COMPLETE / PARTIAL / MISSING-placeholder) in
`scripts/figures/data_source.md`. Summary:

| # | Figure | body.tex L# | Generator | Status | Source |
|---|---|---|---|---|---|
| 1 | fig_rolling_gamma | L220 | `scripts/figures/fig_rolling_gamma.py` | PARTIAL (placeholder) | K902 summary stats |
| 2 | fig_vix_garch_ratio | L227 | `scripts/figures/fig_vix_garch_ratio.py` | MISSING (placeholder) | needs daily VIX+σ ratio CSV |
| 3 | fig_cumulative_returns | L246 | `scripts/figures/fig_cumulative_returns.py` | MISSING (placeholder) | needs daily B&H vs VT CSV |
| 4 | fig_gamma_mechanism | L411 | `scripts/figures/fig_gamma_mechanism.py` | COMPLETE | body.tex inline + K902 sanity |
| 5 | fig_vix_weight_timeline | L460 | `scripts/figures/fig_vix_weight_timeline.py` | MISSING (placeholder) | needs `data/vix_daily.csv` extended pull |
| 6 | fig_mdd_comparison | L471 | `scripts/figures/fig_mdd_comparison.py` | PARTIAL | K273 protection values via K276 |
| 7 | fig_kurtosis_reduction | (orphan) | `scripts/figures/fig_kurtosis_reduction.py` | PARTIAL (orphan: not `\includegraphics`'d) | K902 Table 1; pending T-TABLE11 |

---

## Canonical K-experiments (alphabetical by K-id)

- **K273** — VT crisis taxonomy and per-crisis MDD protection deltas. Drives
  Table 12-13 protection cells and `fig_mdd_comparison.py`. Lives in
  `experiments/k273/` with knowledge IDs `e8e069f7` and `1fd0be4b`.
- **K276** — K273 propagation into JBF table updates
  (`experiments/k276/k276_jbf_updates.py`).
- **K799** — Grand Model Evaluation: SPY QLIKE + VaR, 2023-24 OOS. Source for
  Table 5 QLIKE column and several Table 4 cells. Paper-folder shim:
  `experiments/k799_grand_evaluation_results.json`.
- **K802** — GJR + Skewed-t distribution, SPY VaR orthogonality (2023-24 OOS).
  Canonical source for Table 4 Student-t row and Kupiec p (after L93/L95
  rounding fix). Shim: `experiments/k802_gjr_skewt_results.json`.
- **K824v2** — Probabilistic RV quantile forecasting, SPY HistSim VaR. Table 4
  Adaptive row source. Shim: `experiments/k824v2_quantile_fixed_results.json`.
- **K829** — VaR panel across 7 assets (Table 6 source). Not yet shimmed into
  `paper/leverage-direction/experiments/`; **TODO** for self-contained
  completeness — currently reads from `experiments/k829/` only.
- **K902** — Paper 1 supplement: cross-asset GJR γ, rolling-γ summaries,
  Table 1 descriptive stats, asymmetry regression. Shim:
  `experiments/k902_paper1_tables_supplement_results.json`.
- **K1185** — Table 4 canonical replication closing prior C5 untraceability
  (the four-config 1508-day SPY VaR stack). Full provenance in
  `experiments/k1185/` (script + results + diff vs paper). MATCH within
  ±3 violation count drift attributed to yfinance vintage.
- **K1188** — Table 8 window-size robustness closing the `STILL_NO_SOURCE`
  flag for the 5×3 QLIKE grid. 15/15 MATCH within ±0.10 absolute. Full
  provenance in `experiments/k1188/`.
- **K1209 (batch 2)** — Tail-risk validation, feeds Table 10 row 7 and the
  fig_kurtosis_reduction narrative.
- **K1256** — Henriksson-Merton γ 3-spec disambiguation (`pure_vt_full`,
  `pure_vt_high_vix`, `hybrid_vt_full`). All three γ signs negative
  (variance-management thesis confirmed qualitatively). Magnitudes 17-55%
  smaller than body_v3 L433 footnote; DIVERGENT_SAME_SIGN NOTE triggers L11
  errata path (c). Full provenance: `experiments/k1256/`.

---

## Open items (proposal.md / R1 follow-ups)

- **R1 C3**: Table 5 cross-OOS standardisation across K799 / K802 / K824v2 —
  K899 unified VaR panel pending.
- **R1 C4-C5**: Tables 1, 3 partial untraceability — covered by K902 for most
  cells; 2 cells remain UNTRACEABLE (structural).
- **T-TABLE11**: dedicated tail-risk JSON per asset to replace narrative
  kurtosis estimates in `fig_kurtosis_reduction.py`.
- **T-FIG-DATA**: 3 daily CSV bundles to lift figs 1/2/3/5 from PLACEHOLDER
  → COMPLETE. Smallest unblock: `data/vix_daily.csv` extended pull
  (`fig_vix_weight_timeline`).
- **K829 paper-folder shim**: drop a `experiments/k829_var_panel_results.json`
  copy to mirror the K799/K802/K824v2/K902 self-contained pattern.

---

## Audit notes (preserved from prior versions)

- K1185 is the provenance source for Table 4's previously undocumented
  configuration stack. Qualitative ordering stable: `Normal > Student-t >
  Adaptive = Jump`. Normal row has ±3 violation count vintage sensitivity;
  documented as Table 4 footnote rather than rewritten without original
  vintage snapshot.
- K1188 resolves the prior `STILL_NO_SOURCE` flag on Table 8 (per
  `nosource_rescan_report.md`). Provenance: agent-a0e0bd14 (2026-04-17);
  details in `experiments/k1188/k1188_vs_paper1_table8_diff.md`. QLIKE
  expressed in quasi-LL scale (range ~-8 to -9); **not** Patton-centered
  (K783b used Patton scale ~1.5 — incompatible). Rolling fixed window, refit
  monthly for w≤1000 / quarterly for w>1000, seed=42.
