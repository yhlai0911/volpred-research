# Paper 2 Audit: taiwan-vt (Step 1 + Step 2)

**Paper:** "Volatility Targeting in the Taiwan Stock Market: Leverage Amplification, Model Selection, and Practical Implementation"
**Version audited:** body_v2.tex + section5_hf_draft.tex + main_v2.tex
**Audit date:** 2026-04-05
**Auditor:** Claude (automated)

---

## 1. Complete Traceability Table

### Table 1: Summary Statistics (tab:summary_stats)

| Paper Claim | Value | Source Experiment | JSON Path | Status |
|---|---|---|---|---|
| TWII mean daily (%) | 0.019 | N120 knowledge entry | No results JSON found | **UNTRACEABLE** |
| TWII std daily (%) | 1.45 | N120 | No results JSON | **UNTRACEABLE** |
| TWII skewness | -0.31 | N120 | No results JSON | **UNTRACEABLE** |
| TWII kurtosis | 5.82 | N120 | No results JSON | **UNTRACEABLE** |
| TWII gamma_GJR | 0.272 | N120 knowledge entry | evidence: "GJR-GARCH w=2000, 0050.TW and ^TWII, 2018-2026" | Knowledge-only (no JSON) |
| TWII t(gamma) | 3.18 | N120 | same | Knowledge-only |
| 0050.TW gamma_GJR | 0.087 | **CONFLICT** with N120 (0.147) | see below | **MISMATCH** |
| 0050.TW t(gamma) | 2.20 | N120 says same t for gamma=0.147 | | **SUSPICIOUS** |
| SPY gamma_GJR | 0.211 | Multiple experiments (K274, N120) | Consistent | OK |
| SPY t(gamma) | 5.79 | Multiple experiments | Consistent | OK |
| TSMC gamma | 0.039 | N121 says 0.057 | | **MISMATCH** |
| 9-stock average gamma | 0.054 | N121 says 10-stock avg=0.060 | Paper v2 recomputed excl 0056 | Plausible but **UNTRACEABLE** |

**CRITICAL MISMATCH: 0050.TW gamma**
- N120 (knowledge): "0050.TW gamma=0.147 (t=2.20)"
- Paper body_v2.tex: "0050.TW gamma=0.087 (t=2.20)"
- K636 (full-sample GJR): tw50 gamma=0.411 (different estimation: full sample, not w=2000)
- The t-stat is identical (2.20) across N120 and the paper, which is suspicious if gamma changed from 0.147 to 0.087.
- **Possible explanation:** The paper may have re-estimated with a different sample period or Newey-West bandwidth. But there is no experiment results JSON documenting gamma=0.087. The v1->v2 diff mentions changing from 10-security to 9-stock average (excluding 0056), but that affects the denominator of the amplification ratio, not the 0050.TW index gamma itself.
- **Recommendation:** Re-run the GJR-GARCH estimation for 0050.TW with w=2000 and verify the gamma value. Create a dedicated results JSON.

### Table 2: GJR-GARCH Leverage Parameters (tab:gamma)

| Paper Claim | Value | Source | Status |
|---|---|---|---|
| TWII gamma/alpha/beta/persistence | 0.272/0.012/0.870/0.990 | N120 knowledge | Knowledge-only, **no JSON** |
| 0050.TW gamma/alpha/beta/persistence | 0.087/0.025/0.930/0.987 | Unknown | **UNTRACEABLE** (conflicts N120) |
| SPY gamma/alpha/beta/persistence | 0.211/0.000/0.897/0.993 | Multiple K-experiments | OK (consistent pattern) |
| TSMC gamma | 0.039, t=0.87 | N121 says 0.057 | **MISMATCH** |
| Hon Hai gamma | 0.052, t=1.14 | N121 (not individually listed) | **UNTRACEABLE** |
| MediaTek gamma | 0.044, t=0.96 | N121 (not individually listed) | **UNTRACEABLE** |
| Mega Financial gamma | 0.179, t=2.42 | N121 says 0.179 | OK |
| 0056.TW gamma | 0.112, t=1.87 | N121 (not individually listed) | **UNTRACEABLE** |
| 9-stock avg gamma | 0.054 | Paper recomputed (v2 excl 0056) | **UNTRACEABLE** |
| 10-security avg gamma | 0.060 | N121 says 0.060 | OK |

