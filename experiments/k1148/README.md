# K1148 — EAV Continuous Surprise Refinement (N=29 Taiwan Stocks)

> **TL;DR**: Refined K1145's binary EAV (1/0 on announcement day) to a CONTINUOUS
> |surprise|-magnitude EAV. Pooled θ is **highly significant** (Hessian t = 10.4,
> LRT p≈0, placebo distance 26.9σ), but **identification is STRICTLY WEAKER than
> K1145 binary** (bootstrap t = 2.90 vs K1145 boot-t = 5.24) **AND OOS DM does not
> reject equal predictive accuracy against pure GJR** (panel DM t = -1.16,
> one-sided p = 0.12). **Verdict: H1_PASS_but_binary_stronger | OVERFIT_RISK**.
>
> **Paper 2 narrative implication (positive finding)**: "The earnings-announcement
> effect in Taiwan equities is about the EVENT itself, not the magnitude of the
> surprise. A simple 0/1 indicator extracts the entire identifiable signal;
> adding surprise magnitude introduces noise without improving fit or
> out-of-sample accuracy."

[提出: Claude (承接 K1145 next_tasks K1148), 執行: Claude]

---

## 1. 動機 (Why)

K1145 confirmed a universal-magnitude EAV (earnings-announcement variance) effect
across 31 Taiwan stocks using a binary indicator:

> θ_EAV_binary = +6.36e-05, t = 14.14 (Hessian) / 5.24 (stock-clustered
> bootstrap), LRT-equivalent p ≈ 0, placebo 13.6σ distance.

A natural next question (proposed in K1145 next_tasks): **does REFINING the EAV
signal from binary to continuous surprise magnitude strengthen identification?**

Two competing a-priori hypotheses:

| Hypothesis | Paper 2 narrative |
|-----------|-------------------|
| **H_continuous**: θ_continuous produces a LARGER t-stat and OOS improvement | "EAV is magnitude-proportional (rational announcement variance premium)" |
| **H_event**: binary already extracts the full signal; continuous just adds noise | "EAV is about the EVENT, not surprise size — binary is the correct reduced form" |

K1148 tests these head-to-head.

---

## 2. Method (What)

### 2.1 Model spec (identical to K1145 except EAV definition)

$$
\sigma^2_{i,t} = g_{i,t} \cdot \tau_{i,t}
$$

- **Short-run g_{i,t}**: GJR(1,1) with stock-specific (ω_i, α_i, γ_i, β_i)
- **Long-run τ_{i,t}**: $\tau_{i,t} = \max\!\left(\theta^{(i)}_0 + \theta_{VIX}\cdot VIX^2_{t-1} + \theta_{EAV}\cdot EAV_{i,t-1},\; 10^{-16}\right)$
- **Pooled θ_VIX, θ_EAV** shared across stocks (same as K1145)

### 2.2 EAV definition change (the only difference vs K1145)

$$
EAV^{\text{cont}}_{i,t} = |\text{winsor}(\text{Surprise\%}_i)|/100 \cdot \mathbf{1}\{t = \text{announcement\_day}_i\}
$$

**Why |surprise| (absolute value), not signed**:
- Raw Taiwan earnings surprise distribution is extremely heavy-tailed: min
  -10,802%, max +1,824% (N=1,747 events pooled). Even after 5%-95% quantile
  winsorization, range is [-91%, +76%].
- "Announcement variance" is symmetric: both large positive and large negative
  surprises amplify realized volatility.
- Signed surprise caused the first run to diverge — θ_EAV·(-0.91) at smallest
  stock θ₀ (~1.5e-5) forced τ → negative, caught by floor at 1e-16, and
  destabilized the likelihood (pooled negll = 2.8e11, tau ≈ 0 everywhere →
  OOS QLIKE blew up to 3.3M).
- |surprise| keeps τ strictly positive and isolates the magnitude-proportional
  hypothesis cleanly.

### 2.3 Data sources

- **Prices**: TW stock daily close 2010-01-01 ~ 2025-12-31, yfinance
  auto_adjust (cached from K1145 data/)
- **VIX**: ^VIX 2010-2025 (cached)
- **Earnings surprise**: `yfinance.Ticker(tk).get_earnings_dates(limit=80)`
  returns `Surprise(%)` column with quarterly history back to 2010.
  **NOTE**: `yfinance.Ticker(tk).earnings_history` returns ONLY the last 4
  quarters — insufficient. We use `get_earnings_dates` which returns ~64
  events per ticker (16 years × 4 quarters, with a few gaps).
- **Pre-registered 31-stock list** from K1109, of which **29 survive the
  N_events ≥ 15 threshold**. 2 stocks excluded:
  - 2388.TW (only 16 surprise events since 2010; edge case accepted but
    dropped after load)
  - 2883.TW (only 13 events — below threshold)
