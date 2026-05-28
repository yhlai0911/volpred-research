# Experiment Index — Paper 2: Volatility Targeting in Taiwan

Full table of all experiments supporting this paper.
Columns: K-ID | Paper Section | Title | Verdict | Status | Location

**Verdict legend**: PASS / CONDITIONAL_PASS / NULL / FAIL / PARTIAL_MATCH / (verdict not recorded)
**Location**: `local` = `paper/taiwan-vt/experiments/`; `root` = `experiments/<K>/`

---

| K | Paper Section | Title | Verdict | Status | Location |
|---|---------------|-------|---------|--------|----------|
| K461 | Sec 3.3 Cross-Market Spillover | SSVS macro predictors for 0050.TW ARX-GARCH — SPY_ret_L1 PIP=1.0, VIX PIP=0.801 | CONDITIONAL_PASS | complete | local |
| K472 | Sec 4.2 GJR vs GARCH | Taiwan comprehensive vol prediction — EWMA / HAR / semivariance all ≈ GJR (DM p>0.05) | CONDITIONAL_PASS | complete | root |
| K512 | Sec 6.4 Ex-Dividend Vol | Taiwan ex-div vol — pre-div calm, post-div +32% (0050, t=2.28) / +69% (0056, t=3.80) spike; fill rates 79% / 90% within 60d | CONDITIONAL_PASS | complete | root |
| K515 | Sec 5.3 Overnight Gap | Taiwan overnight gap alpha — gap=86.5% of total return; SPY+VIX conditional gap=+10.73bp (t=6.845, Harvey PASS) but ETF TX=38.5bp non-tradeable | CONDITIONAL_PASS | complete | root |
| K516 | Sec 5.3 Futures Implementation | Overnight gap with TAIFEX futures TX=5bp — SPY+VIX Sharpe=0.926, 5/5 cross-OOS positive; breakeven TX=10.73bp (institutional-only) | CONDITIONAL_PASS | complete | root |
| K553 | Sec 4.4 Conditional Leverage | VIX-conditional leverage VT for Taiwan — Hybrid RV+Pctile lev=1.5 Sharpe +0.248; Harvey t>3.0 PASS | PASS | complete | local |
| K558 | Sec 4.4 Conditional Leverage | K553 deep validation — 11/11 gates PASS (Harvey / cross-OOS / sensitivity / tx-cost / drawdown) | PASS | complete | local |
| K636 | Sec 3.2 Diversification Amplification | Taiwan amplification factor deep dive — γ-ratio TAIEX/stock ≈ 4.6×; reconciles K530 vs K633 | (verdict not recorded) | complete | root |
| K844 | Sec 5 HF / Appendix | TX futures VT vs 0050.TW stock VT — futures Sharpe +0.095 but DM Harvey FAIL (t=0.216) | CONDITIONAL_PASS | complete | local |
| K847 | Sec 5 HF — Overnight Gap | Overnight gap decomposition — Slot B+C absorb 73.3% of gap variance; ~61% of gap tradable | (verdict not recorded) | complete | local |
| K848 | Sec 5 HF — RV Statistics | TAIFEX 5-min RV construction — night session 43.3% of RV; r² noisy proxy (ratio 0.65) | (verdict not recorded) | complete | local |
| K849 | Sec 5 HF — HAR vs GJR | HAR-RV vs GJR on TAIFEX — Track A best: HAR-RV-J (QLIKE=0.180); inconsistent across tracks | (verdict not recorded) | complete | local |
| K850 | Sec 6 VaR | HAR-RV VaR for 0050.TW — GJR+CF champion (2 violations); HAR QLIKE better but VaR trinity FAIL | CONDITIONAL_PASS | complete | local |
| K851 | Sec 5 HF — Jumps | Jump dynamics (BNS) — significant jumps 10.1% of days; jump share of RV 2.5%; HAR-CJ +1.23% not sig | (verdict not recorded) | complete | local |
| K852 | Sec 5 HF — RealGARCH | Realized GARCH — beats GJR on QLIKE; HAR-RV QLIKE=0.101 still best overall | (verdict not recorded) | complete | local |
| K852b | Sec 5 HF — Regime HAR | Regime-dependent HAR — best QLIKE 0.119; no DM Harvey-significant improvement vs HAR-RV | (verdict not recorded) | complete | local |
| K853 | Sec 5 HF — Proxy Ceiling | Proxy ceiling ablation — HAR-RV ranks 1st under all proxy conditions; proxy choice determines ranking | (verdict not recorded) | complete | local |
| K854 | Sec 6 VaR | Common-sample VaR (fix K850 unfair comparison) — GJR+CF and RGL+CF PASS 1% VaR trinity | CONDITIONAL_PASS | complete | local |
| K886 | Sec 4 VT Strategies | PRG on 0050.TW — PRG_Extended best QLIKE 0.7838; DM t=5.27 Harvey PASS vs GJR | (verdict not recorded) | complete | local |
| K892 | Sec 2 Data / Sec 3 Leverage | Canonical 0050.TW GJR gamma — γ=0.097 (full-sample), 0.080 (rolling w=2000); resolves paper conflict | PASS | complete | local |
| K896 | Sec 4.2 / Sec 6.5 ES | Expected shortfall analysis — GJR+HistSim VaR PASS + ES PASS + best Fissler-Ziegel | (verdict not recorded) | complete | local |
| K900 | Sec 4 VT Performance | Taiwan VT performance tables — GJR VT Sharpe 1.074; VIX-863 Sharpe 1.137, MDD −13.7% | (verdict not recorded) | complete | local |
| K1098 | Sec 4.5 VIXTWN Linearity | A4f with VIXTWN vs VIX — H1–H4 all FAIL; VIXTWN does not beat VIX in Taiwan context | FAIL | complete | root |
| K1145 | Sec 5 EAV / Five-Layer Robustness | A4f-EAV Taiwan (N=31 stocks) — placebo rejection_rate=0.0; EAV effect not attributable to chance | PASS | complete | root |
| K1147 | Sec 5 EAV / Three-Market Evidence | A4f-EAV US (N=30 S&P 500) — primary t PASS, bootstrap PASS | PASS | complete | root |
| K1150 | Sec 5 EAV / Three-Market Evidence | A4f-EAV Japan (N=30 TOPIX) — primary t PASS, bootstrap PASS | PASS | complete | root |
| K1175 | Sec 4.2 / Sec 4.3 / Conclusion | Table 3 VT 2010–2026 canonical replication — buy-hold Sharpe diff ~9.6% from paper (period mismatch) | PARTIAL_MATCH | complete | root |
| K1176 | Appendix Time-Zone / Table 4 | Cross-market TZ momentum replication — split-corrected 0050.TW c2c Sharpe 1.915 vs legacy 1.473; canonical o2o defined as adj-open$_t$/adj-open$_{t-1}$ with 2014-01-02 split date excluded | PARTIAL_MATCH | complete | root |
| K1180 | Sec 6.2 / Sec 6.3 BCI Momentum | Coincident MoM strategy IS Sharpe 0.413 (paper 0.732 unreproducible — errata applied to body.tex line 486); OOS Sharpe 1.2694 (paper 1.260) MATCH; BCI null t=-0.5349 (paper -0.53) MATCH; Leading MoM t=3.74 PARTIAL_MATCH | PARTIAL_MATCH | complete | root |
| K1181 | Sec 2.4 VIX Proxy / Sec 4.5 | VIXTWN stats + Steiger Z — ρ=0.594 matched (paper 0.595); 64-month window confirmed | PARTIAL_MATCH | complete | root |
| K1302 | Sec 2 / Sec 3.1 / Sec 8.5 | Table 2 individual γ rebuild — 9+1 stocks, 100 multistart, 0 failures; all targets matched | PASS | complete | root |
| K1302b | Sec 3.1 Diversification | γ for 5 unlisted Taiwan stocks — all 5 converged, avg γ=0.024, persistence<1 | PASS | complete | root |
| K1370 | Introduction / Sec 3.2 / Sec 8 | Bootstrap 90% CI [2.28, 6.58] for amplification ratio 4.3× (canonical BW-robust) | (verdict not recorded) | complete | root |
| K1370c | Sec 3.2 Sensitivity | N_start=10 vs 100 sensitivity micro-test for K1370 — PASS; N_start=10 sufficient | PASS | complete | root |

---

## Experiment Count Summary

- Total experiments: 34
- Local (`paper/taiwan-vt/experiments/`): 17 scripts + 18 result JSONs (k851 has 2 JSONs)
- Root (`experiments/<K>/`): 17 experiments
- PASS: 8 (K553, K558, K892, K1145, K1147, K1150, K1302, K1302b, K1370c)
- CONDITIONAL_PASS: 7 (K461, K472, K512, K515, K516, K844, K850, K854)
- FAIL: 1 (K1098)
- PARTIAL_MATCH: 4 (K1175, K1176, K1180, K1181)
- verdict not recorded: 14 (K636, K844, K847, K848, K849, K851, K852, K852b, K853, K886, K896, K900, K1302b, K1370)

## Open Issues Affecting Submission

- **H1 HIGH (blocking)**: Three-way γ inconsistency for 0050.TW (body.tex lines 52/137/148/683)
- **H2 HIGH (blocking)**: ELITE Material (2383.TW) in Table 2 (K1302) but absent from Sec 2.1 data description
- See `README.md` for full issue list

*Generated: 2026-05-26 — do not edit manually; update via task paper_taiwan_vt_self_contained*