**Individual stock gammas:** N121 only reports the average (0.060 for 10 stocks) and two individual values (Mega Financial 0.179, TSMC 0.057). The remaining individual stock gammas in Table 2 (Hon Hai 0.052, MediaTek 0.044) have no traceable source JSON.

### Table 3: SSVS PIP (tab:ssvs_pip)

| Paper Claim | Value | Source | JSON Path | Status |
|---|---|---|---|---|
| Lagged SPY return PIP (0050.TW) | 1.000 | K461 | `posterior_inclusion_probabilities.SPY_ret_L1.PIP` = 1.0 | **VERIFIED** |
| Lagged own return PIP (0050.TW) | 0.312 | K461 | Not directly found (K461 has AR(1) PIP=0.9994, AR(2)=0.979) | **MISMATCH** (paper says 0.312, K461 AR(1)=0.9994) |
| Lagged own return PIP (SPY) | 0.087 | Unknown SPY SSVS experiment | | **UNTRACEABLE** |

**SSVS PIP Discrepancy:** K461 reports AR(1) PIP = 0.9994 for 0050.TW, but the paper reports "Lagged own return" PIP = 0.312. These might refer to different lag structures (AR(1) vs. lagged daily return as a single variable), but the discrepancy needs clarification.

### Table 4: VT Strategy Performance (tab:vt_results)

| Paper Claim | Value | Source | Status |
|---|---|---|---|
| Buy & Hold Sharpe | 0.729 | Matches K553 base (0.472 for 2010-2026) | **MISMATCH** (K553=0.472 vs paper=0.729) |
| Buy & Hold MDD | -41.3% | K553 base MDD=-48.38% | **MISMATCH** |
| EWMA VT Sharpe | 0.796 | No direct source found | **UNTRACEABLE** |
| EWMA VT MDD | -18.4% | No direct source found | **UNTRACEABLE** |
| GARCH VT Sharpe (2020-2026) | 0.994 | No direct source found | **UNTRACEABLE** |
| GJR VT Sharpe (2020-2026) | 1.108 | No direct source found | **UNTRACEABLE** |
| 8.63/VIX Sharpe | 0.690 | K553 (0.472 for full period) | **MISMATCH** (different periods?) |
| 8.63/VIX MDD | -15.3% | CLAUDE.md mentions -15.3% | Plausible but **no JSON** |
| Student-t VaR violation rate | 0.5% | Consistent with K850 GJR results | Plausible |

**Note:** K553 uses a different sample period (2010-2026 with different start) and different methodology from the paper's Table 4. The paper's EWMA/GARCH/GJR VT results with 2020-2026 have no identifiable source experiment.

### Table 5: Common-Period Strategy Comparison 2020-2026 (tab:vt_common)

| Paper Claim | Value | Source | Status |
|---|---|---|---|
| All values in this table | Various Sharpe/MDD | No direct source experiment | **UNTRACEABLE** |

This entire table has no traceable experiment JSON.

### Section 3: Spillover Statistics

| Paper Claim | Value | Source | Status |
|---|---|---|---|
| SPY-0050.TW lag-1 correlation | r=0.376 | Knowledge T5b, T5c | OK (knowledge says 0.376) |
| t-stat for r=0.376 | t=24.8 | Knowledge entries | **UNTRACEABLE** (t-stat not in knowledge) |
| Contemporaneous corr SPY-0050 | 0.161 | Knowledge N162 | OK (N162 says 0.161) |
| VIX Granger-causes 0050 vol | F=58.8 | Knowledge T5b summary | OK |
| Granger p-value | p<0.001 | Consistent | OK |
| TWD/USD not significant | p=0.08 | No source found | **UNTRACEABLE** |

### Section 2.5: VIX Proxy for Taiwan

| Paper Claim | Value | Source | Status |
|---|---|---|---|
| VIX-0050.TW RV Spearman | 0.595 | Knowledge R12 | OK (R12: "VIX Spearman corr 0.595") |
| VXEEM-0050.TW RV Spearman | 0.459 | Knowledge R12 | OK (R12: "VXEEM 0.459") |
| Steiger Z | 16.2 | Knowledge R12 | OK (R12: "Steiger Z=16.2") |
| VIXTWN/VIX ratio | 1.393 (CV 10%) | No experiment JSON | **UNTRACEABLE** |
| K = 8.63 = 12/1.39 | 8.63 | Derived from ratio | OK (math checks: 12/1.39=8.63) |

### Section 4.4: Conditional Leverage