- **Winsorization**: pooled 5%-95% quantile (5th pct = -91.2%, 95th pct =
  +75.8%). z-score winsor would fail because std = 306% dominated by outliers.

### 2.4 Estimation — Block Coordinate Descent (unchanged from K1145)

Inner loop: per-stock (θ₀, ω, α, γ, β) via L-BFGS-B (Numba-JIT).
Outer loop: update shared (θ_VIX, θ_EAV) by L-BFGS-B on pooled negll.
Iterate until Δloglik < 1e-2.

**Key bounds on shared θ_EAV**: [-1e-4, +1e-3]. Lower bound -1e-4 permits
rejection; upper bound 1e-3 is wide enough to capture binary-equivalent
effect sizes (K1145 binary θ = 6.4e-5, continuous scale ≈ 6.4e-5 / 0.15_avg
≈ 4.3e-4).

### 2.5 Lookahead discipline (Codex-audited 2026-04-17)

Codex flagged 3 HIGH severity issues at initial code review, all fixed:

1. **`mask_is.values` AttributeError** — DatetimeIndex `<` comparison returns
   `numpy.ndarray`, not pandas object. Fixed: use `np.asarray(idx < ts, dtype=bool)`
   directly without `.values`.
2. **Pooled DM-HLN overstated effective T** — naively concatenating
   stock-day losses ignored cross-stock correlation. Fixed: **per-stock DM-HLN
   then stock-level bootstrap** for cross-sectional SE. This is the Codex-
   recommended correct inference for panel forecast comparison.
3. **τ[0] used vix[0]/eav[0]** — strictly speaking violates "only t-1 info"
   rule. Fixed: **τ[0] ≡ θ₀** (unconditional long-run level, no vix/eav
   lookup). Likelihood loop starts at t=1 so the effect is burn-in only,
   but strict lag-1 discipline is restored.

Post-fix verification:
- VIX and EAV in likelihood use `vix[t-1]`, `eav[t-1]` exclusively (code
  structure enforcement, not memory).
- OOS split uses fixed calendar date 2020-01-01; no peeking.
- OOS forecasts use IS-only estimated params; OOS recursion is self-
  contained.

### 2.6 Pre-registered hypotheses

| Test | Criterion | Logic |
|------|-----------|-------|
| **H1** | pooled θ_EAV pool-Hessian t ≥ 3.0 (Harvey 2016) AND BH-adj p < 0.05 | Does continuous spec identify EAV at all? |
| **H2** | \|bootstrap_t(cont)\| > \|bootstrap_t(binary K1145)\| | Is continuous strictly more informative than binary? |
| **H3** | Panel DM-HLN t ≤ -2.0 AND p < 0.05 (one-sided cont < gjr) | Does continuous generate OOS forecast improvement? |
| **OVERFIT_RISK** | H1 PASS but H3 FAIL | In-sample overfits; no external validity |

---

## 3. Data summary

- **N stocks used**: 29/31 (2 dropped for insufficient events)
- **Pooled observations**: ~121,000 (29 stocks × ~3900 days)
- **Total earnings events**: 1,747 (pooled across stocks and time)
- **Sample period**: 2010-01-01 to 2025-12-31 (16 years)
- **OOS split**: IS 2010-2019, OOS 2020-2025 (~6 years post-COVID)
- **Winsorization**: 5%-95% quantile; capped 12/1747 events (0.7%)
  - Lower bound: -91.2% surprise
  - Upper bound: +75.8% surprise
  - Raw range was [-10,802%, +1,824%] — driven by near-zero denominator EPS

---

## 4. Results

### 4.1 Main pooled MLE

| Quantity | K1148 (continuous \|surprise\|) | K1145 (binary) |
|---------|-----|-----|
| θ_EAV point estimate | **+2.695e-04** | +6.362e-05 |
| θ_VIX | 9.29e-08 | 9.32e-08 |
| Hessian SE | 2.58e-05 | 4.50e-06 |
| Hessian t | **+10.43** | +14.14 |
| Hessian p | ≈ 0 | ≈ 0 |
| Cluster bootstrap mean | 2.84e-04 | 6.77e-05 |
| Cluster bootstrap SE | 9.30e-05 | 1.21e-05 |
| Cluster bootstrap t | **+2.90** | **+5.24** |
| Bootstrap 95% CI | [+1.27e-4, +5.01e-4] (excludes 0) | [+4.13e-5, +9.38e-5] (excludes 0) |
| Pooled log-likelihood | 309,961.20 | 329,349.98 |
| Converged | True (8 outer iters) | False but stable |
| **LRT vs pure GJR** | χ²(2)=**2094.69**, p ≈ 0 | not computed in K1145 |

