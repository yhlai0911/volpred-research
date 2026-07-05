# Experiment Index — Paper 2: Volatility Targeting in Taiwan

Canonical manuscript: `main_v3.tex` → `body_v3.tex`.
Columns: K-ID | Canonical manuscript binding | Title | Verdict | Status | Location

**Verdict legend**: PASS / CONDITIONAL_PASS / NULL / FAIL / PARTIAL_MATCH / (verdict not recorded)
**Location**: `local` = `paper/taiwan-vt/experiments/`; `root` = `experiments/<K>/`

---

## Canonical v3 Table / Figure Map

| Manuscript object | `body_v3.tex` label | Role |
|---|---|---|
| Table 1 | `tab:summary_stats` | Summary statistics for key assets |
| Table 2 | `tab:gamma` | GJR-GARCH leverage parameters |
| Figure 1 | `fig:rolling_gamma` | Rolling 252-day gamma estimates |
| Table 3 | `tab:ssvs_pip` | SSVS posterior inclusion probabilities |
| Table 4 | `tab:vt_results` | 0050.TW VT performance |
| Table 5 | `tab:vt_common` | Common-period VT comparison |
| Figure 2 | `fig:cumulative_returns` | VT cumulative wealth |
| Table 6 | `tab:sharpe_reconciliation` | Sharpe reconciliation |
| Appendix Table A1 | `tab:tz_results` | Time-zone momentum strategy performance |
| Appendix Figure A1 | `fig:overnight_vix` | Overnight gap / VIX evidence |

## Experiment Bindings