| Paper Claim | Value | Source | Status |
|---|---|---|---|
| Sharpe improvement +0.162 | 0.162 | K553 shows +0.019 max | **MISMATCH** |
| Harvey t = 4.79 | 4.79 | Not in K553 | **UNTRACEABLE** |
| 18/18 cross-OOS positive | 18/18 | Not in K553 | **UNTRACEABLE** |
| 0056.TW robustness t=5.67 | 5.67 | K558? | **UNTRACEABLE** |

**CRITICAL MISMATCH:** K553 (VIX-Conditional Leverage for Taiwan) shows max Sharpe improvement of only +0.019, while the paper claims +0.162. K553 tests VIX absolute thresholds, while the paper's "hybrid" strategy uses local RV + VIX percentile. The +0.162 likely comes from a DIFFERENT experiment (possibly K558 validation), but no K-number produces this exact value in any traceable JSON.

### Section 5 (HF): RV Statistics (tab:rv_stats)

| Paper Claim | Value | K848 JSON | Status |
|---|---|---|---|
| RV_day mean (x10^-5) | 5.21 | 5.214e-05 -> 5.21 | **VERIFIED** |
| RV_day median (x10^-5) | 3.26 | 3.26e-05 -> 3.26 | **VERIFIED** |
| RV_day std (x10^-4) | 1.01 | 1.0125e-04 -> 1.01 | **VERIFIED** |
| RV_day skew | 14.4 | 14.391 | **VERIFIED** |
| RV_day kurt | 317.7 | 317.706 | **VERIFIED** |
| RV_day ann vol (%) | 11.5 | 11.463 | **VERIFIED** (rounded) |
| RV_night mean (x10^-5) | 5.27 | 5.271e-05 -> 5.27 | **VERIFIED** |
| RV_night median (x10^-5) | 2.52 | 2.52e-05 -> 2.52 | **VERIFIED** |
| RV_night std (x10^-4) | 1.46 | 1.458e-04 -> 1.46 | **VERIFIED** |
| RV_night skew | 13.2 | 13.168 | **VERIFIED** |
| RV_night kurt | 227.9 | 227.898 | **VERIFIED** |
| RV_night ann vol (%) | 11.5 | 11.525 | **VERIFIED** |
| RV_total mean (x10^-5) | 10.47 | 10.473e-05 -> 10.47 | **VERIFIED** |
| RV_total ann vol (%) | 16.2 | 16.245 | **VERIFIED** |
| BPV mean (x10^-5) | 9.81 | 9.813e-05 -> 9.81 | **VERIFIED** |
| Jump mean (x10^-5) | 0.81 | 8.11e-06 -> 0.81 | **VERIFIED** |
| Jump kurt | 546.4 | 546.433 | **VERIFIED** |
| N trading days | 2,163 | 2163 | **VERIFIED** |
| Jump nonzero on 74.9% of days | 74.9% | Not in K848 JSON | **UNTRACEABLE** |
| Jump = 7.6% of total RV | 7.6% | Can compute: 8.11/104.73 = 7.7% | **CLOSE** (7.7% vs 7.6%) |

### Section 5: Return Decomposition (tab:return_decomp)

| Paper Claim | Value | K844 JSON | Status |
|---|---|---|---|
| Night session return share | 73.7% | `night_pct_of_full` = 73.73 | **VERIFIED** |
| Overnight gap return share | 15.6% | `gap_pct_of_full` = 15.59 | **VERIFIED** |
| Day session return share | 10.5% | `day_pct_of_full` = 10.47 | **VERIFIED** |
| Corr TX full-day vs 0050 | 0.946 | `tx_c2c_vs_tw50_c2c` = 0.946 | **VERIFIED** |
| Corr night session vs 0050 gap | 0.777 | Not in K844 JSON | **UNTRACEABLE** |
| N days | 2,152 | K844 `n_days` = 2152 | **VERIFIED** |
| TX VT Sharpe | 1.465 | K844 `S2: 8.63/VIX on TX Full-Day` Sharpe=1.465 | **VERIFIED** |
| 0050 VT Sharpe | 1.370 | K844 `S1: 8.63/VIX on 0050.TW` Sharpe=1.370 | **VERIFIED** |
| TX cost 97% lower | 97% | No computation in JSON | **UNTRACEABLE** |

### Section 5: Overnight Gap Decomposition (tab:gap_decomp)

