# BTC-GAS Negative-Result Paper — Replication Package

**Title**: Why GAS-t Fails on Pre-Institutional Bitcoin: Student-t Innovation, Not Score-Driven Dynamics, Is the Culprit (and Regime-Switching Cannot Fully Rescue It)

**Author**: Yi-Hao Lai (Da-Yeh University, Department of Finance)

**Target journal**: Journal of Banking and Finance (JBF) / International Journal of Forecasting (IJF) — negative-result methodology track

**Status**: `draft` — v1 body sections complete (2026-06-07), pending R0 review cycle

## Folder layout

```
paper/btc-gas-negative/
├── README.md              (this file)
├── drafts/                v0 outline + v1 section markdown drafts
│   ├── v0_outline_abstract.md
│   ├── v1_section1_introduction.md
│   ├── v1_section2_lit_review.md
│   ├── v1_section3_methodology.md
│   ├── v1_sections4-6_results.md
│   └── v1_sections7-9_discussion.md
├── data_sources.md        Provenance + API endpoints + snapshot pins
└── experiments.md         K-ID index pointing back to experiments/
```

## Supporting experiments (canonical sources of all numbers)

| K-ID | Role | Path |
|------|------|------|
| K1129 | Cross-asset GAS-t baseline; documents BTC full-sample reversal (DM-HLN -4.67) | `experiments/K1129/` |
| K1133 | BTC sub-period decomposition; isolates Period 1 (pre-institutional) as origin | `experiments/k1133/` |
| K1133b | 5-model factorial + MS-GAS-t rescue; provides Key Numbers table | `experiments/k1133b/` |

All headline statistics (QLIKE point estimates, DM-HLN tests, Spearman correlations) trace back to `*_results.json` in each experiment directory. The Key Numbers table in `drafts/v0_outline_abstract.md` is the single source of truth and is referenced by all body sections.

## Reproducibility status

- **Lookahead audit**: All forecasts use `realized.shift(1)`; independently reviewed by Codex (2026-04-17).
- **Multistart MLE**: ≥100 random initializations per fit (per K1213 methodology rule); log-likelihood basin stable across seeds.
- **Seed**: 42 across all three experiments; multistart seeds 1-100.
- **Data snapshot**: BTC-USD via yfinance with `auto_adjust=False`, fetched 2026-04-10 (K1133b run timestamp); cached snapshot at `data/btc/btc_daily.parquet`.

## Next steps (queued tasks)

1. R0 review cycle (paper-review-cycle: latex-academic-reviewer + citation-verifier in parallel) once all body markdown sections are complete.
2. Markdown → JBF LaTeX template conversion after R0 review settles.
3. `reproduce.py` script with `table_row_mapping` binding for every Table row.
4. `data_sources.md` with full API endpoint + period + license documentation.

## Submission gate checklist (pending)

- [ ] All 9 sections drafted (5/5 complete as of 2026-06-07)
- [ ] R0 review cycle complete and findings addressed
- [ ] `reproduce.py` exists, exits 0, match_rate ≥ 95%, alert_level = green
- [ ] Every Table row has `% source:` binding to JSON field
- [ ] `data_sources.md` lists all API endpoints + license conditions
- [ ] `experiments.md` indexed with K-ID → contribution one-liner
- [ ] LaTeX main.tex compiles with xelatex
- [ ] paper-update CLI Supabase sync verified
