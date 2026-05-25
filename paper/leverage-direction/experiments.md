# Paper 1: Supporting Experiments Index

**Paper**: Leverage Direction Matters: Cross-Asset Evidence on GARCH Model Selection and Volatility Targeting  
**Current body**: `body_v3.tex` / `main_v3.tex`  
**Last Updated**: 2026-05-25

---

## Canonical Experiment Mappings

| Table / Figure | Caption / Claim | Source Experiment(s) | Notes |
|---|---|---|---|
| Table 4 | VaR 1\% Attribution Analysis: SPY (2020--2025, 1508 days) | K1185 (`experiments/k1185/`) | Canonical replication of the four Table 4 configurations. Confirms the baseline is symmetric GARCH(1,1), Student-$t$ uses fixed df=5 with scale correction $\sqrt{(\nu-2)/\nu}$, and the adaptive threshold is a 20-day rolling maximum sigma rule. Minor Normal-row count drift of up to $\pm 3$ violations may arise from yfinance data-vintage revisions. |
| Table 8 | Window Size Robustness: GJR-GARCH QLIKE for SPY (5 windows × 3 OOS periods) | K1188 (`experiments/k1188/`) | Canonical replication closing the final Paper 1 STILL_NO_SOURCE entry. 15/15 cells match within ±0.10 absolute tolerance; best-window rank per period (504 for 2020--2021; 5000 for 2023--2024 and 2025--2026) reproduced exactly. QLIKE expressed in quasi-LL scale (range ~-8 to -9); **not** Patton-centered (K783b used Patton scale ~1.5 — incompatible). Rolling fixed window, refit monthly for w≤1000 / quarterly for w>1000, seed=42. |

---

## Audit Notes

- K1185 is the provenance source for Table 4's previously undocumented configuration stack.
- The qualitative ordering in Table 4 is stable under replication: `Normal > Student-t > Adaptive = Jump`.
- The Normal row is the only cell with data-vintage sensitivity material enough to move the raw violation count by a few observations; K1185 recommends documenting this as a footnote rather than rewriting the published table without the original vintage snapshot.
- K1188 resolves the prior `STILL_NO_SOURCE` flag on Table 8 (per `nosource_rescan_report.md`). Provenance: agent-a0e0bd14 (2026-04-17); details in `experiments/k1188/k1188_vs_paper1_table8_diff.md`.
