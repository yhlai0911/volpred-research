# Results Index — Paper 2: Volatility Targeting in Taiwan

All result JSONs are stored alongside their scripts in `paper/taiwan-vt/experiments/`
and the root `experiments/` directory. **Relative paths point to the canonical JSON.**

Verdict legend: PASS / CONDITIONAL_PASS / NULL / FAIL / (verdict not recorded)

---

## Section 2: Data and Methodology

| Experiment | Result JSON | 1-Line Verdict |
|------------|-------------|----------------|
| K892 | [`../experiments/k892_verify_tw_gamma_results.json`](../experiments/k892_verify_tw_gamma_results.json) | 0050.TW canonical γ=0.097 (full-sample), 0.080 (rolling w=2000); resolves paper conflict — PASS |
| K1302 | `../../experiments/k1302/k1302_results.json` | Table 2 individual-stock γ rebuilt, 100 multistart, 0 fail — overall_pass=True |
| K1302b | `../../experiments/k1302b/k1302b_results.json` | 5 unlisted stocks: all 5 converged, avg γ=0.024, persistence <1 — success_criteria met |
| K1181 | `../../experiments/k1181/k1181_results.json` | VIX–RV correlation ρ=0.594 matched (paper 0.595); VIXTWN ratio 1.39 confirmed — PARTIAL_MATCH |

---

## Section 3: The Leverage Effect in the Taiwan Market

| Experiment | Result JSON | 1-Line Verdict |
|------------|-------------|----------------|
| K1370 | `../../experiments/k1370/k1370_results.json` | Bootstrap 90% CI [2.28, 6.58] for amplification ratio 4.3× (canonical BW-robust) — (verdict not recorded) |
| K1370c | `../../experiments/k1370c/k1370c_results.json` | N_start=10 vs 100 sensitivity: PASS — N_start=10 sufficient |
| K636 | `../../experiments/k636/k636_results.json` | Amplification 4.6× (γ ratio TAIEX/stock); reconciles K530 vs K633 — (verdict not recorded) |
| K461 | [`../experiments/k461_ssvs_taiwan_results.json`](../experiments/k461_ssvs_taiwan_results.json) | SSVS selects SPY_ret_L1 PIP=1.0, VIX_level PIP=0.801; confirms US–Taiwan cross-market spillover — CONDITIONAL_PASS |

---

## Section 4: Volatility Targeting Strategies for Taiwan

| Experiment | Result JSON | 1-Line Verdict |
|------------|-------------|----------------|
| K1175 | `../../experiments/k1175/k1175_results.json` | Table 3 canonical replication: buy-hold Sharpe ≈9.6% diff from paper (period mismatch) — APPROX |
| K900 | [`../experiments/k900_taiwan_vt_performance_results.json`](../experiments/k900_taiwan_vt_performance_results.json) | GJR VT Sharpe 1.074; VIX-863 Sharpe 1.137, MDD −13.7%; VaR trinity pass — (verdict not recorded) |
| K886 | [`../experiments/k886_prg_0050tw_results.json`](../experiments/k886_prg_0050tw_results.json) | PRG_Extended best QLIKE 0.7838; DM t=5.27 Harvey PASS vs GJR — (verdict not recorded) |
| K472 | `../../experiments/k472/k472_taiwan_comprehensive_results.json` | EWMA / HAR / semivariance all ≈ GJR (DM p>0.05); no significant improvement — CONDITIONAL_PASS |
| K553 | [`../experiments/k553_leveraged_vt_taiwan_results.json`](../experiments/k553_leveraged_vt_taiwan_results.json) | Hybrid RV+Pctile lev=1.5 best variant (+0.248 Sharpe); Taiwan adaptation SUCCEEDS (Harvey t>3.0) — PASS |
| K558 | [`../experiments/k558_k553_taiwan_validation_results.json`](../experiments/k558_k553_taiwan_validation_results.json) | 11/11 validation gates PASS; all cross-OOS, sensitivity, tx-cost, drawdown checks clear — PASS |
| K1098 | `../../experiments/k1098/k1098_results.json` | A4f with VIXTWN: H1–H4 all FAIL; VIXTWN does not beat VIX in Taiwan context — FAIL |
| K896 | [`../experiments/k896_taiwan_es_supplement_results.json`](../experiments/k896_taiwan_es_supplement_results.json) | GJR+HistSim: VaR trinity PASS + ES PASS + best Fissler-Ziegel; GJR+Student-t also passes — (verdict not recorded) |

---

## Section 5: Earnings Announcement Volatility (A4f-EAV)

| Experiment | Result JSON | 1-Line Verdict |
|------------|-------------|----------------|
| K1145 | `../../experiments/k1145/k1145_placebo_results.json` | Taiwan EAV placebo rejection_rate=0.0; θ_EAV=6.36e-5 not attributable to chance — PASS |
| K1147 | `../../experiments/k1147/k1147_results.json` | US A4f-EAV pooled panel: primary t PASS, bootstrap PASS — PASS |
| K1150 | `../../experiments/k1150/k1150_results.json` | Japan A4f-EAV pooled panel: primary t PASS, bootstrap PASS — PASS |
| K512 | `../../experiments/k512/k512_tw_exdividend_results.json` | Ex-div vol not elevated (0.1418 vs 0.1511 control, no sig diff); ex-div return spike confirmed — NULL |

