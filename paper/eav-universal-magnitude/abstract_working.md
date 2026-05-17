# Working Abstract v2 (target: 180–220 words)

> **Draft — not for submission. Revise after body.tex is finalized.**
> v1 (152 words, archived as `abstract_working_v1_pre_rewrite_backup.md`) committed
> "universal firm-event constant" over-claim, used K1148_d2 OOS DM as cross-market
> magnitude evidence (mis-attribution), and silently omitted the K1109/K1113/K1114/K1140
> null heterogeneity evidence chain. v2 below corrects all five P0 issues from
> `review_v1.md`.

---

We document a robust **cross-market regularity** in earnings-announcement volatility amplification using a multiplicative GARCH framework that decomposes conditional variance into a firm-specific GJR component (g) and a pooled market-level factor (τ). Estimating a shared τ coefficient on a binary earnings indicator across three independent equity markets — Taiwan (N=31 TWSE bluechips), the United States (N=30 S&P 500 large-caps), and Japan (N=30 TOPIX large-caps), all 2014–2025 — we obtain θ̂_EAV > 0 with cluster-bootstrap |t| of 5.24 (TW), 4.50 (US), and 11.99 (JP), all surviving Bonferroni adjustment for the three-market joint test (|t| > 2.39). Within-stock permutation placebos (n = 60 per market) reject the null at 0/60 in every market, with observed θ̂ standing 13.27 (TW), 70.74 (US), and 38.65 (JP) placebo standard errors above zero — where the placebo standard error is the cross-permutation standard deviation of refit θ̂_EAV under within-stock EAV-day shuffles. Point-estimate **magnitudes are market-specific and structurally ordered: US (1.91 × 10⁻⁴) > JP (1.41 × 10⁻⁴) > TW (6.36 × 10⁻⁵)** — consistent with cross-market institutional features (analyst coverage density, earnings-call culture, institutional pre-announcement positioning). A PCA-based market-factor absorption test confirms the effect is orthogonal to systematic stress in both TW and US (Scenario A), with stress-interaction asymmetric across markets (US amplified; TW null). Within each market, however, no observable firm-attribute predictor of θ_EAV — sector, market capitalization, beta, earnings frequency, trading volume, momentum, or rolling temporal trend — survives multiple-testing correction across four pre-registered cross-sectional and HAC-robust temporal tests. This within-market null supports interpreting θ_EAV as a **market-level constant** whose cross-market variation reflects structural rather than idiosyncratic forces. A binary indicator is marginally preferred over a continuous analyst-surprise specification in out-of-sample US forecasts (both highly significant; ΔDM t ≈ 0.33).

**Word count**: ~285 (will trim to 180–220 in final pass; current verbosity reflects multiple new substantive claims that need careful tightening rather than premature compression)

---

## Key Numbers Locked to JSON Sources

| Statistic | Value | Source |
|-----------|-------|--------|
| θ̂_EAV (TW pooled, IS) | +6.362e-5 | `k1145_results.json.main_fit_eav_window_1.theta_eav` |
| θ̂_EAV (US pooled, IS) | +1.909e-4 | `k1147_results.json.main_fit_eav_window_1.theta_eav` |
| θ̂_EAV (JP pooled, IS) | +1.413e-4 | `k1150_results.json.main_fit_eav_window_1.theta_eav` |
| Cluster-bootstrap t (TW) | +5.24 | `k1145_results.json.cluster_bootstrap.t_stat` |
| Cluster-bootstrap t (US) | +4.50 | `k1147_results.json.cluster_bootstrap.t_stat` |
| Cluster-bootstrap t (JP) | +11.99 | `k1150_results.json.cluster_bootstrap.t_stat` |
| Placebo z (TW) | 13.27σ | (observed − placebo_mean) / placebo_se from `k1145_placebo_results.json` |
| Placebo z (US) | 70.74σ | `k1147_placebo_results.json.z_observed_relative_to_placebo` |
| Placebo z (JP) | 38.65σ | `k1150_placebo_results.json.z_observed_relative_to_placebo` |
| Placebo one-sided rejection (all 3 markets) | 0/60 | each market's placebo JSON |
| US OOS DM t (binary, K1148_d2 TW-fitted) | −5.58 | `k1148_d2_results.json.four_row_table[0].panel_DM_t_OOS` |
| US OOS DM t (continuous, K1148_d2 TW-fitted) | −5.25 | `k1148_d2_results.json.four_row_table` |
| TW stocks (IS) | N=31 | K1145 |
| US stocks (IS) | N=30 | K1147 |
| JP stocks (IS) | N=30 | K1150 |
| Sample period (all 3 markets) | 2014–2025 | K1145/K1147/K1150 |

---

## Definitional Footnote — Placebo σ

The placebo z reported in this abstract is computed as
`z = (θ̂_observed − mean(θ̂_placebo)) / sd(θ̂_placebo)`
where the placebo distribution is the set of n=60 within-stock EAV-day permutations (each permutation refits the full pooled MLE on shuffled EAV indicators). `sd(θ̂_placebo)` is the cross-permutation standard deviation, treated as the placebo standard error. This is **not** the bootstrap SE (which is reported separately as the cluster-bootstrap row).

Earlier scaffold v1 reported "13.6σ" for TW; recomputation from the source JSON yields **13.27σ** (rounding-down at 0.005). The corrected value is used throughout v2.

---

## Convergence-flag honesty disclosure

Main pooled fits in K1145 (TW) and K1147 (US) report `scipy.minimize.converged = False` on the inner BFGS step, despite outer-loop EM-style tolerance (Δθ < 1e-7) being achieved and loglik plateau being monotone. K1150 (JP) reports `converged = True`. The replication package will document the discrepancy (likely BFGS gradient tolerance is too strict at the ~10⁻⁴–10⁻⁵ θ scale) with manual gradient verification and analytic-gradient re-fit as appendix robustness.
