# BTC-GAS Negative-Result Paper — Replication Package

**Title**: Why GAS-t Fails on Pre-Institutional Bitcoin: Student-t Innovation, Not Score-Driven Dynamics, Is the Culprit (and Regime-Switching Rescues to Parity, Not Superiority)

**Author**: Yi-Hao Lai (Da-Yeh University, Department of Finance)

**Target journal**: Journal of Banking and Finance (JBF) / International Journal of Forecasting (IJF) — negative-result methodology track

**Status**: `major_revision` — 2026-06-10 audit HIGH findings addressed in markdown draft, but `.tex` conversion remains blocked on pinned snapshot CSV, `reproduce.py`, and the planned robustness package

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
| K1129 | Cross-asset GAS-t baseline; flags BTC as the anomaly asset on its own 2021+ OOS window (DM-HLN ≈ -4.6) | `experiments/K1129/` |
| K1133 | BTC sub-period decomposition; isolates Period 1 (pre-institutional) as the source of the `-4.67` reversal | `experiments/k1133/` |
| K1133b | 5-model factorial + MS-GAS-t rescue; provides Key Numbers table | `experiments/k1133b/` |

All headline statistics (QLIKE point estimates, DM-HLN tests, and factorial contrasts) trace back to `*_results.json` in each experiment directory. The Key Numbers table in `drafts/v0_outline_abstract.md` is the single source of truth and is referenced by all body sections.

## Reproducibility status

- **Lookahead audit**: All forecasts use `realized.shift(1)`; independently reviewed by Codex (2026-04-17).
- **Multistart MLE**: ≥100 random initializations per fit (per K1213 methodology rule); log-likelihood basin stable across seeds.
- **Seed**: 42 across all three experiments; multistart seeds 1-100.
- **Data snapshot**: K1133b canonical sample ends on `2026-04-15`; a paper-local pinned CSV still needs to be landed before `.tex` conversion and reproduce-gate activation.

## Next steps (queued tasks)

1. Land a pinned snapshot CSV matching the canonical `2026-04-15` sample end.
2. Add `reproduce.py` with paper-wide numeric bindings and a green gate.
3. Run the planned robustness battery into `k1133b_robustness_results.json`.
4. Convert the markdown draft to JBF LaTeX only after the three blockers above settle.

## Submission gate checklist (pending)

- [ ] All 9 sections drafted (5/5 complete as of 2026-06-07)
- [x] R0 review cycle complete and HIGH findings addressed in markdown
- [ ] `reproduce.py` exists, exits 0, match_rate ≥ 95%, alert_level = green
- [ ] Every Table row has `% source:` binding to JSON field
- [ ] `data_sources.md` and the local snapshot CSV agree on the canonical 2026-04-15 sample
- [ ] `experiments.md` indexed with K-ID → contribution one-liner
- [ ] LaTeX main.tex compiles with xelatex
- [ ] paper-update CLI Supabase sync verified