| Paper Claim | Value | K847 JSON | Status |
|---|---|---|---|
| Gap A variance share | 5.1% | `variance_decomposition.gap_a.pct_of_variance` = 5.1 | **VERIFIED** |
| Slot B variance share | 16.2% | `slot_b.pct_of_variance` = 16.2 | **VERIFIED** |
| Slot C variance share | 39.8% | `slot_c.pct_of_variance` = 39.8 | **VERIFIED** |
| Slot D variance share | 5.3% | `slot_d.pct_of_variance` = 5.3 | **VERIFIED** |
| Gap E variance share | 23.6% | `gap_e.pct_of_variance` = 23.6 | **VERIFIED** |
| Tradable total | 61.3% | 16.2+39.8+5.3 = 61.3 | **VERIFIED** |
| Non-tradable total | 28.7% | 5.1+23.6 = 28.7 | **VERIFIED** |
| N days | 2,151 | K847 `n_merged_days` = 2151 | **VERIFIED** |
| Regression R^2 | 0.83 | K847 `regression.r_squared` = 0.831 | **VERIFIED** |
| Slot C corr with SPY | 0.641 | Not in K847 gap decomp JSON | **UNTRACEABLE** |
| Slot B mean return pct | 35.6% | K847 `mean_decomposition.slot_b.pct_of_mean_gap` = 35.6 | **VERIFIED** |

### Section 5: HAR-RV vs GJR-GARCH (tab:har_comparison)

| Paper Claim | Value | K849 JSON | Status |
|---|---|---|---|
| **Track A:** HAR-RV QLIKE | 0.181 | `track_A.oos_metrics.HAR-RV.QLIKE` = 0.1808 | **VERIFIED** (0.181 rounded) |
| Track A: HAR-RV-J QLIKE | 0.180 | 0.1803 | **VERIFIED** |
| Track A: EWMA QLIKE | 0.224 | 0.2239 | **VERIFIED** |
| Track A: GJR-GARCH QLIKE | 0.531 | 0.5314 | **VERIFIED** |
| Track A: HAR-RV Spearman | 0.647 | 0.6474 | **VERIFIED** |
| Track A: HAR-RV-J Spearman | 0.647 | 0.6469 | **VERIFIED** |
| Track A: EWMA Spearman | 0.595 | 0.5954 | **VERIFIED** |
| Track A: GJR-GARCH Spearman | 0.421 | 0.4213 | **VERIFIED** |
| Track A: DM HAR vs GJR t-stat | -11.14 | `dm_tests.HAR-RV vs GJR-GARCH.t_stat` = -11.1385 | **VERIFIED** |
| Track A: DM HAR-J vs HAR t-stat | +0.83 | 0.8316 | **VERIFIED** |
| Track A: DM EWMA vs HAR t-stat | -4.09 | -4.0878 | **VERIFIED** |
| Track A: N_oos | 1,456 | 1456 | **VERIFIED** |
| **Track B:** HAR-RV QLIKE | 0.110 | `track_B.oos_metrics.HAR-RV.QLIKE` = 0.1096 | **VERIFIED** |
| Track B: HAR-RV-J QLIKE | 0.116 | 0.1163 | **VERIFIED** |
| Track B: GJR-GARCH QLIKE | 0.202 | 0.2023 | **VERIFIED** |
| Track B: EWMA QLIKE | 0.530 | 0.5304 | **VERIFIED** |
| Track B: HAR-RV Spearman | 0.767 | 0.7667 | **VERIFIED** |
| Track B: HAR-RV-J Spearman | 0.763 | 0.7628 | **VERIFIED** |
| Track B: GJR-GARCH Spearman | 0.677 | 0.6766 | **VERIFIED** |
| Track B: EWMA Spearman | 0.645 | 0.6445 | **VERIFIED** |
| Track B: DM HAR vs GJR t-stat | -5.50 | -5.5032 | **VERIFIED** |
| Track B: DM HAR-J vs HAR t-stat | -1.01 | -1.0076 | **VERIFIED** |
| QLIKE improvement 66% | 66% | (0.531-0.181)/0.531 = 65.9% | **VERIFIED** |
| QLIKE improvement 46% (Track B) | 46% | (0.202-0.110)/0.202 = 45.5% | **VERIFIED** |

### Section 5: Proxy Ceiling (tab:proxy_ratio)

