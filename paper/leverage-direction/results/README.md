# Paper 1 — Results Index

**Paper**: Leverage Direction Matters (`paper/leverage-direction/`)
**Purpose**: index of canonical result JSONs and reproduce-gate outputs that
back every numerical claim in `body.tex` / `body_v3.tex`.
**Last updated**: 2026-05-25

This folder does **not** duplicate result files. It catalogues where each
canonical result lives in the existing two-tier layout:

- **Tier 1 (paper-folder shim)** — `paper/leverage-direction/experiments/*_results.json`:
  paper-local copies of the four canonical experiments that the paper depends
  on most directly (K799, K802, K824v2, K902 + HM timing tests).
- **Tier 2 (project K-exp tree)** — `experiments/k<NNN>/k<NNN>_results.json`:
  full provenance with README, run log, side-by-side diff against the paper.
  `reproduce.py::find_json` falls through to this tree as a backup.

---

## Canonical result JSONs (with body.tex anchors)

| Result file | K-id | Backs | body.tex anchor | Status |
|---|---|---|---|---|
| `experiments/k799_grand_evaluation_results.json` | K799 | Grand model evaluation (QLIKE + VaR, 2023-24 OOS, SPY) | Tables 4, 5 (some cells); Sec 4.2 QLIKE panel | MATCH |
| `experiments/k802_gjr_skewt_results.json` | K802 | GJR + Skewed-t VaR orthogonality (SPY) | Table 4 baseline + Kupiec p (after rounding fix); Sec 5.2 | MATCH |
| `experiments/k824v2_quantile_fixed_results.json` | K824v2 | Probabilistic RV quantile (SPY HistSim VaR) | Table 4 Adaptive row; Sec 4.4 | MATCH |
| `experiments/k902_paper1_tables_supplement_results.json` | K902 | Cross-asset GJR γ, rolling γ summaries, Table 1 stats | Table 1; Sec 4.3 rolling-γ; Sec 5.5 mechanism | MATCH |
| `experiments/hm_timing_tests_results.json` | (stub) | Henriksson-Merton γ pointer | — | Points to K1256 (3-spec) |
| `../experiments/k1185/k1185_results.json` | K1185 | Table 4 canonical replication (4-config stack) | Table 4 (canonical provenance) | MATCH |
| `../experiments/k1188/k1188_results.json` | K1188 | Table 8 window-size robustness | Table 8 (closes prior `STILL_NO_SOURCE`) | MATCH |
| `../experiments/k1256/k1256_results.json` | K1256 | HM γ 3-spec disambiguation | Sec 4.7 (3 specs) + L433 footnote | DIVERGENT_SAME_SIGN (NOTE) |

---

## Aggregate reproduce-gate output

| File | Purpose |
|---|---|
| `../reproduce.py` | Single-entry verifier: walks all canonical JSONs above + body.tex/tables.tex extracted numbers; emits Check rows with status MATCH/MISMATCH/NOTE/UNTRACEABLE |
| `../reproduce_report.json` | Latest run; **2026-05-17**: 0 MISMATCH, 28 MATCH, 9 NOTE, 19 UNTRACEABLE (structural data-limit), `alert_level=amber`, `gate_status=pass_with_untraceable`, `traceable_match_rate_pct=80.9` |

---

## Tables / figures in body.tex

Tables are produced inline as LaTeX in `tables.tex`. Figures live as PDFs in
the paper root and PNGs in `figures/`; generator scripts are in
`scripts/figures/` (per `scripts/README.md`).

| Output | Location | Built from |
|---|---|---|
| Tables 1-14 | `../tables.tex` (LaTeX inline) | K799 / K802 / K824v2 / K902 / K1185 / K1188 / K829 / K273 |
| Figures 1-7 | `../figures/*.png` + `../fig_*.pdf` | `scripts/figures/fig_*.py` (see `scripts/figures/data_source.md` for per-figure status) |

---

## Cross-reference

- `../README.md` — paper status, known R1 issues
- `../data_sources.md` — pinned CSVs and API provenance
- `../experiments.md` — table/figure → experiment mapping
- `../scripts/README.md` — replication entry points
- `../experiments/` — paper-local shim copies of canonical JSONs
- `../../../experiments/k{1185,1188,1256}/` — full K-exp provenance trees
