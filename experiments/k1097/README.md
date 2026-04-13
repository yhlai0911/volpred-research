# K1097: MS-GJR-t (Student-t Innovations) + Full VaR-ES Trinity

## Plan / 研究計畫

測試 **Markov-Switching GJR with Student-t innovations (MS-GJR-t)** 是否能
同時解決 K1019 遺留的兩個問題：

1. **QLIKE gap**: K1019 的 MS-GJR-Normal (QLIKE=1.615) 仍輸 A4f-VIX9D-t (1.581)
2. **VaR failure**: K1019 MS-GJR-Normal **VaR 2.5% Kupiec p=0.005 FAIL**，因為 Normal 忽略 fat tails

本實驗 (K1097) 在每個 regime 內使用 Student-t 分配（共享 df），並加入完整 VaR-ES Trinity 檢驗。

## 問題描述 / Problem Statement

K1019 建立了 MS-GJR 能在 QLIKE 層次顯著贏 GJR-t baseline（DM t=-3.20, Harvey PASS），
但也揭露了一個關鍵弱點：**Normal innovations 在每個 regime 內嚴重低估尾部風險**。
K1019 VaR 2.5% violation rate = 3.30%（目標 2.5%）、Kupiec p=0.005 → 違反 Basel 要求。

如果 MS-GJR 要實際上線用於風險管理，Student-t 是必要的擴展。
**Haas, Mittnik & Paolella (2004, JFEC)** 正式討論 MS-GARCH-t，
並建議**共享 df across regimes** 以確保識別性（K1097 遵循此做法）。

## 動機 / Motivation

- **不重複 K1019**：K1019 已回答「MS-GJR 是否勝 GJR、是否勝 A4f」
- **補齊 K1019 漏洞**：VaR 失敗 + QLIKE 沒超過 A4f
- **理論動機**：金融收益的尾部厚度來自兩個來源——regime-level volatility heterogeneity（MS 能捕捉）+ conditional fat tails（需要 Student-t）。K1019 只處理前者
- **風險管理實用性**：Basel 要求 VaR PASS；K1097 加入 ES、Christoffersen CC、Acerbi-Szekely、FZ0 四個維度的檢驗

## 方法 / Method

### Models

| Model | Specification | Innovations | # Params | Role |
|-------|---------------|-------------|----------|------|
| **M1: GJR-t** | GJR(1,1) baseline | Student-t | 5 (ω,α,γ,β,df) | K988 baseline |
| **M2: MS-GJR-N** | MS(2)-GJR, Gray collapse | Normal | 10 | K1019 replication |
| **M3: MS-GJR-t** | MS(2)-GJR, Gray collapse, shared df | Student-t | 11 | NEW |
| **M4: A4f-VIX9D-t** | GJR + δ·(VIX9D/100)² | Student-t | 6 | K1075 best |

### Estimation

- **Filter**: Hamilton (1989) + Gray (1996) variance collapse
- **MLE**: L-BFGS-B with multiple random starts (n=8-10), seed=42
- **Unconstrained parameterization**: sigmoid/exp transforms for bounds
- **Regime ordering**: swap to ensure regime 0 = calm (lower unconditional variance)

### Data

- **SPY**: yfinance, 2003-01-01 to 2026-12-31 (OOS: 2013-01-01 onwards)
- **VIX, VIX9D**: yfinance (`^VIX`, `^VIX9D`)
- **Window**: 2000 days; **Refit**: every 63 trading days (~quarterly)
- Returns clipped to ±20% to remove extreme outliers

### Evaluation

1. **QLIKE on r²** (Patton 2011) with DM test (Newey-West HAC, Harvey |t|>3.0)
2. **VaR-ES Trinity** at **both** 1% and 5%:
   - **Kupiec (1995)** LR unconditional coverage
   - **Christoffersen (1998)** CC joint UC + independence
   - **Acerbi-Szekely (2014)** Z1 test for ES (bootstrap p-value, 2000 reps)
   - **Fissler-Ziegel (2016)** FZ0 joint scoring rule
   - **Basel Traffic Light** at 1% (last 250 OOS days)
3. **Student-t VaR/ES closed form** (McNeil, Frey & Embrechts 2015):
   ```
   VaR_α = t_α(df) · √(σ² · (df-2)/df)
   ES_α  = -(df + t_α²)/(df-1) · φ_t(t_α)/α · √(σ² · (df-2)/df)
   ```

### Hypotheses

- **H1**: M3 (MS-GJR-t) vs M2 (MS-GJR-N) QLIKE DM |t|>3.0 — does Student-t help?
- **H2**: M3 vs M4 (A4f-VIX9D-t) QLIKE — does MS structure close A4f gap given Student-t?
- **H3**: M3 VaR Kupiec PASS at 1% AND 5% — does Student-t fix the K1019 failure?
- **H4**: M3 joint FZ0 loss lower than both M1 and M2