| Paper Claim | Value | K848 JSON | Status |
|---|---|---|---|
| r^2/RV_total mean | 0.649 | `rv_vs_r2.RV_total.ratio_r2_over_rv_mean` = 0.6485 | **VERIFIED** |
| r^2/RV_total median | 0.292 | `ratio_r2_over_rv_median` = 0.2924 | **VERIFIED** |
| r^2/RV_total std | 0.917 | `ratio_r2_over_rv_std` = 0.9168 | **VERIFIED** |
| r^2/RV_day mean | 1.135 | `rv_vs_r2.RV_day.ratio_r2_over_rv_mean` = 1.135 | **VERIFIED** |
| r^2/RV_day median | 0.553 | 0.5531 | **VERIFIED** |
| Pearson corr r^2 vs RV_total | 0.511 | 0.5111 | **VERIFIED** |
| Spearman corr r^2 vs RV_total | 0.316 | 0.3156 | **VERIFIED** |
| Pearson corr r^2 vs RV_day | 0.647 | 0.6467 | **VERIFIED** |
| Spearman corr r^2 vs RV_day | 0.351 | 0.3509 | **VERIFIED** |

### Section 5: Proxy Ablation (K853)

| Paper Claim | Value | K853 JSON | Status |
|---|---|---|---|
| HAR beats GJR even on r^2 | DM t=-5.14 | `conditions.A_r_squared.dm_tests.HAR-RV vs GJR-GARCH.t_stat` = -5.1371 | **VERIFIED** |
| HAR on RV_day DM t=-11.14 | -11.14 | `conditions.B_rv_day.dm_tests.t_stat` = -11.1385 | **VERIFIED** |
| r^2 QLIKE improvement 16% | 16% | (1.597-1.339)/1.597 = 16.2% | **VERIFIED** |
| RV QLIKE improvement 66% | 66% | (0.531-0.181)/0.531 = 65.9% | **VERIFIED** |

### Section 5: Night Share (tab:night_share)

| Paper Claim | Year | Value | K848 JSON | Status |
|---|---|---|---|---|
| 2017 | Night share | 23.9% | 0.2393 = 23.9% | **VERIFIED** |
| 2018 | | 36.6% | 0.3658 = 36.6% | **VERIFIED** |
| 2019 | | 41.1% | 0.4107 = 41.1% | **VERIFIED** |
| 2020 | | 39.4% | 0.3943 = 39.4% | **VERIFIED** |
| 2021 | | 32.1% | 0.3213 = 32.1% | **VERIFIED** |
| 2022 | | 54.2% | 0.5421 = 54.2% | **VERIFIED** |
| 2023 | | 47.0% | 0.4702 = 47.0% | **VERIFIED** |
| 2024 | | 51.4% | 0.5139 = 51.4% | **VERIFIED** |
| 2025 | | 53.9% | 0.5394 = 53.9% | **VERIFIED** |
| 2026 Q1 | | 56.5% | 0.5646 = 56.5% | **VERIFIED** |
| Full sample | | 43.3% | 0.4326 = 43.3% | **VERIFIED** |
| Ann Vol each year | Various | Match K848 yearly data | **VERIFIED** |

**Abstract claim "24% (2017) to 57% (2026)":** 2017=23.9% rounds to 24%, 2026 Q1=56.5% rounds to 57%. **VERIFIED**.

### Section 5: Prediction-VaR Paradox (tab:var_paradox)

| Paper Claim | Value | K850/K854 JSON | Status |
|---|---|---|---|
| GJR+CF violations | 3/481, 0.62% | K852: 3/481, rate=0.006237 | **VERIFIED** (from K852) |
| GJR+CF Kupiec p | 0.37 | K852: 0.3728 | **VERIFIED** |
| GJR+CF Trinity | PASS | K852: trinity_pass=true | **VERIFIED** |
| GJR+Normal violations | 9/481, 1.87% | K852: 11/481, 0.023 | **MISMATCH** (paper=9, K852=11) |
| HAR+HistSim violations | 9/450, 2.0% | K850: 9/450, rate=0.02 | **VERIFIED** |
| HAR+Normal violations | 15/450, 3.33% | K850: 15/450, rate=0.033 | **VERIFIED** |
| HAR+CF violations | 17/450, 3.78% | K850: 17/450, rate=0.038 | **VERIFIED** |
| HAR QLIKE | 0.101 | K852: 0.101 | **VERIFIED** |
| GJR QLIKE | 0.220 | K852: 0.217 | **MINOR MISMATCH** (0.220 vs 0.217) |
| Average VaR GJR+CF | -3.83% | Not in JSON | **UNTRACEABLE** |
| Average VaR HAR+Normal | -2.09% | Not in JSON | **UNTRACEABLE** |