---

## Section 5 (High-Frequency): TAIFEX Tick Evidence

| Experiment | Result JSON | 1-Line Verdict |
|------------|-------------|----------------|
| K848 | [`../experiments/k848_taifex_5min_rv_results.json`](../experiments/k848_taifex_5min_rv_results.json) | Night session 43.3% of RV; r² noisy proxy (ratio 0.65 vs ideal ~1) — (verdict not recorded) |
| K847 | [`../experiments/k847_overnight_gap_decomposition_results.json`](../experiments/k847_overnight_gap_decomposition_results.json) | Slot B+C (post-open) absorb 73.3% of overnight gap variance; ~61% gap tradable — (verdict not recorded) |
| K849 | [`../experiments/k849_har_rv_taifex_results.json`](../experiments/k849_har_rv_taifex_results.json) | Track A best: HAR-RV-J (QLIKE=0.180); Track B best: HAR-RV (0.110); inconsistent across tracks — (verdict not recorded) |
| K851 | [`../experiments/k851_results.json`](../experiments/k851_results.json) | BNS jumps on 10.1% of days; jump contribution 2.5% of RV; HAR-CJ improvement 1.23%, not Harvey-significant — (verdict not recorded) |
| K852 | [`../experiments/k852_realized_garch_results.json`](../experiments/k852_realized_garch_results.json) | RealGARCH beats GJR on QLIKE (PASS); HAR-RV QLIKE=0.101 still best — (verdict not recorded) |
| K852b | [`../experiments/k852b_results.json`](../experiments/k852b_results.json) | Regime-HAR: best QLIKE 0.119; no DM Harvey-significant improvement vs HAR-RV — (verdict not recorded) |
| K853 | [`../experiments/k853_proxy_ablation_results.json`](../experiments/k853_proxy_ablation_results.json) | HAR-RV ranks 1st under all proxy conditions (A–D); proxy choice explains 100% of HAR vs GJR ranking — (verdict not recorded) |
| K844 | [`../experiments/k844_futures_vs_stock_vt_results.json`](../experiments/k844_futures_vs_stock_vt_results.json) | TX futures Sharpe 1.465 vs stock 1.370 (+0.095); DM Harvey FAIL (t=0.216) — CONDITIONAL_PASS |

---

## Section 6: VaR and Risk Management

| Experiment | Result JSON | 1-Line Verdict |
|------------|-------------|----------------|
| K850 | [`../experiments/k850_har_rv_var_taiwan_results.json`](../experiments/k850_har_rv_var_taiwan_results.json) | GJR+CF champion at 1% VaR (2 violations); HAR-RV QLIKE +54% but VaR trinity FAIL — CONDITIONAL_PASS |
| K854 | [`../experiments/k854_common_sample_var_results.json`](../experiments/k854_common_sample_var_results.json) | Common sample (450 days): GJR+CF and RGL+CF PASS 1% VaR trinity; HAR methods FAIL — CONDITIONAL_PASS |
| K896 | [`../experiments/k896_taiwan_es_supplement_results.json`](../experiments/k896_taiwan_es_supplement_results.json) | GJR+HistSim: VaR PASS + ES PASS + best Fissler-Ziegel score — (verdict not recorded) |

---

## Section 8: Discussion

| Experiment | Result JSON | 1-Line Verdict |
|------------|-------------|----------------|
| K1370 | `../../experiments/k1370/k1370_results.json` | Amplification 90% CI [2.28, 6.58]; point estimate 4.3× (this run) — (verdict not recorded) |
| K1302 | `../../experiments/k1302/k1302_results.json` | TSMC γ provenance confirmed; all Table 2 targets matched — PASS |

---

## Appendix: Time-Zone Information Transmission

| Experiment | Result JSON | 1-Line Verdict |
|------------|-------------|----------------|
| K1176 | `../../experiments/k1176/k1176_results.json` | PARTIAL_MATCH — c2c Sharpe 1.92 vs paper 1.47 (split-correction divergence; recommendation: add data provenance note) |

---

## Summary Counts

- Total result JSONs: 27 unique experiments (17 local + 10 root)
- PASS: 5 (K553, K558, K1145, K1147, K1150, K1302)
- CONDITIONAL_PASS: 4 (K461, K472, K844, K850, K854)
- NULL: 1 (K512)
- FAIL: 1 (K1098)
- PARTIAL_MATCH / APPROX: 2 (K1175, K1176, K1181)
- verdict not recorded: 13 (K636, K847, K848, K849, K851, K852, K852b, K853, K886, K896, K900, K1302b, K1370)

*Generated: 2026-05-26 — do not edit manually; update via task paper_taiwan_vt_self_contained*