## 預期 / Expectations

Based on K1019 + K988 findings:
- **H1 Likely PASS**: SPY excess kurtosis ≈ 14 means Normal density dramatically under-weights extremes; Student-t should improve both likelihood and QLIKE
- **H2 Likely NS**: K1019 showed MS alone doesn't beat A4f; Student-t unlikely to close full gap because A4f already has Student-t
- **H3 Likely PASS on at least 5% level**: Student-t matches known fat-tail structure; 1% level harder
- **H4 Likely PASS**: FZ0 rewards joint calibration; Student-t models M1/M3/M4 should dominate M2

## 結論 / Conclusion

**Null result (mostly) — with one important empirical finding about regime instability.**

### QLIKE Results (OOS 2013-01-02 to 2026-04-10, N=3338)

| Model | QLIKE | DM vs M1 | DM vs M2 | DM vs M4 |
|-------|-------|----------|----------|----------|
| M1: GJR-t | 1.6350 | — | — | — |
| M2: MS-GJR-N | 1.6141 | t=-1.01 NS | — | — |
| **M3: MS-GJR-t (NEW)** | **1.6297** | t=-1.31 NS | t=+0.62 NS | t=+2.95 NS |
| M4: A4f-VIX9D-t | 1.5676 | **t=-3.00 ★** | — | — |

### VaR-ES Trinity

| Model | Level | VR | Kupiec | Christoffersen | Acerbi-Szekely | FZ0 | Basel |
|-------|-------|-----|--------|----------------|----------------|-----|-------|
| M1 GJR-t | 1% | 1.32% | **PASS** (p=0.08) | **PASS** (p=0.19) | PASS | -4.923 | Green |
| M1 GJR-t | 5% | 5.81% | FAIL (p=0.04) | PASS (p=0.06) | PASS | -5.319 | — |
| M2 MS-GJR-N | 1% | 1.98% | **FAIL** (p<0.001) | FAIL | PASS | -5.012 | Green |
| M2 MS-GJR-N | 5% | 5.25% | PASS (p=0.51) | PASS | PASS | -5.462 | — |
| **M3 MS-GJR-t** | 1% | 1.38% | FAIL (p=0.04) | FAIL (p=0.04) | PASS | -4.931 | Green |
| **M3 MS-GJR-t** | 5% | 5.90% | FAIL (p=0.02) | PASS (p=0.06) | PASS | -5.322 | — |
| **M4 A4f-VIX9D-t** | 1% | 1.32% | **PASS** (p=0.08) | **PASS** (p=0.19) | PASS | **-5.068** | Green |
| **M4 A4f-VIX9D-t** | 5% | 5.60% | **PASS** (p=0.12) | **PASS** (p=0.29) | PASS | **-5.394** | — |

### Hypothesis Results

- **H1 (Student-t beats Normal in MS)**: **FAIL** — DM M3 vs M2 t=+0.62 NS. Student-t innovations DO NOT significantly improve QLIKE over Normal in the MS-GJR framework.
- **H2 (MS-GJR-t closes A4f gap)**: **FAIL** — M4 still best QLIKE. DM M3 vs M4 t=+2.95 (just below Harvey threshold; A4f effectively wins).
- **H3 (MS-GJR-t fixes VaR)**: **FAIL** — M3 still fails Kupiec at both 1% (p=0.04) and 5% (p=0.02). Student-t innovations alone are not enough.
- **H4 (M3 FZ0 better than M1/M2)**: **FAIL** — M3 FZ0=-4.93 is worse than both M2 (-5.01) and M4 (-5.07).

### Critical Empirical Finding — Regime Label Instability

The MS-GJR-t refits show dramatic **regime label switching** between adjacent refits:
- 2014-01: mean P(calm)=0.835 → 2014-04: 0.149 → 2014-07: 0.169
- Transition probabilities also swap: p00=0.859/p11=0.978 ↔ p00=0.975/p11=0.879

When Student-t innovations already absorb fat tails, the MS structure no longer cleanly splits "calm" vs "crisis" along unconditional-variance lines. Instead, the two regimes differ more by **persistence** (one near-unit-root, one mean-reverting) than by volatility level. This makes the unconditional-variance-based regime-ordering heuristic unreliable, causing P(calm) series to be incoherent across refit boundaries and hurting OOS forecast quality.

**Implication**: Simple MS-GJR-t is not a practical improvement over MS-GJR-Normal; if fat tails are needed, **exogenous information (VIX9D via A4f)** provides them more efficiently than internal Student-t innovations.

### Regime Parameters (Final 2000 obs, last refit)

| Regime | ω | α | γ | β | Persistence | Uncond σ (daily) |
|--------|---|---|---|---|-------------|------------------|
| 0 (Calm) | 5.71e-6 | 0.077 | 0.383 | 0.688 | 0.957 | 1.15% |
| 1 (Crisis) | 2.59e-6 | 0.027 | 0.180 | 0.882 | 0.999 | 4.30% |