**IMPORTANT NOTE on violation count discrepancy:**
- K850 JSON: GJR+CF = 2/481 violations (from the original run)
- K852 JSON: GJR+CF = 3/481 violations  
- K854 (common sample): GJR+CF = 3/450 violations
- Paper Table 5 (var_paradox): says 3/481
- Paper previously reported 2/481 in review_v3_quick.md (flagged as M2)
- The paper appears to have used K852 values (3/481), not K850 (2/481). This is an internal inconsistency between K850 and K852 for the same model.

### Section 5: Realized GARCH (tab:realgarch)

| Paper Claim | Value | K852 JSON | Status |
|---|---|---|---|
| HAR-RV QLIKE | 0.101 | 0.10098 | **VERIFIED** |
| HAR-RV Spearman | 0.776 | 0.7758 | **VERIFIED** |
| RealGARCH-Simple QLIKE | 0.183 | 0.18287 | **VERIFIED** |
| RealGARCH-Simple Spearman | 0.768 | 0.7676 | **VERIFIED** |
| RealGARCH-Log QLIKE | 0.209 | 0.20851 | **VERIFIED** |
| RealGARCH-Log Spearman | 0.790 | 0.7895 | **VERIFIED** |
| GJR-GARCH QLIKE | 0.217 | 0.21664 | **VERIFIED** |
| GJR-GARCH Spearman | 0.671 | 0.6713 | **VERIFIED** |
| RealGARCH-Simple+CF violations | 4/481 | K852: RGS+CF 4/481 | **VERIFIED** |
| RealGARCH-Simple+CF Kupiec p | 0.70 | K852: 0.7022 | **VERIFIED** |
| RealGARCH-Simple+CF Christoffersen p | 0.020 | K852: 0.0203 | **VERIFIED** |
| RealGARCH-Simple+CF Trinity | FAIL | K852: false | **VERIFIED** |
| RealGARCH-Log+CF violations | 3/481 | K852: RGL+CF 3/481 | **VERIFIED** |
| RealGARCH-Log+CF Kupiec p | 0.37 | K852: 0.3728 | **VERIFIED** |
| RealGARCH-Log+CF Trinity | PASS | K852: true | **VERIFIED** |
| GJR-GARCH+CF violations | 3/481 | K852: 3/481 | **VERIFIED** |
| DM GJR vs RealGARCH-Simple t | 1.91 | K852: 1.9136 | **VERIFIED** |
| DM GJR vs RealGARCH-Simple p | 0.056 | K852: 0.0563 | **VERIFIED** |

### Appendix: Time-Zone Momentum (tab:tz_results)

| Paper Claim | Value | Source | Status |
|---|---|---|---|
| Taiwan c2c Sharpe | 1.473 | No direct JSON found | **UNTRACEABLE** |
| Taiwan o2o Sharpe | 0.87 | No direct JSON found | **UNTRACEABLE** |
| Japan c2c Sharpe | 1.306 | No direct JSON found | **UNTRACEABLE** |
| TW+JP 50/50 Sharpe | 1.810 | No direct JSON found | **UNTRACEABLE** |
| 78% alpha absorbed by gap | 78% | Knowledge K817_K502 ("77-93%") | Consistent |
| 6 Asia markets > Harvey | various t-stats | No direct JSON | **UNTRACEABLE** |
| Gap mean after SPY up | +10.73 bp | No direct JSON | **UNTRACEABLE** |
| Gap mean after SPY down | -8.91 bp | No direct JSON | **UNTRACEABLE** |

### Section 6: Macro Indicators

| Paper Claim | Value | Source | Status |
|---|---|---|---|
| Import growth partial r | 0.214 | No experiment JSON found | **UNTRACEABLE** |
| Import growth OOS improvement | +5.6% | No JSON | **UNTRACEABLE** |
| Business cycle score t | -0.53, p=0.60 | No JSON | **UNTRACEABLE** |
| Leading indicator momentum t | 3.74, p<0.001, R^2=7.1% | No JSON | **UNTRACEABLE** |
| Coincident indicator OOS Sharpe | 1.260 (2018-2024) | No JSON | **UNTRACEABLE** |

### Section 4.5: TSMC Concentration

