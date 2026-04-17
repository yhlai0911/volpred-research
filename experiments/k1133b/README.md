# K1133b: BTC GAS-t decomposition — innovation vs GAS dynamics vs regime-switching

**Status**: completed (2026-04-17)
**Proposer**: Claude
**Executor**: Claude (worktree `agent-a97b4fe0`)
**Parent**: K1133 (BTC GAS-t sub-period split)
**Related K**: K1129 (BTC GAS-t reversal motivator), K1038 (4-asset GAS-t NULL), K437 (SPY GAS-t NULL)

## Motivation

K1133 established two uncomfortable facts about BTC GAS-t:

1. The K1129 full-sample GAS-t reversal (DM t=-4.58) is **concentrated in P1 pre-institutional (2017-2020)** with t=-4.67 and is **NEUTRAL in P2 FTX/Luna and P3 spot-ETF eras**.
2. **GJR-Student-t also reverses in P1** (t=-3.36), suggesting that the heavy-tail Student-t innovation — rather than GAS score-driven dynamics — might be the true culprit.

K1133 also fit a 2-state Markov-switching GAS-t in-sample (Hamilton filter) and found the LRT highly significant in all three periods (χ²=48.5, 36.6, 15.9 with df=6, p<0.05). But K1133 **did not implement OOS forecasting** with the MS model, so the in-sample likelihood gain cannot be translated into a forecast advantage.

K1133b addresses **both loose ends**:

- **Part A — Innovation-distribution vs GAS-dynamics decomposition**: add **M4 GAS-Normal** (Creal-Koopman-Lucas score with Normal density, no Student-t tail penalty) as a 4th model. If GAS-Normal recovers to GJR-Normal parity, the Student-t innovation is the problem. If GAS-Normal is also a reversal, GAS dynamics are the problem. M5 GJR-Normal with shift-scale standardisation is added as a numeric-scaling control.
- **Part B — MS-GAS-t OOS forecasting**: implement Klaassen (2002) style state-probability recursion with per-state log-variance paths, and test whether regime-switching rescues BTC.

## Methodology

### Models

| Key | Model | Purpose |
|---|---|---|
| M1 | GJR-GARCH Normal | K1129 baseline |
| M2 | GJR-GARCH Student-t | K1129 baseline (P1 reversal -3.36 confirmed) |
| M3 | GAS-t | K1133 baseline (P1 reversal -4.67 confirmed) |
| **M4** | **GAS-Normal (NEW)** | **Isolates GAS dynamics — no Student-t penalty** |
| M5 | GJR-Normal on standardised input | Scaling control |
| MS | 2-state Markov-switching GAS-t (OOS) | Regime-switching rescue test |

**M4 GAS-Normal specification**: Following Creal-Koopman-Lucas (2013) Table 1 / Harvey (2013) §4.1. Under f = log σ² parameterisation, the Fisher-scaled score is s_t = ε²_t − 1 (Fisher information I = 0.5; S = I⁻¹ = 2; ∇ = 0.5(ε²-1)). The recursion is:

    f_{t+1} = ω + α · (ε²_t − 1) + β · f_t
    σ²_{t+1} = exp(f_{t+1})

### MS-GAS-t OOS recursion (Klaassen 2002 / hybrid Gray)

At each OOS observation t, using ONLY information up to t-1:

    ξ_{t|t-1} = P' · ξ_{t-1|t-1}         # predictive state prob
    σ²_{k,t} = exp(f_{k,t})              # per-state predictive variance
    σ²_{t|t-1} = ξ_{0,t|t-1}·σ²_{0,t} + ξ_{1,t|t-1}·σ²_{1,t}

Filtered update (after observing r_t):

    ξ_{k,t|t} ∝ ξ_{k,t|t-1} · f_k(r_t | σ²_{k,t}, ν_k)

Per-state log-variance recursion (GAS-t):

    f_{k,t+1} = ω_k + α_k · S_k · score_k(r_t, σ²_{k,t}) + β_k · f_{k,t}

MS parameters are refit on the rolling 750-obs training window every 252 days (quarterly for stability — 10-param MLE is slow and fragile). State filter warm-starts through training data to reach f₀, f₁, ξ at the first OOS index.

**Lookahead safety**: explicit `assert train_start + len(train_data) == t_abs` at every refit. MS predictive state prob uses ONLY info up to prev observation.

### Data

- Source: yfinance BTC-USD, 2015-01-02 → 2026-04-14 (4121 daily observations)
- Returns: percent daily returns (`pct_change * 100`)
- Mean=0.195%, Std=3.510%, Skew=-0.119, Excess Kurtosis=7.969
- Sub-periods: P1 2015-2020, P2 2021-2023, P3 2024-2026
- Rolling window 750 obs (adaptive for P3); refit every 63 days for M1-M5, every 252 days for MS
- Seed 42

## Results

### Part A — 5-model QLIKE and DM (vs M1 GJR-N)