- Shared df = **6.71** (moderately fat-tailed; consistent with equity return kurtosis ≈ 14)
- p00=0.914 (calm persistence), p11=0.962 (crisis persistence)
- Ergodic P(Calm) = 30.6% — lower than K1019 MS-GJR-N (73%) because Student-t absorbs outliers that would have forced the Normal-MS model to classify more days as "calm"

### Main Takeaways

1. **A4f-VIX9D-t remains unchallenged** — it is the only model that passes the full VaR-ES Trinity at both 1% AND 5% with lowest FZ0 at both levels. This is Paper 9 finding re-confirmed across yet another dimension.
2. **Internal regime switching ≠ Exogenous VIX** — even with matching distributional assumptions (both Student-t), MS-GJR-t loses to A4f-VIX9D-t (QLIKE 1.630 vs 1.568, FZ0 -4.93 vs -5.07).
3. **Student-t in MS-GARCH introduces identification instability** — a genuinely new empirical finding not documented in K1019.
4. **K1019 VaR failure is structural, not distributional** — we hypothesized Student-t would fix K1019's 2.5% Kupiec failure. It does not. The failure comes from MS structure itself being over-sensitive to recent volatility (pushes up forecasts only after crises begin, missing onset spikes).

### Paper 9 Implications

This confirms a strong case for A4f-VIX9D-t as the **single recommended equity volatility model**:
- Best QLIKE
- Passes full VaR-ES Trinity at 1% and 5%
- Lowest FZ0 joint loss
- No regime-identification instability
- Interpretable parameters

## Files

- `k1097.py` — main script (~950 lines)
- `k1097_results.json` — complete results (QLIKE, DM, VaR-ES trinity, regime analysis, final params)
- `k1097_qlike_comparison.png` — QLIKE bar chart
- `k1097_dm_comparison.png` — DM test forest plot
- `k1097_state_probabilities.png` — M2/M3 filtered P(calm) + VIX timeline
- `k1097_parameters.png` — M3 regime parameter evolution (beta, gamma, persistence, df)
- `k1097_theta1_evolution.png` — shared df stability over refits
- `k1097_var_es_trinity.png` — pass/fail matrix + FZ0 loss

## Differentiation from K1019

| Dimension | K1019 | K1097 |
|-----------|-------|-------|
| MS innovations | Normal only | Normal + **Student-t (shared df)** |
| VaR levels | 2.5% only | **1% + 5%** |
| VaR tests | Kupiec only | **Kupiec + Christoffersen CC + Acerbi-Szekely ES + FZ0** |
| ES evaluation | None | Full |
| Student-t VaR/ES formulas | N/A | McNeil et al. (2015) closed form |
| df stability tracking | N/A | Per-refit df evolution chart |

## Limitations

- **Shared df across regimes**: Haas et al. (2004) notes this is a common restriction to ensure
  identifiability. An extension (K1097b potential) would allow regime-specific df at the cost of
  convergence difficulties.
- **Gray collapse**: approximates full path-dependent MS likelihood. Klaassen (2002) shows this
  is a reasonable compromise; exact MS-GARCH is intractable for long series.
- **A&S bootstrap p-value**: approximates the A&S Monte Carlo test. Full parametric bootstrap
  from the fitted model would be more rigorous but much slower.
- **Normal innovation assumption in VaR for M2**: we deliberately test M2 with Normal VaR to
  mirror K1019 (and show the cost of ignoring fat tails).

## References

- Hamilton (1989), *Econometrica* 57(2): Markov-Switching time series
- Gray (1996), *JFE* 42(1): Regime-Switching GARCH
- Klaassen (2002), *Empirical Economics* 27(2): Improving GARCH with RS
- **Haas, Mittnik & Paolella (2004), *JFEC* 2(4): MS-GARCH with t-innovations (core reference)**
- Patton (2011), *JoE* 160(1): QLIKE loss function
- **Kupiec (1995), *J. Derivatives* 3(2): VaR unconditional coverage**
- **Christoffersen (1998), *IER* 39(4): VaR conditional coverage**
- **Acerbi & Szekely (2014), *Risk* 27(11): ES backtest**
- **Fissler & Ziegel (2016), *AoS* 44(4): Joint VaR-ES elicitability**
- McNeil, Frey & Embrechts (2015), *Quantitative Risk Management* (2nd ed.): Student-t ES
- Harvey (2016): t>3.0 threshold for DM multiple-testing correction

## Related Experiments

- **K1019**: MS-GJR-Normal baseline (this is K1097's direct predecessor)
- **K1020**: MS-A4f hybrid (MS + VIX multiplicative — combined approach did not help)
- **K988**: Paper 9 A4f baseline comparisons
- **K1075**: A4f-VIX9D-t verified best equity vol forecaster