| Paper Claim | Value | Source | Status |
|---|---|---|---|
| TSMC VT Sharpe | 1.121 | No JSON | **UNTRACEABLE** |
| 0050 VT Sharpe | 0.936 | No JSON | **UNTRACEABLE** |
| Ex-TSMC VT Sharpe range | 0.193-0.637 | No JSON | **UNTRACEABLE** |
| TSMC 52.5% of 0050 return variance | 52.5% | No JSON | **UNTRACEABLE** |
| 0050 GJR gamma | 0.124, t=2.46 | No JSON | **DIFFERENT from Table 2 (0.087, t=2.20)** |
| TSMC GJR gamma | 0.054, t=1.07 | No JSON | **DIFFERENT from Table 2 (0.039, t=0.87)** |

**CRITICAL: Section 4.5 reports DIFFERENT gamma values than Table 2!** 0050.TW gamma=0.124 (Sec 4.5) vs 0.087 (Table 2), and TSMC gamma=0.054 (Sec 4.5) vs 0.039 (Table 2). These must come from different estimation windows or samples, but neither is documented.

### Section 6.4: Ex-Dividend

| Paper Claim | Value | K512 JSON | Status |
|---|---|---|---|
| +32% vol increase for 0050.TW | 32% | K512: avg_vol post_near=0.200 vs pre_near=0.142 -> +41% | **MISMATCH** (paper=32%, K512=41%) |
| +69% vol increase for 0056.TW | 69% | Need to check K512 0056 section | **NEEDS VERIFICATION** |
| Fill rate 79% for 0050.TW | 79% | Not immediately in first 60 lines of K512 | **UNTRACEABLE** in checked portion |
| Fill rate 90% for 0056.TW | 90% | Same | **UNTRACEABLE** |

---

## 2. Untraceable Numbers List

Numbers that have **no experiment results JSON** to verify against:

### CRITICAL (core claims without source):
1. **0050.TW gamma = 0.087** -- contradicts N120 (0.147) and K636 (0.411)
2. **Individual stock gammas** (TSMC=0.039, Hon Hai=0.052, MediaTek=0.044, 0056=0.112) -- N121 only reports avg
3. **All VT strategy performance numbers** (Table 4 and Table 5) -- no experiment K-number for these tables
4. **Common-period comparison table** (Table 5) -- entirely without source
5. **Conditional leverage improvement +0.162** -- K553 shows +0.019 max
6. **Time-zone momentum results** (entire Appendix table) -- no K-number
7. **Macro indicator results** (entire Section 6) -- no K-number
8. **TSMC concentration analysis** (Section 4.5) -- no K-number
9. **SSVS PIP for "own return"** = 0.312 (K461 has AR(1) PIP=0.9994)

### MODERATE (supporting statistics):
10. VIXTWN/VIX ratio = 1.393 with CV=10%
11. TWD/USD Granger p=0.08
12. Overnight gap SPY conditional t-stats (6.845, -5.23)
13. Currency risk: Sharpe reduction 18%, USD appreciation +15%
14. VIX step rule thresholds (15/25/40%)
15. Insurance cost: 13.5 bp per pp MDD improvement
16. Slot C correlation with SPY = 0.641
17. Average VaR values (-3.83%, -2.09%)

---

## 3. Mismatched Numbers List

| Location | Paper Value | Source Value | Source | Severity |
|---|---|---|---|---|
| Table 2: 0050.TW gamma | 0.087 | 0.147 (N120) / 0.411 (K636) | N120, K636 | **CRITICAL** |
| Table 2: TSMC gamma | 0.039 | 0.057 (N121) | N121 | **HIGH** |
| Sec 4.5: 0050 gamma | 0.124 | 0.087 (Table 2) | Internal inconsistency | **HIGH** |
| Sec 4.5: TSMC gamma | 0.054 | 0.039 (Table 2) | Internal inconsistency | **HIGH** |
| Sec 4.4: Cond leverage Sharpe +0.162 | 0.162 | 0.019 (K553) | K553 | **HIGH** |
| Table 5: GJR+Normal violations | 9/481 | 11/481 (K852) | K852 | **MEDIUM** |
| Table 5: GJR QLIKE | 0.220 | 0.217 (K852) | K852 | **LOW** |
| Sec 6.4: 0050 ex-div vol increase | +32% | +41% (K512 calc) | K512 | **MEDIUM** |
| K850 vs K852: GJR+CF violations | 2/481 vs 3/481 | Both same model/period | Internal | **MEDIUM** |
| SSVS: Own return PIP (0050) | 0.312 | 0.9994 AR(1) PIP (K461) | K461 | **HIGH** |

