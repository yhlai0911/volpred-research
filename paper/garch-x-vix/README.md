# Paper 9: Multiplicative GARCH-X with VIX — A Parsimonious Alternative to GARCH-MIDAS

**Target Journal**: Journal of Empirical Finance / International Journal of Forecasting
**Status**: submitted (under review) | Reproduce gate snapshot-first 53.8% RED / live-mode 84.6% amber. 2026-04-19 **shelf-ready errata prepared** (see `errata_pending.md`): yfinance drift on K997/K1085 DM t-stats 0-11% relative (SPY 4.03→4.48, QQQ 3.71→3.89, GLD+GVZ 3.17→3.20, USO+OVX 4.47→4.47) — Harvey |t|>3 **qualitative invariant** across both snapshots; no paper body edit until R1 reviewer response, errata wording ready for submission.
**R1 prep (2026-05-17)**: K1066 dual-target robustness — A4f_oc vs GJR_oc (r²_oc DM t=+4.04 Harvey PASS), A4f_oc vs GJR_close (r²_oc DM t=+7.05), 5/5 sub-periods. Addresses Limitations proxy-sensitivity "future work." Shelf-ready LaTeX: `r1_prep/robustness_oc_proxy.tex`; Limitations revision wording included in file.
**Methodology note (2026-06-06)**: `main.tex` now carries an explicit footnote in the normalization-convention paragraph clarifying Engle (2013) Eq.~4 timing (`u_{t-1}/\sqrt{\tau_t}`) versus the DGP-timed alternative (`u_{t-1}/\sqrt{\tau_{t-1}}`), with pointers to K988/K988b design comparison and K1056b refit verification.
**Pages**: ~45 | **Citations**: 27 (24 verified, 1 MAJOR issue, 5 MEDIUM — see `citation_check.md`)

---

## Summary

Proposes a daily multiplicative GARCH-X model (σ²_t = τ_t × g_t) where τ_t is a simple function
of lagged VIX. In a 17-model horse race, the simplest daily VIX-squared spec with free intercept
(A4f) achieves the lowest QLIKE (DM t=4.03, Harvey |t|>3.0 threshold passed), outperforming all
GARCH-MIDAS variants. Key structural finding: the g_t component tracks the variance risk premium
(Spearman ρ≈0.80), providing an economic interpretation for the decomposition.

---

## Data Sources

See `data_sources.md` for full details.

- SPY, VIX, VIX9D, VIX3M, QQQ, GLD, GVZ, FEZ, 0050.TW: Yahoo Finance (yfinance)
- VIXTWN (Taiwan): TAIFEX (used in K1098 robustness)
- IS: rolling 2,000 trading days; OOS: 2019-01-01 – 2026-04-08 (n=1,825)

---

## Supporting Experiments

| K | Contribution |
|---|-------------|
| K889 | Original pilot: identified estimation/OOS denominator inconsistency (A1 spec in paper) |
| K889b | Cross-period robustness of multiplicative structure |
| K889v2 | Denominator-consistent fix confirmed improvement |
| K988 | **Main horse race**: 11 specs, A4f identified as champion |
| K988b | 6 additional GARCH-MIDAS specs (B1–B3, C1–C3); all fail to beat A4f |
| K989 | VIX² convexity synthesis; tau/OOS figures |
| K1085 | GLD+GVZ cross-asset PASS (t=+4.46) |
| K1088 | USO+OVX cross-asset PASS (t=+4.48) |
| K1098 | 0050.TW+VIXTWN Taiwan full 15-year test |

Full experiment index: see `experiments.md`.

---

## Reproduction

```bash
uv run python experiments/k988/k988.py           # core model comparison
uv run python paper/garch-x-vix/compute_mcs_dm.py  # MCS + DM tests
```

See `scripts/README.md` for full reproduction sequence.

---

## Key Results

- A4f: QLIKE = −8.360, DM t = 4.03 vs GJR-GARCH (Harvey PASS)
- Cross-asset: QQQ t=3.71, FEZ t=3.64, GLD+GVZ t=3.17
- VaR scorecard: A4f-t passes 3/4 levels vs GJR 1/4
- g_t Spearman ρ with VRP: 0.78–0.82 (vs raw ratio ρ=0.15)
- Kurtosis reduction: 60% absorbed by VIX τ component

---

## Files

```
paper/garch-x-vix/
  main.tex              — Paper body (DO NOT edit via agent)
  compute_mcs_dm.py     — MCS + DM computation script
  mcs_dm_results.json   — Full results (OOS 2019-2026, n=1825)
  citation_check.md     — Citation verification (1 MAJOR fabricated ref)
  review_history/v1/    — Review correspondence
  data_sources.md       — Data provenance index
  experiments.md        — K-number experiment index
  scripts/README.md     — Reproduction guide
  results/README.md     — Table/figure → source mapping
  figures/              — Soft-linked figures from experiments/kXXX/
```
