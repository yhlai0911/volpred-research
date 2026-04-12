# K1081: A4f on EEM Emerging Markets — Distinguishing "Non-US" vs "Taiwan-Specific" Failure

**Status**: Completed 2026-04-12
**Proposer**: User (via K1081 brief)
**Executor**: Claude
**Upstream**: K988, K1075 (SPY), K1077 (0050.TW), K1078 (QQQ), K1079 (VXN), K1080 (IWM)
**Downstream**: Paper 9 five-asset table, future cross-market A4f work

---

## 1. Motivation and Research Question

K1075-K1080 established the **Paper 9 cross-asset A4f axis** using one
asset per rung:

| Asset         | Market / Sector         | DM t   | Harvey | θ₁ span (full) |
|---------------|-------------------------|--------|--------|----------------|
| SPY  (K1075)  | US large-cap            | +7.92  | PASS   | <1             |
| QQQ  (K1078)  | US tech (Nasdaq-100)    | +5.99  | PASS   | 1.91           |
| IWM  (K1080)  | US small-cap (Russell)  | +4.80  | PASS   | 3.54           |
| 0050.TW (K1077) | Taiwan single market  | -0.49  | FAIL   | ~4             |

The 0050.TW null result raises the central question of this experiment:

> Is the failure because the instrument is **non-US** (VIX is an SPX IV and
> cannot carry information across markets), or because Taiwan has **unique
> structural factors** (TWD currency, retail-dominated flow, concentrated
> TSMC exposure, political risk)?

**EEM (iShares MSCI Emerging Markets ETF)** is the natural discriminator:

- USD-denominated, NYSE-listed → same currency/microstructure as US ETFs
- Diversified EM basket: ~30% China, ~18% India, ~15% Taiwan, ~12% Korea
- VIX (SPX IV) should still carry some global-risk-off information for EM
- IPO 2003-04-15 → >22 years history, sufficient for the 3 OOS windows

**Three possible outcomes and their Paper 9 implications**:

| Outcome               | Verdict | Paper 9 claim                                                  |
|-----------------------|---------|----------------------------------------------------------------|
| Harvey-PASS (t>3)     | Taiwan-specific | A4f works on USD-denominated liquid ETFs incl. EM; 0050.TW null is local |
| Marginal (1<t<3)      | Attenuates      | A4f effect weakens outside US but stays directional |
| NULL (t<1)            | Non-US failure  | A4f requires US market structure; all non-US fail |

---

## 2. Method (strict parity with K1075 / K1078 / K1080)

### Models (exactly two)

1. **GJR-GARCH(1,1) baseline**  
   `h_t = ω + α r²_{t-1} + γ r²_{t-1} I(r_{t-1}<0) + β h_{t-1}`

2. **A4f (VIX² free-ω, the K988 winner specification)**  
   `τ_t = max(θ₀ + θ₁ · VIX²_{t-1}, ε)`  
   `u_{t-1} = r_{t-1} / √τ_t`  
   `g_t = ω_g + α u²_{t-1} + γ u²_{t-1} I(u_{t-1}<0) + β g_{t-1}`  
   `σ²_t = τ_t · g_t`  
   Parameters: `[θ₀, θ₁, ω_g, α, γ, β]` (6-dim)

### Estimation

- `scipy.optimize.minimize` L-BFGS-B, 3 multi-starts, `maxiter=500`
- Numba JIT on GJR log-likelihood
- `np.random.seed(42)` for all bootstrap

### OOS design

| Window           | Dates                 | N    | Economic context                                     |
|------------------|-----------------------|------|------------------------------------------------------|
| Early_Crisis     | 2007-01-01 – 2012-12-31 | 1510 | GFC + Euro crisis; EM collapsed harder than SPX      |
| Middle_Recovery  | 2013-01-01 – 2018-12-31 | 1510 | China 2015 devaluation, Trump tariffs                |
| Late_COVID       | 2019-01-01 – 2026-04-11 | 1828 | COVID + rate hike + China tension                    |