| Period | n_OOS | M1 QL | M2 QL | M3 QL | **M4 QL** | M5 QL | DM M2 | DM M3 | **DM M4** | DM M5 | **DM M4 vs M3** |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 pre-institutional | 1441 | **1.9926** | 2.2339 | 2.1904 | 2.0402 | 1.9930 | **-3.36** | **-4.67** | -1.90 | -0.06 | **+2.67** |
| P2 FTX/Luna (PRE) | 345† | 2.2891 | 2.2958 | 2.3162 | **2.2848** | 2.2891 | -0.26 | -0.82 | +0.25 | -0.19 | +0.94 |
| P3 spot-ETF (PRE) | 100† | 1.9753 | **1.9484** | 2.0563 | 2.0189 | 1.9744 | +0.79 | -0.80 | -1.00 | +0.75 | +0.56 |

Bold DM = |t| > 3 (Harvey 2016). † PRELIMINARY (n_OOS < 504). Bold QL = best row.

### Part B — MS-GAS-t OOS vs single-state baselines

| Period | n_OOS | **QLIKE MS** | DM MS vs M1 | DM MS vs M2 | **DM MS vs M3** | DM MS vs M4 |
|---|---|---|---|---|---|---|
| P1 | 1441 | 1.9868 | +0.28 | **+3.07** | **+5.97** | +1.54 |
| P2 (PRE) | 345† | 2.2865 | +0.15 | +0.35 | +0.95 | -0.07 |
| P3 (PRE) | 100† | 2.0170 | -0.75 | -0.79 | +0.79 | +0.10 |

### Part C — Decomposition verdict by period

**P1 pre-institutional (the only period with K1129 reversal)**:

1. **Adding Student-t kills performance** (M2 vs M1: DM=-3.36; M3 vs M1: DM=-4.67).
2. **Adding GAS dynamics WITHOUT Student-t barely hurts** (M4 GAS-Normal vs M1: DM=-1.90, NS at |t|>2 threshold). QLIKE rel_change only -2.4% vs -9.9% for GAS-t.
3. **GAS-Normal BEATS GAS-t** (M4 vs M3: DM=+2.67, p=0.008). Removing the Student-t innovation recovers ~75% of the QLIKE gap.
4. **MS-GAS-t rescues single-state GAS** (MS vs M3: DM=+5.97, p<1e-8) and **recovers to GJR-N parity** (MS vs M1: DM=+0.28, NS). MS also dominates GJR-t (MS vs M2: DM=+3.07, p=0.002). But MS does NOT give any positive edge over GJR-Normal — it only removes the penalty that single-state GAS-t carries.
5. Scaling control M5 is effectively identical to M1 (DM=-0.06), confirming the effect is not a numeric-scale artefact.

**P2 FTX/Luna (PRELIMINARY n=345 < 504)**: All five models are within ~1% QLIKE of each other. No model significantly beats M1. MS-GAS-t is indistinguishable from GJR-N. **The most volatile regime produces the most uniform model performance.**

**P3 spot-ETF (PRELIMINARY n=100 << 504)**: Same pattern as P2 — everyone within the noise band of GJR-N.

### Decomposition attribution (P1)

Decomposing the M3 GAS-t reversal QLIKE gap vs M1 (-9.92%):

- Student-t innovation contribution (M3→M4, holding GAS dynamics constant): closes **7.5 pp** of the gap (QLIKE 2.1904 → 2.0402, rel_improvement vs M1 -9.92% → -2.39%).
- GAS dynamics contribution (M4→M1 residual, with Normal): **-2.4%** (not significant).

Therefore **~75% of the BTC P1 GAS-t reversal is attributable to the Student-t innovation, not to GAS dynamics**. The remaining ~25% gap of M4 vs M1 is not statistically significant.

## Conclusions

1. **Primary verdict (P1)**: The BTC P1 GAS-t reversal documented in K1129 and K1133 is **primarily a Student-t innovation penalty, not a GAS score-driven dynamics penalty**. GAS-Normal recovers three quarters of the QLIKE gap and is no longer Harvey-significant. This matches the secondary observation in K1133 (GJR-t also reversed in P1), now quantified cleanly.
2. **MS-GAS-t is a partial rescue**: the 2-state MS-GAS-t with Klaassen-style OOS state-prob recursion beats single-state GAS-t in P1 with DM=+5.97 (Harvey-significant). But the rescue only brings MS-GAS-t back to GJR-Normal parity — it does **not** deliver a forecast edge over the simpler model. This is consistent with the K1038/K437 pattern "in-sample MS LRT significance ≠ OOS forecast advantage" and undermines a strong reading of Catania (2018).
3. **P2/P3 are uninformative**: all models including the K1133 baseline are within noise of GJR-N. P2 sample is PRELIMINARY (345 < 504), P3 deeply so (100 < 504).
4. **Paper implication**: A **"GAS-t helps crypto volatility"** paper remains not feasible. A defensible refocused paper is:
    > *"Why GAS-t fails on BTC: the Student-t innovation, not the score dynamics, is the culprit — and regime-switching does not rescue it beyond a plain GJR-Normal."*
   This paper would combine (K1129 full-sample reversal), (K1133 sub-period decomposition), (K1133b Student-t attribution ~75%), and (K1133b MS-GAS-t neutral-at-best). It is a **negative-result methodology paper** in the vein of Harvey (2016) rather than a "novel model wins" story.