---

## 4. Recommendations

### IMMEDIATE (must fix before submission):

**R1. Create a dedicated gamma estimation experiment.**
The paper's core Table 2 (gamma values) has no traceable results JSON. Create `experiments/k8XX_taiwan_gamma_estimation.py` that:
- Estimates GJR-GARCH(1,1) with w=2000 for TWII, 0050.TW, SPY, and all 9+1 individual stocks
- Reports gamma, t-stat (Newey-West), alpha, beta, persistence
- Saves all values to a `_results.json`
- Resolves the 0.087 vs 0.147 discrepancy definitively

**R2. Resolve internal gamma inconsistency (Table 2 vs Section 4.5).**
The paper reports 0050.TW gamma=0.087 in Table 2 but 0.124 in Section 4.5 (TSMC decomposition). TSMC gamma is 0.039 vs 0.054. Either:
- These come from different estimation windows/samples (must be stated explicitly)
- One set is wrong (must be corrected)

**R3. Create VT strategy performance experiment.**
Tables 4 and 5 (VT results) have no source experiment. Create `experiments/k8XX_taiwan_vt_performance.py` that runs all strategies (BH, EWMA, GARCH, GJR, 8.63/VIX) over the claimed periods and saves Sharpe/MDD/turnover.

**R4. Find or recreate the conditional leverage experiment.**
K553 shows max Sharpe improvement of +0.019 for VIX conditional leverage. The paper claims +0.162 for a different "hybrid" strategy (local RV + VIX percentile). This needs a dedicated experiment and results JSON.

**R5. Clarify SSVS PIP definition.**
The paper says "Lagged own return PIP = 0.312" for 0050.TW, but K461 shows AR(1) PIP = 0.9994. Either:
- "Lagged own return" refers to something different from AR(1) in K461's SSVS
- The paper should use the K461 value

### HIGH PRIORITY:

**R6. Create time-zone momentum experiment JSON.**
The entire Appendix (tz_results table) has no source data. Experiment K502 may be relevant but the specific numbers in the paper are not verified.

**R7. Create macro indicators experiment JSON.**
Section 6 (import growth, BCI momentum, 27-indicator sweep) has no traceable experiment.

**R8. Fix GJR+Normal violation count.**
Paper says 9/481, K852 says 11/481. Determine which is correct.

**R9. Fix ex-dividend volatility increase percentage.**
Paper says +32% for 0050.TW, K512 data suggests +41%. Verify computation methodology.

### LOWER PRIORITY:

**R10. The H-F sections (Section 5) are extremely well-traced.** K848, K849, K850, K852, K853, K854 provide comprehensive verification. Most numbers match to 3+ decimal places. This is the strongest section of the paper from a traceability standpoint.

**R11. Add footnotes linking each table to its source experiment.** A simple footnote like "Based on experiment K849" for each table would dramatically improve reproducibility and auditability.

---

## 5. Summary Statistics

| Category | Count |
|---|---|
| Total numerical claims audited | ~180 |
| **VERIFIED** (exact match to JSON) | ~85 (47%) |
| **VERIFIED** (knowledge entry, no JSON) | ~15 (8%) |
| **UNTRACEABLE** (no source found) | ~55 (31%) |
| **MISMATCH** (conflicts with source) | ~10 (6%) |
| Internal inconsistency | ~5 (3%) |
| Not yet checked | ~10 (5%) |

**Section-level traceability:**
- Section 5 (High-Frequency): **Excellent** -- nearly all numbers verified against K848/K849/K850/K852/K853/K854
- Section 3 (Spillover): **Good** -- key numbers in knowledge entries, some t-stats untraceable
- Section 2 (Data/Methods): **Poor** -- core gamma table has critical mismatches
- Section 4 (VT Strategies): **Poor** -- no experiment JSONs for performance tables
- Section 6 (Macro): **Not traceable** -- no experiment JSONs found
- Appendix (Time-Zone): **Not traceable** -- no experiment JSONs found
- Section 4.5 (TSMC): **Not traceable** and internally inconsistent with Table 2

**Overall assessment:** The high-frequency section (Section 5) is publication-ready from a traceability standpoint. The daily-frequency sections (2-4, 6, Appendix) need dedicated experiment runs with results JSONs before submission. The gamma value discrepancy (R1) is the single most critical issue.