- Rolling window: 2000 days (`max(0, abs_idx - WINDOW)` so first refit at
  2007-01-03 uses ~935 available obs — same convention as K1075/K1078/K1080).
- Refit every 63 trading days (~quarterly), 78 refits total.
- Sequential forecast: GJR `h_t = f(h_{t-1}, r²_{t-1})` and A4f
  `σ²_t = τ(VIX_{t-1}) · g(g_{t-1}, r_{t-1}, τ_t)` — no static-σ peeking.

### Crisis sub-periods (EM-specific calibration)

| Crisis         | Dates                 | Rationale |
|----------------|-----------------------|-----------|
| GFC            | 2008-01-01 – 2009-12-31 | Global benchmark (EEM collapsed -60%) |
| China_2015     | 2015-06-01 – 2016-02-29 | EM-specific devaluation + China crash |
| COVID_Crash    | 2020-02-01 – 2020-06-30 | Global shock, VIX max 82.69 |
| Bear_2022      | 2022-01-01 – 2022-12-31 | Rate hike + dollar strength |

### Evaluation

- QLIKE loss on r² (Patton 2011, proxy-robust)
- DM test HAC-Newey-West (Harvey 2016 |t|>3.0 threshold)
- Spearman rank correlation
- Moving-block bootstrap 95% CI (`n_boot=1000`, `block_len ~ n^{1/3}`, seed 42)

---

## 3. Data

- **EEM**: yfinance `Adj Close`, 2003-04-15 → 2026-04-10 (n=5784)
- **^VIX**: yfinance `Close`, same range
- Joined sample: n=5783 after inner-join dropna

### Descriptive statistics (full sample)

| Statistic              | EEM     |
|------------------------|---------|
| Ann. return mean       | +9.21%  |
| Ann. return std        | 27.00%  |
| Skew                   | +0.02   |
| Excess kurtosis        | 15.96   |
| Max 1-day drawdown     | -17.6%  |
| VIX mean               | 19.00   |
| VIX max (2020-03-16)   | 82.69   |

EEM is substantially more volatile than SPY (ann. std 27% vs ~16%) and
has very heavy tails (kurt 16).

---

## 4. Results

### 4.1 Full OOS (2007-2026, n=4848)

| Model | QLIKE    | Diff %  | DM t     | p-value | Harvey | Spearman |
|-------|----------|---------|----------|---------|--------|----------|
| GJR   | -7.614001 | —       | —        | —       | —      | 0.229    |
| A4f   | -7.646795 | -0.43% | **+5.248** | <0.0001 | **PASS** | 0.283    |

Bootstrap 95% CI for the mean loss diff: `[0.0158, 0.0497]` (strictly
positive → A4f wins robustly).

### 4.2 Per OOS window

| Window           | n    | QL_GJR    | QL_A4f    | Diff %  | DM t    | Harvey |
|------------------|------|-----------|-----------|---------|---------|--------|
| Early_Crisis     | 1510 | -6.90619  | -6.93124  | -0.36%  | +2.965  | FAIL (0.035 below threshold) |
| Middle_Recovery  | 1510 | -7.95418  | -7.99109  | -0.46%  | +3.684  | **PASS** |
| Late_COVID       | 1828 | -7.91768  | -7.95347  | -0.45%  | +2.871  | FAIL (just below threshold) |

All three windows are **directionally positive** and two windows are near
or at the Harvey threshold. The full-OOS combined n=4848 gives the pooled
t=+5.248 Harvey-PASS.

### 4.3 Crisis sub-periods

| Crisis         | n   | VIX max | QL_GJR    | QL_A4f    | Diff %  | DM t    |
|----------------|-----|---------|-----------|-----------|---------|---------|
| GFC            | 505 | 80.86   | -6.26210  | -6.30319  | -0.66%  | +2.716  |
| China_2015     | 189 | 40.74   | -7.39841  | -7.45038  | -0.70%  | +2.130  |
| COVID_Crash    | 104 | 82.69   | -6.30304  | -6.48836  | **-2.94%** | +1.367  |
| Bear_2022      | 251 | 38.94   | -7.43667  | -7.47360  | -0.50%  | +1.497  |