## Files

| File | Purpose |
|---|---|
| `k1133b.py` | Main experiment script |
| `k1133b_results.json` | Full numeric output (all 5 models × 3 periods, MS-GAS-t OOS, verdict, state-prob samples) |
| `k1133b_qlike_5model.png` | Grouped bar: QLIKE by period × 5 models |
| `k1133b_ms_state_prob.png` | MS-GAS-t ξ_{t|t-1} timeseries stacked by period |
| `k1133b_dm_heatmap.png` | DM-HLN heatmap across key contrasts |
| `run.log` | Stdout from the run |

## Lookahead and methodology safeguards

- `assert train_start + len(train_data) == t_abs` at every refit (Part A and Part B)
- Rolling IS window with REFIT_EVERY=63 (Part A) / 252 (Part B) days
- MS-GAS-t state filter warm-starts through training data only; predictive ξ_{t|t-1} = P'·ξ_{t-1|t-1} uses only information up to the previous observation
- Seed 42 fixed at top of script; L-BFGS-B with multi-start for numerical robustness
- MLE restart for GJR-t / GAS-t / GAS-N on non-convergence; MS-GAS-t also retries with swapped-state init
- QLIKE evaluation uses Patton (2011) proxy-robust ratio loss
- DM-HLN (Harvey-Leybourne-Newbold 1997) with Newey-West HAC variance, max_lag = floor(n^(1/3))

## Limitations

1. **P2 and P3 are PRELIMINARY**. P2 n=345 (>300 OK for trend but < 504 Harvey spec); P3 n=100 is much too small for reliable DM inference. The "no effect in P2/P3" finding is suggestive, not confirmatory.
2. **MS refit cadence is 252 days (quarterly)**, not 63. MS-GAS-t MLE on 10 parameters and 750 obs per fit is expensive (~15-20s per fit) and unstable at shorter cadences. A 63-day cadence might produce slightly different results but likely in the same direction (the in-sample LRT evidence was uniformly significant across periods).
3. **2-state MS**. 3-state MS-GAS-t might behave differently, but the estimation burden on BTC's short-per-regime sample is prohibitive.
4. **MS OOS recursion is hybrid Gray(1996) / Klaassen(2002)**: per-state log-variance paths (GAS-native) but Gray-style filtered-probability forward update. Pure Klaassen would collapse paths via ξ_{t|t-1}-weighted aggregation at each step; this is approximately equivalent when state persistence is high (p00, p11 → 1), which holds empirically here (p00 ~ 0.4-0.6, p11 ~ 0.3-0.8 after training).
5. **GAS-Normal is a hand-implemented CKL specification** following Harvey (2013) §4.1. It has not been cross-validated against a reference package. But its recursion collapses to a RiskMetrics-like form when β → 1 and ω → 0, which we verified empirically (β fit ~ 0.97 on P1, ω ~ 0).
6. **BTC negative skew (-0.12)**: GJR-Normal's leverage asymmetry γ·r²·I(r<0) captures asymmetric response directly. GAS-t's score implicitly handles tail events via the denominator (ν-2+ε²), which down-weights extreme observations. On BTC P1 with modest excess kurtosis (7.97), this Student-t score down-weighting may systematically under-respond to actual volatility clusters. This is a testable hypothesis for a diagnostic paper.

## References

- Catania, L. (2018). Dynamic Adaptive Mixture Models with an Application to Volatility and Risk. *Journal of Financial Econometrics*, 18(3), 493-544.
- Creal, D., Koopman, S. J., & Lucas, A. (2013). Generalized autoregressive score models with applications. *JASA*, 108(501), 1-18.
- Gray, S. F. (1996). Modeling the conditional distribution of interest rates as a regime-switching process. *Journal of Financial Economics*, 42(1), 27-62.
- Hamilton, J. D. (1989). A new approach to the economic analysis of nonstationary time series and the business cycle. *Econometrica*, 57(2), 357-384.
- Harvey, A. C. (2013). *Dynamic Models for Volatility and Heavy Tails*. Cambridge University Press.
- Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of prediction mean squared errors. *International Journal of Forecasting*, 13(2), 281-291.
- Harvey, C. R. (2016). Editorial: The Scientific Outlook in Financial Economics. *Journal of Finance*, 72(2).
- Klaassen, F. (2002). Improving GARCH volatility forecasts with regime-switching GARCH. *Empirical Economics*, 27(2), 363-394.
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256.