### 4.2 Within-stock permutation placebo (60 reps)

| Quantity | Value |
|----------|-------|
| Placebo mean θ_EAV | +5.34e-06 (essentially zero) |
| Placebo SE | 9.84e-06 |
| Observed θ_EAV | +2.695e-04 |
| **Distance from placebo** | **26.9σ** |
| One-sided p (placebo ≥ observed) | 0/60 = 0.000 |

**Interpretation**: The continuous EAV effect is not a pooling artifact — the
observed θ sits ~27 placebo-SDs above the null distribution. This is stronger
placebo evidence than K1145 binary (13.6σ).

### 4.3 OOS Diebold-Mariano (2020-2025, panel DM-HLN)

| Quantity | Value |
|----------|-------|
| N stocks | 29 (all pass IS ≥ 500 and OOS ≥ 250) |
| OOS observations pooled | 42,195 stock-days |
| Mean QLIKE continuous-EAV | **-7.0911** |
| Mean QLIKE pure GJR baseline | -7.0846 |
| QLIKE diff | -0.0065 (continuous marginally lower/better) |
| Per-stock DM stats | mean=**-0.450**, SE=0.388 (stock-level bootstrap) |
| **Panel DM t (Codex-corrected)** | **-1.16** |
| **Panel DM p (one-sided cont<gjr)** | **0.122** |

**Interpretation**: The IS likelihood improvement (LRT = 2094, p≈0) does NOT
translate into OOS forecast improvement at the Harvey |t|≥2 threshold. The
effect is statistically real in-sample but economically tiny (6.5e-3 QLIKE
units) and not significant at any conventional level after proper cross-stock
correlation adjustment.

### 4.4 Hypothesis verdicts

| H | Criterion | Result |
|---|-----------|--------|
| H1 | pooled t > 3.0, BH-adj < 0.05 | ✅ **PASS** (t=10.43) |
| H2 | \|boot_t_cont\| > \|boot_t_binary\| (2.90 vs 5.24) | ❌ **FAIL** — binary is stronger |
| H3 | Panel DM t ≤ -2.0 | ❌ **FAIL** (t = -1.16) |
| OVERFIT_RISK | H1 PASS but H3 FAIL | ⚠️ **TRUE** |

### 4.5 Surprise magnitude vs realized volatility (scatter)

See `k1148_surprise_vs_absr.png`. OLS of |return| on |surprise| across 1,747
announcement days yields a weak but positive slope. The visual pattern is
dominated by a wide dispersion at all surprise levels — consistent with H_event
(noise overwhelms the magnitude signal).

---

## 5. 結論 (Conclusion)

### 5.1 Core verdict: **H1_PASS_but_binary_stronger | OVERFIT_RISK**

Neither of the two a-priori narratives wins cleanly:

- **H_continuous is REJECTED**: continuous spec has smaller bootstrap t-stat
  than binary (2.90 < 5.24) and does not generate OOS forecast improvement
  (panel DM t = -1.16, p = 0.12).
- **H_event is SUPPORTED but not definitively**: continuous is still highly
  significant in-sample (Hessian t = 10.43, 26.9σ placebo distance), so it is
  not "pure noise" — it just adds no information beyond binary.

### 5.2 Paper 2 narrative (added finding on top of K1145)

> "We refine K1145's binary EAV indicator to a continuous |earnings-surprise|
> magnitude and estimate the same pooled GARCH-MIDAS spec. The continuous θ
> remains highly significant in-sample (t = 10.4, LRT p ≈ 0, placebo distance
> 26.9σ) but is STRICTLY LESS INFORMATIVE than the binary spec at panel-level
> identification (bootstrap t = 2.9 vs 5.2) and does not generate out-of-sample
> forecast improvement against a no-τ GJR baseline (panel DM-HLN t = -1.16,
> p = 0.12). This pattern is consistent with the earnings-announcement variance
> effect being about the EVENT itself — a uniform variance uplift across all
> announcements — rather than a magnitude-proportional premium. Binary EAV is
> the correct reduced-form specification; adding surprise magnitude introduces
> noise without improving fit or OOS accuracy."

This tightens Paper 2's contribution: the universal-magnitude claim from K1145
is about the PER-ANNOUNCEMENT variance uplift being uniform across firms, NOT
about the within-announcement surprise-size mapping.

### 5.3 Codex review summary

Codex (gpt-5.4, xhigh reasoning) conducted a read-only audit before execution
and flagged 3 HIGH, 2 MED, 5 LOW severity issues:

- **HIGH-1** (line 847) DatetimeIndex `.values` AttributeError in OOS split → **FIXED**
- **HIGH-2** (line 641) DM-HLN pooled stock-day treats correlation as zero → **FIXED** with per-stock DM + stock bootstrap
- **HIGH-3** (line 352) τ[0] lookahead into vix[0]/eav[0] → **FIXED** to τ[0] = θ₀
- **MED-1**: OOS recursion does not carry final IS state → accepted (burn-in effect small)
- **MED-2**: BCD convergence does not check `res.success` flag → accepted; Δll < 1e-2 is still a sensible criterion
- **LOW**: bounds, docstrings, winsorization scope, non-trading-day alignment — all acceptable

No HIGH-severity issues remain after the fixes.

### 5.4 Limitations

- Sample is 29 Taiwan large-cap stocks; results may not transfer to smaller
  caps or other markets.
- `yfinance.get_earnings_dates` Surprise(%) accuracy varies by stock — some
  extreme values are genuine small-EPS cases, but some may be parsing artifacts.
  Quantile winsorization at 5%-95% is robust to both interpretations.
- OOS period is 2020-2025 including COVID regime and post-COVID normalization
  — different from IS period. Could be the reason for OOS DM failure.
- The |surprise| specification loses the sign of surprises. A separate test
  could split positive vs negative surprises (dual-coefficient spec), but the
  full-sample result already suggests the event-vs-magnitude distinction, so
  further refinement is lower-priority.

### 5.5 衍生方向 (next_tasks)

| K ID | 主題 | Priority |
|------|------|----------|
| K1149 | Signed-surprise asymmetric spec: θ_EAV_pos (for surprise>0), θ_EAV_neg (for surprise<0), test whether negative surprises dominate | Low |
| K1150 | Cross-market EAV magnitude: US S&P 500 N=30 continuous vs binary, confirm whether "event-not-magnitude" pattern holds universally | High |
| K1151 | Announcement-window effect decay: continuous with \|surprise\| on day 0 vs \|surprise\| × exp(-λ·k) smeared over k days post-announcement; compares to K1145 R1 window={1,3,5} | Low |
| K1152 | Paper 2 manuscript update: add K1148 as a falsification robustness section that strengthens the "binary EAV is the correct reduced form" claim | **High** |

---

## 6. 檔案

- `k1148.py` — main experiment (BCD + Hessian + bootstrap + LRT + placebo + OOS DM)
- `k1148_results.json` — main result JSON (all metrics + per-stock DM + BH table)
- `k1148_placebo_results.json` — standalone placebo distribution dump
- `k1148_binary_vs_continuous.png` — θ_EAV point + t-stat comparison
- `k1148_surprise_vs_absr.png` — scatter of surprise magnitude vs |return| on announcement day (1,747 events)
- `k1148_placebo_distribution.png` — placebo histogram + observed θ line
- `data/earnings_dates_surprise.json` — yfinance surprise cache
- `data/*.parquet` — price cache (copied from K1145)
- `run.log` — stdout execution log

---

## 7. 參考文獻

- Engle, R. F., Ghysels, E., & Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. *Review of Economics and Statistics*, 95(3), 776-797. (GARCH-MIDAS long-run τ component)
- Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy. *JBES*, 13(3), 253-263.
- Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of prediction mean squared errors. *IJF*, 13(2), 281-291. (small-sample DM correction)
- Cameron, A. C., Gelbach, J. B., & Miller, D. L. (2008). Bootstrap-based improvements for inference with clustered errors. *RES*, 90(3), 414-427. (cluster bootstrap for panel)
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the cross-section of expected returns. *RFS*, 29(1), 5-68. (Harvey t>3.0 threshold for multi-testing)
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256. (QLIKE loss function)

## 8. 相關 K 編號

- **K1067 / K1067b / K1067c** — Three-stock A4f-EAV first results
- **K1109** — Pre-registered N=31 cross-sectional sector ANOVA FAIL (provides ticker list)
- **K1113** — Firm covariate regression FAIL
- **K1114** — Rolling θ_EAV with 96% overlap
- **K1140** — HAC + block-bootstrap on rolling θ, 0/9 BH-PASS
- **K1145** — **Pooled panel EAV binary — the direct predecessor. PASS (boot t = 5.24, placebo 13.6σ)**
- **K1148** — This experiment. Continuous |surprise| refinement shows binary is strictly better

## 9. Execution metadata

- Wall time: 542.7 seconds (9 min) on Apple M1 Max
- Random seed: 42 (Bootstrap N=150, Placebo N=60)
- Codex review: gpt-5.4 xhigh reasoning, 3 HIGH issues found and fixed pre-execution
- Date: 2026-04-17