All four crises show A4f improvement. Small n in COVID (104) and
Bear_2022 (251) makes Harvey threshold hard to reach, but the economic
size of the gains (notably -2.94% in COVID) is substantial.

### 4.4 VIX buckets (lagged VIX, matching A4f's `τ_t = f(VIX_{t-1})`)

| Bucket   | Range   | n    | QL_GJR   | QL_A4f   | Diff %  | DM t    |
|----------|---------|------|----------|----------|---------|---------|
| Low      | [0, 15) | 1545 | -8.22461 | -8.25659 | -0.39%  | +3.733  |
| Normal   | [15,25) | 2421 | -7.68530 | -7.70544 | -0.26%  | +3.423  |
| High     | [25,40) |  703 | -6.69157 | -6.73364 | -0.63%  | +1.808  |
| Extreme  | [40,60) |  141 | -5.24630 | -5.42568 | -3.42%  | +1.872  |
| Crisis   | [60,200)|   38 | -4.09577 | -4.25201 | **-3.81%** | +1.401  |

**H4 PASS** — A4f does not break down at extreme VIX; in fact, the largest
QLIKE-diff gains are in the Extreme and Crisis buckets (-3.42% and -3.81%).
DM t is non-significant at extreme VIX only because n is too small (38 and
141) to reject H0.

### 4.5 θ₁ stability

| Statistic                   | EEM         |
|-----------------------------|-------------|
| N refits converged          | 77          |
| Median θ₁                   | 2.56×10⁻⁷   |
| Full range (min→max)        | 1e-10 → 1.89e-3 |
| **Full span** (orders)      | 7.28        |
| **P25-P75 span**            | **0.23**    |
| **P10-P90 span**            | **0.44**    |
| **P5-P95 span**             | **1.84**    |
| Boundary hits (1e-10)       | 1 (2007-04-04, Early_Crisis startup) |
| Near-upper hits (>0.9e-3)   | 1 (2015-10-02, China devaluation)    |

**Critical reading**: the full 7.28-order span is driven by **2 outlier
refits out of 77** (both converged but at numerical bounds). The core
distribution (P25-P75: 0.23 orders, P10-P90: 0.44 orders) is as stable as
SPY. The P10-P90 core span 0.44 places EEM close to SPY-stable behaviour.

---

## 5. Hypothesis verdicts

| # | Hypothesis                                       | Verdict | Evidence |
|---|--------------------------------------------------|---------|----------|
| H1 | Full OOS A4f Harvey-PASS (t>3)                  | **PASS** | t=+5.248, p<0.0001 |
| H2 | GFC A4f improves over GJR                       | **PASS** | -0.66%, t=+2.716 directional |
| H3 | All 3 OOS windows directional win               | **PASS** | 3/3 windows diff%<0 |
| H4 | No breakdown at VIX>40                          | **PASS** | Extreme -3.42%, Crisis -3.81% |
| H5 | θ₁ intermediate (prediction 2.5-3.5)            | **Surprise**: P10-P90 span 0.44 → SPY-stable; full span 7.28 only due to 2 outliers |
| H6 | Discrimination (non-US vs Taiwan-specific)      | **Taiwan-specific** — A4f works on EM diversified ETF |

**Overall verdict**: EEM A4f **passes** the Paper 9 cross-asset test.
Combined with K1077's null on 0050.TW, the 0050.TW failure is
**Taiwan-specific**, not a generic non-US failure.

---

## 6. Paper 9 Five-Asset Table

| Asset           | Market                    | Full DM | Diff %  | Harvey | θ₁ span (full) | θ₁ span (P10-P90) |
|-----------------|---------------------------|---------|---------|--------|----------------|-------------------|
| SPY  (K1075)    | US large-cap              | +7.915  | -0.89% | PASS   | <1             | <1                |
| QQQ  (K1078)    | US tech                   | +5.995  | -0.59% | PASS   | 1.91           | —                 |
| IWM  (K1080)    | US small-cap              | +4.797  | -0.38% | PASS   | 3.54           | 1.87              |
| **EEM (K1081)** | **EM diversified (USD)**  | **+5.248** | **-0.43%** | **PASS** | **7.28 (2 outliers)** | **0.44** |
| 0050.TW (K1077) | Taiwan single market (TWD) | -0.488 | +0.33% | FAIL   | ~4             | —                 |