| K | Canonical manuscript binding | Title | Verdict | Status | Location |
|---|---------------|-------|---------|--------|----------|
| K461 | `sec:spillover`; `tab:ssvs_pip` | SSVS macro predictors for 0050.TW ARX-GARCH — SPY_ret_L1 PIP=1.0, VIX PIP=0.801 | CONDITIONAL_PASS | complete | local |
| K472 | `sec:vt`; `tab:vt_results` | Taiwan comprehensive vol prediction — EWMA / HAR / semivariance all ≈ GJR (DM p>0.05) | CONDITIONAL_PASS | complete | root |
| K512 | `sec:exdiv` | Taiwan ex-div vol — pre-div calm, post-div +32% (0050, t=2.28) / +69% (0056, t=3.80) spike; fill rates 79% / 90% within 60d | CONDITIONAL_PASS | complete | root |
| K515 | `app:tz`; `fig:overnight_vix` | Taiwan overnight gap alpha — gap=86.5% of total return; SPY+VIX conditional gap=+10.73bp (t=6.845, Harvey PASS) but ETF TX=38.5bp non-tradeable | CONDITIONAL_PASS | complete | root |
| K516 | `app:tz`; `tab:tz_results` | Overnight gap with TAIFEX futures TX=5bp — SPY+VIX Sharpe=0.926, 5/5 cross-OOS positive; breakeven TX=10.73bp (institutional-only) | CONDITIONAL_PASS | complete | root |
| K553 | `sec:cond_leverage`; `fig:cumulative_returns` | VIX-conditional leverage VT for Taiwan — Hybrid RV+Pctile lev=1.5 Sharpe +0.248; Harvey t>3.0 PASS | PASS | complete | local |
| K558 | `sec:cond_leverage`; `fig:cumulative_returns` | K553 deep validation — 11/11 gates PASS (Harvey / cross-OOS / sensitivity / tx-cost / drawdown) | PASS | complete | local |
| K636 | `sec:leverage`; `fig:rolling_gamma` | Taiwan amplification factor deep dive — γ-ratio TAIEX/stock ≈ 4.6×; reconciles K530 vs K633 | (verdict not recorded) | complete | root |
| K844 | `app:tz`; `tab:tz_results` | TX futures VT vs 0050.TW stock VT — futures Sharpe +0.095 but DM Harvey FAIL (t=0.216) | CONDITIONAL_PASS | complete | local |
| K847 | `app:tz`; `fig:overnight_vix` | Overnight gap decomposition — Slot B+C absorb 73.3% of gap variance; ~61% of gap tradable | (verdict not recorded) | complete | local |
| K848 | `app:tz` | TAIFEX 5-min RV construction — night session 43.3% of RV; r² noisy proxy (ratio 0.65) | (verdict not recorded) | complete | local |
| K849 | `sec:vt`; `sec:var` | HAR-RV vs GJR on TAIFEX — Track A best: HAR-RV-J (QLIKE=0.180); inconsistent across tracks | (verdict not recorded) | complete | local |
| K850 | `sec:var` | HAR-RV VaR for 0050.TW — GJR+CF champion (2 violations); HAR QLIKE better but VaR trinity FAIL | CONDITIONAL_PASS | complete | local |
| K851 | `app:tz` | Jump dynamics (BNS) — significant jumps 10.1% of days; jump share of RV 2.5%; HAR-CJ +1.23% not sig | (verdict not recorded) | complete | local |
| K852 | `sec:vt`; `sec:var` | Realized GARCH — beats GJR on QLIKE; HAR-RV QLIKE=0.101 still best overall | (verdict not recorded) | complete | local |
| K852b | `sec:vt`; `sec:var` | Regime-dependent HAR — best QLIKE 0.119; no DM Harvey-significant improvement vs HAR-RV | (verdict not recorded) | complete | local |
| K853 | `sec:vt`; `sec:var` | Proxy ceiling ablation — HAR-RV ranks 1st under all proxy conditions; proxy choice determines ranking | (verdict not recorded) | complete | local |
| K854 | `sec:var` | Common-sample VaR (fix K850 unfair comparison) — GJR+CF and RGL+CF PASS 1% VaR trinity | CONDITIONAL_PASS | complete | local |
| K886 | `sec:vt`; `tab:vt_results` | PRG on 0050.TW — PRG_Extended best QLIKE 0.7838; DM t=5.27 Harvey PASS vs GJR | (verdict not recorded) | complete | local |
| K892 | `tab:summary_stats`; `tab:gamma`; `sec:tsmc` | Canonical 0050.TW GJR gamma — γ=0.097 (full-sample), 0.080 (rolling w=2000); resolves paper conflict | PASS | complete | local |
| K896 | `sec:var`; `sec:es`; `tab:vt_results` | Expected shortfall analysis — GJR+HistSim VaR PASS + ES PASS + best Fissler-Ziegel | (verdict not recorded) | complete | local |
| K900 | `tab:vt_results`; `tab:vt_common` | Taiwan VT performance tables — GJR VT Sharpe 1.074; VIX-863 Sharpe 1.137, MDD −13.7% | (verdict not recorded) | complete | local |
| K1098 | `sec:cond_leverage`; `sec:cross_validation` | A4f with VIXTWN vs VIX — H1–H4 all FAIL; VIXTWN does not beat VIX in Taiwan context | FAIL | complete | root |
| K1145 | `sec:cross_validation` | A4f-EAV Taiwan (N=31 stocks) — placebo rejection_rate=0.0; EAV effect not attributable to chance | PASS | complete | root |
| K1147 | `sec:cross_validation` | A4f-EAV US (N=30 S&P 500) — primary t PASS, bootstrap PASS | PASS | complete | root |
| K1150 | `sec:cross_validation` | A4f-EAV Japan (N=30 TOPIX) — primary t PASS, bootstrap PASS | PASS | complete | root |
| K1175 | `tab:vt_results`; `sec:conclusion` | VT 2010–2026 canonical replication — buy-hold Sharpe diff ~9.6% from paper (period mismatch) | PARTIAL_MATCH | complete | root |
| K1176 | `app:tz`; `tab:tz_results` | Cross-market TZ momentum replication — split-corrected 0050.TW c2c Sharpe 1.915 vs legacy 1.473; canonical o2o defined as adj-open$_t$/adj-open$_{t-1}$ with 2014-01-02 split date excluded | PARTIAL_MATCH | complete | root |
| K1180 | `sec:macro`; `sec:bci_mom` | Coincident MoM strategy IS Sharpe 0.413 (paper 0.732 unreproducible — errata applied in v3 macro section); OOS Sharpe 1.2694 (paper 1.260) MATCH; BCI null t=-0.5349 (paper -0.53) MATCH; Leading MoM t=3.74 PARTIAL_MATCH | PARTIAL_MATCH | complete | root |
| K1181 | `sec:data`; `sec:vt`; `tab:sharpe_reconciliation` | VIXTWN stats + Steiger Z — ρ=0.594 matched (paper 0.595); 64-month window confirmed | PARTIAL_MATCH | complete | root |
| K1302 | `sec:data`; `tab:gamma` | Table 2 individual γ rebuild — 9+1 stocks, 100 multistart, 0 failures; all targets matched | PASS | complete | root |
| K1302b | `tab:gamma`; `sec:leverage` | γ for 5 unlisted Taiwan stocks — all 5 converged, avg γ=0.024, persistence<1 | PASS | complete | root |
| K1370 | `sec:intro`; `sec:leverage` | Bootstrap 90% CI [2.28, 6.58] for amplification ratio 4.3× (canonical BW-robust) | (verdict not recorded) | complete | root |
| K1370c | `sec:leverage` | N_start=10 vs 100 sensitivity micro-test for K1370 — PASS; N_start=10 sufficient | PASS | complete | root |

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

## Canonical Binding Status

- `main_v3.tex` imports `body_v3.tex`; pre-v3 manuscripts and 66-page table mappings are superseded.
- `body_v3.tex` documents ELITE Material (2383.TW) in `sec:data`, so the prior H2 data-description blocker is no longer a valid index issue.
- Reproduction status is governed by `reproduce.py` and `reproduce_report.json`; residual untraceable items are traceability gaps, not table-map drift.

*Updated: 2026-07-06 — platform_ops_taiwan_vt_reproduce_experiments_rebind_body_v3*
