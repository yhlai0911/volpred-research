# Paper 3: Is Volatility Targeting Just Trend Following?

**Full title**: Is Volatility Targeting Just Trend Following? Decomposing the Benefits of Volatility Targeting
**Target Journal**: Journal of Portfolio Management / Financial Analysts Journal
**Status**: body_v3 HIGH = 0 (after v3 H1–H4 fixes, 2026-05-23); 13 MEDIUM + 7 LOW carry-forward from R4; ready for R5 review before submission
**Current body**: `body_v3.tex` / `main_v3.tex` (supersedes v1 and v2)
**Pages**: 33 | **Citations**: 18

---

## Self-Contained Replication Package Checklist (5/5)

Per `.claude/rules/paper-workflow.md` (hard requirement for submission).

- [x] **Data sources**: `data_sources.md` — lists all yfinance + Kenneth French tickers, API endpoints, sample periods, licenses.
- [x] **Reproduce scripts**: `scripts/README.md` — entry-point index mapping Tables/Figures → K experiments → scripts.
- [x] **Results**: `results/README.md` — traceability map between body numbers and canonical JSON source files; `figures/*.pdf` for Figures 1–2.
- [x] **Experiment index**: `experiments.md` — lists K55, K54, K71, K79, K898, K1178, K1192, K1193 (canonical) + K487–K697 (supporting) + K901 (superseded).
- [x] **README**: this file — title, target journal, status, K list, data summary.

---

## Supporting Experiments (canonical)

| K | Role | Table / Section |
|---|------|-----------------|
| K55 | 22-asset panel primary | Tables 1, 2 |
| K54 / K71 | FF5 + MOM + BAB factor controls | Table 4 |
| K79 | VIX threshold sensitivity | Discussion |
| K898 | 5-asset dual-mechanism supplement | Table 3 |
| K1178 | 13-market international (canonical) | Table 5 |
| K1192 | MDD retention block bootstrap (canonical) | Table 6 |
| K1193 | Split-sample robustness (canonical) | Section 3.3 / Table 2 panel B |

Supporting K experiments (cited in Discussion): K488, K499, K503, K507, K518, K533, K568, K687, K688, K697. Full list in `experiments.md`.

---

## Data Sources Summary

All data from free public APIs:

- **yfinance**: SPY, QQQ, DIA, IWM, XLF, XLE, EEM, EFA, FXI, EWZ, GLD, TLT, SHY (cash proxy), VIX, and 13-market international ETFs (EFA, EWJ, EWG, EWU, EWA, EWC, VGK, EEM, FXI, EWZ, INDA, EWT, MCHI).
- **Kenneth French Data Library**: FF5 + MOM factors.

No proprietary data. Full ticker list, sample periods, and license notes in `data_sources.md`.

---

## Reproduction

```bash
# One-shot audit: compare paper numbers against canonical JSONs
uv run python paper/vt-trend-following/reproduce.py

# Re-run canonical experiments
uv run python experiments/k1178/k1178.py     # Table 5 (13 markets)
uv run python experiments/k1192/k1192.py     # Table 6 (bootstrap MDD retention)
uv run python experiments/k1193/k1193.py     # Section 3.3 split-sample

# 5-asset dual-mechanism (Table 3)
cd paper/vt-trend-following
uv run python experiments/k898_paper3_table3_supplement.py
cd ../..
```

See `scripts/README.md` for dependencies and full reproduction sequence.

---

## Known Issues (v3 status)

**Resolved in v3** (K898/K1178/K1192/K1193 canonical updates):

- A.1 Table 3 → K898 provides 5-asset verified data.
- A.2 Table 5 13-market → K1178 canonical (asset set corrected from K901).
- A.3 Table 6 bootstrap → K1192 canonical (paper's Eq. mdd_retention_boot with monthly rebalancing).
- C.1 "1.4% TSMOM" → v3 forensic note + K898 back-calc 5.3%.
- Split-sample r=0.487 → K1193 canonical r=0.793.

**Still PENDING** (require main-thread revision):

- **B.1** Sample period inconsistency (Tables 1/3/4 vary: 2005, 2007, 1998 starts) — needs body reconciliation.
- **B.2** Table 4 M5 N=3,740 vs K54 N=5,049 (BAB proxy SPLV-SPHB post-2011 vs hybrid). Either clarify N in table note or re-run with AQR BAB factor.
- **B.3** MDD retention only reported for 5 equity assets; no non-equity extension.
- **Section 3.4 sector r=0.163 NS** traceability — text claim has no dedicated K experiment; need K1179 (11 SPDR sectors) or explicit text-only footnote before submission.
- **H5** K687/K688 reconciliation — the per-asset VT vs VT-on-blend methodology gap needs footnote in Section 4; K697 (VIX direction vs magnitude) should be cited in Section 4.2.

See `reproducibility_audit/diff_report.md`, `experiments.md`, and `results/README.md` for the full forensic trail.