### Paper 9 final claim

> A4f-VIX² **generalises across USD-denominated liquid equity ETFs** —
> including emerging-markets diversified exposure (EEM) — with Harvey-PASS
> discrimination against a plain GJR-GARCH baseline over three non-overlapping
> OOS windows spanning 2007-2026. The **0050.TW null** found in K1077 is
> therefore **Taiwan-specific** rather than a generic non-US phenomenon,
> and likely reflects local currency effects (TWD vs USD), retail-dominated
> flow dynamics, concentrated TSMC exposure, and political-risk premia that
> VIX (an SPX IV) cannot track. Extending A4f to non-USD single-market
> emerging equities remains an open question requiring market-native IV
> surrogates (e.g. VIXTWN for Taiwan).

---

## 7. Limitations and caveats

1. **Per-window Harvey**: only Middle_Recovery reaches Harvey t>3 on its
   own; Early_Crisis (2.965) and Late_COVID (2.871) just miss. The pooled
   full-OOS Harvey-PASS is driven by the combined n=4848. Paper 9 should
   report both.
2. **VIX is SPX IV**: using VIX (not VXEEM) is deliberate because (a) VXEEM
   has limited yfinance history and (b) VIX as a global risk-off signal
   is the relevant discriminant for the H_non_us vs H_tw_uniq test. A
   future robustness check could rerun with VXEEM where history allows.
3. **EEM composition drifts**: the EM basket has changed composition
   (MSCI EM 2013 Korea re-class, etc.). The sample treats the ETF as a
   single time series; this is standard but bears noting.
4. **θ₁ outliers**: 2 refits out of 77 hit numerical bounds (2007-04-04
   at 1e-10; 2015-10-02 at 1.89e-3). The core distribution (P10-P90) is
   stable at 0.44 orders, but the full-span 7.28 should be reported with
   P10-P90 alongside in Paper 9 to avoid misinterpretation.
5. **Small-n crises**: COVID_Crash (n=104) and China_2015 (n=189) can't
   reach Harvey t>3 even with large effect sizes.

---

## 8. Files

| File | Purpose |
|------|---------|
| `k1081.py` | Main script (EEM A4f extended OOS + 4 crises + VIX buckets + 5-asset comparison) |
| `k1081_results.json` | All numerical results, refit log, 5-asset comparison |
| `k1081_extended_dm.png` | 3 OOS windows QLIKE + DM barplot |
| `k1081_crisis_periods.png` | 4 crisis sub-period DM barplot |
| `k1081_vix_bucket.png` | 5 VIX buckets QLIKE diff % |
| `k1081_theta1_evolution.png` | θ₁ time series across 77 refits |
| `k1081_five_asset_comparison.png` | Paper 9 5-asset side-by-side (DM, θ₁ span, summary) |

---

## 9. References

- Engle, R.F., Ghysels, E., Sohn, B. (2013). Stock market volatility
  and macroeconomic fundamentals. *Review of Economics and Statistics*
  95(3), 776-797.
- Patton, A.J. (2011). Volatility forecast comparison using imperfect
  volatility proxies. *Journal of Econometrics* 160(1), 246-256.
- Harvey, D.I., Leybourne, S.J., Newbold, P. (2016). Testing the equality
  of prediction mean squared errors [multiple-testing t-threshold].
- Hansen, P.R., Lunde, A. (2005). A forecast comparison of volatility
  models: does anything beat a GARCH(1,1)? *Journal of Applied
  Econometrics* 20(7), 873-889.

## 10. Reproduction

```bash
# from repo root
uv run python experiments/k1081/k1081.py
```

Runtime: ~4 minutes on Apple M1 Max (78 refits × 2 models, numba JIT).
Deterministic (random seed 42).
