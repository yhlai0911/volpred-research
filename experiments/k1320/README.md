# K1320: Copula-based GARCH Hedge — Hsu et al. (2008, JFM) Minimum Variance Hedge Ratio

## Experiment Overview

**ID**: K1320  
**Date**: 2026-05-21  
**Method**: GJR-GARCH(1,1) marginals + Probability Integral Transform (PIT) → 5 copula families → minimum variance hedge ratio  
**Reference**: Hsu, C.-C., Tseng, C.-P., & Wang, Y.-H. (2008). Dynamic hedging with futures: A copula-based GARCH model. *Journal of Futures Markets*, 28(11), 1095–1116.

## Motivation & Differentiation

Prior work in this knowledge base used copula-GARCH for portfolio VaR (K1100 series). This experiment applies the Hsu et al. (2008) minimum variance hedging framework:

- **New contribution 1**: Copula family selection impact on minimum variance hedge ratio — 5 families compared via AIC
- **New contribution 2**: SPY-QQQ high-correlation equity pair (r≈0.93), well-suited for copula modeling (positive tail dependence)
- **New contribution 3**: Static vs dynamic (rolling 252d) copula hedge comparison in OOS

K1100b lesson applied: Clayton copula performs poorly for negative correlation pairs. SPY-QQQ is strongly positive (r≈0.94), so all 5 copulas are valid candidates.

## Data

| Parameter | Value |
|-----------|-------|
| Spot asset | SPY (S&P 500 ETF) |
| Hedge instrument | QQQ (NASDAQ-100 ETF) |
| Full period | 2005-01-04 to 2024-12-30 |
| In-sample (IS) | 2005-01-01 to 2018-12-31 (N=3,522) |
| Out-of-sample (OOS) | 2019-01-01 to 2024-12-31 (N=1,509) |
| IS correlation | 0.9118 |
| OOS correlation | 0.9319 |
| IS Kendall's tau | 0.7046 |
| Source | yfinance (adjusted close) |

## Methodology

### Step 1: GJR-GARCH(1,1) Marginals (IS fit)

Both SPY and QQQ log returns fitted with GJR-GARCH(1,1):

| Asset | omega | alpha | gamma | beta | LogLik |
|-------|-------|-------|-------|------|--------|
| SPY | 0.0253 | 0.0000 | 0.2166 | 0.8646 | -4469.72 |
| QQQ | 0.0412 | 0.0000 | 0.1844 | 0.8743 | -5164.01 |

Positive gamma (leverage effect) confirms asymmetric volatility in both assets.

### Step 2: PIT → Uniform Margins

Empirical CDF rank-based PIT (avoids distributional misspecification). Standardized residuals u_t = epsilon_t / sigma_t → U[0,1] via empirical ranks/(n+1).

### Step 3: Copula MLE (5 families)

| Copula | Parameter(s) | Log-Likelihood | AIC | Rank |
|--------|-------------|----------------|-----|------|
| **Gumbel** | theta=3.3703 | 3471.0 | **-6940.0** | **1 (BEST)** |
| Student-t | rho=0.8875, nu=5.39 | 2775.1 | -5546.3 | 2 |
| Normal | rho=0.8859 | 2699.7 | -5397.4 | 3 |
| Frank | theta=10.977 | 2460.0 | -4918.0 | 4 |
| Clayton | theta=1.0000 | 1494.4 | -2986.9 | 5 |

**Key finding**: Gumbel copula wins decisively (AIC=-6940 vs Student-t -5546, delta=1394). This reflects strong upper tail dependence in SPY-QQQ — joint extreme up-moves are more probable than implied by Gaussian/Clayton. This makes intuitive sense: both indices rally hard together in tech-driven bull markets.

### Step 4: Hedge Ratio Formula

```
h*_t = rho_copula * sigma_SPY_t / sigma_QQQ_t
```

Where:
- `rho_copula` = linear correlation equivalent derived from Kendall's tau (Greiner's relation: rho = sin(pi/2 * tau))
- `sigma_t` = one-step-ahead GARCH conditional volatility (uses t-1 information only)

Linear correlation equivalents:
| Copula | tau (Kendall) | rho_equiv |
|--------|--------------|-----------|
| Gumbel | 0.7033 | **0.8933** |
| Student-t | 0.6952 | 0.8875 |
| Normal | 0.6930 | 0.8859 |
| Frank | 0.6902 | 0.8839 |
| Clayton | 0.3333 | 0.5000 |

## Lookahead Prevention (CRITICAL)

All hedge ratios are lag-1 applied:

```python
# LOOKAHEAD-FREE: h_{t-1} applied to return at t
hr_lagged = np.roll(hedge_ratios, 1)
hr_lagged[0] = hedge_ratios[0]
hedged_t = spy_return_t - hr_lagged_t * qqq_return_t
```

Additionally:
- GARCH sigma_t uses recursive equation with e_{t-1} only (no same-period information)
- OOS GARCH uses IS-estimated parameters (no parameter re-estimation leakage)
- DCC correlation at t uses e_{t-1} in the recursion (lagged)
- Rolling OLS uses returns up to t-1 only (window ends at t-1)

seed=42 for all random operations.

## Results

### Hedge Effectiveness (HE = 1 - Var(hedged) / Var(unhedged))

| Strategy | HE_IS | HE_OOS |
|----------|-------|--------|
| **Copula_Gumbel_static** | 0.8516 | **0.8880** |
| Copula_Student_t_static | 0.8516 | 0.8879 |
| Copula_Normal_static | 0.8515 | 0.8879 |
| DCC_t (static) | 0.8516 | 0.8879 |
| Copula_Frank_static | 0.8515 | 0.8878 |
| Copula_Gumbel_dynamic | 0.8516 | 0.8876 |
| **DCC_Gaussian** | 0.8504 | 0.8862 |
| Rolling_OLS | 0.8413 | 0.8701 |
| OLS | 0.8314 | 0.8584 |
| Copula_Clayton_static | 0.6871 | 0.7133 |

### Performance Metrics (OOS 2019-2024)

| Strategy | Sharpe | Ann.Vol | MaxDD |
|----------|--------|---------|-------|
| Unhedged (SPY) | 0.797 | 0.1991 | -0.3575 |
| Copula_Gumbel_static | 0.061 | 0.0666 | -0.2071 |
| DCC_Gaussian | 0.059 | 0.0672 | -0.2122 |
| Rolling_OLS | -0.063 | 0.0718 | -0.2206 |
| OLS | -0.219 | 0.0749 | -0.1964 |
| Copula_Clayton_static | 0.677 | 0.1066 | -0.2338 |

Note: Low Sharpe for hedged portfolios is expected — hedging removes systematic return along with variance. The relevant metric is HE (variance reduction), not return.

### DM Test (HLN, HAC) — vs DCC_Gaussian Benchmark

Threshold: |t| > 1.96 (5% two-sided). Harvey |t|>3 threshold is NOT applicable here (that's for cross-sectional factor studies per Harvey, Liu & Zhu 2016).

| Strategy | DM stat | p-value | Significant? | Better than DCC? |
|----------|---------|---------|-------------|-----------------|
| Copula_Gumbel_static | 0.500 | 0.617 | No | Yes |
| Copula_Student_t_static | 0.506 | 0.612 | No | Yes |
| Copula_Normal_static | 0.507 | 0.612 | No | Yes |
| Copula_Frank_static | 0.508 | 0.612 | No | Yes |
| Copula_Gumbel_dynamic | 0.441 | 0.659 | No | Yes |
| DCC_t | 0.506 | 0.612 | No | Yes |
| Rolling_OLS | -0.769 | 0.442 | No | No |
| OLS | -0.838 | 0.402 | No | No |
| Copula_Clayton_static | -1.739 | 0.082 | No | No |

**All copula models (except Clayton) produce lower hedged portfolio variance than DCC_Gaussian in OOS, but the differences are not statistically significant at 5%.**

### Key Numerical Results

- Best IS copula (AIC): **Gumbel** (theta=3.3703, AIC=-6940.0)
- Best OOS copula (HE): **Gumbel** (HE=0.8880)
- DCC Gaussian OOS HE: 0.8862
- Improvement of Gumbel over DCC: **+0.0018** (not significant, DM p=0.617)
- OLS HE: 0.8584 (significantly below copula methods)
- Clayton severely underperforms (HE=0.7133) — low rho_equiv (0.50) underestimates SPY-QQQ dependence

## Research Conclusions

1. **Best copula**: Gumbel achieves lowest AIC (-6940) and highest OOS HE (0.8880), consistent with SPY-QQQ's strong upper tail dependence in tech-driven bull markets.

2. **Copula vs DCC**: Gumbel copula outperforms DCC_Gaussian in OOS HE (+0.0018) and all copula models (except Clayton) beat DCC in raw variance terms, but **none achieve statistical significance at 5% via DM test** (p-values 0.61-0.66). The improvement is economically small.

3. **Static vs dynamic**: Dynamic Gumbel (rolling 252d) slightly underperforms static Gumbel (HE=0.8876 vs 0.8880). The transaction cost of re-estimation every 252d does not improve OOS performance — IS-fitted parameters are stable enough.

4. **Clayton failure**: Clayton HE=0.7133 confirms the K1100b lesson extrapolated: even for positive pairs, Clayton's lower-tail-only dependence structure misses the symmetric high-correlation structure of SPY-QQQ.

5. **Convergence across models**: Normal, Student-t, Frank, Gumbel and DCC all achieve HE in the range 0.8862-0.8880 — a narrow 0.0018 band. At r≈0.93, the dominant driver of hedge effectiveness is the level of correlation (all models estimate rho_equiv ≈ 0.88-0.89), not the copula tail structure.

## Charts

- `k1320_hedge_analysis.png`: Hedge ratio time series, HE comparison, cumulative returns, copula AIC
- `k1320_hedge_ratio_dynamics.png`: DCC vs copula static vs dynamic hedge ratios, GARCH volatilities

## Files

| File | Description |
|------|-------------|
| `k1320.py` | Full experiment script |
| `k1320_results.json` | Structured results (copula AIC, HE IS/OOS, DM tests) |
| `k1320_hedge_analysis.png` | Main 4-panel chart |
| `k1320_hedge_ratio_dynamics.png` | Hedge ratio dynamics chart |
| `README.md` | This file |

## Verdict

- **Overall**: CONDITIONAL_PASS
- **Reason**: All methods produce valid, consistent results with no lookahead. Copula methods outperform OLS/Rolling OLS. The Gumbel copula is theoretically motivated (upper tail dependence) and achieves best IS AIC and OOS HE, but the margin over DCC is economically small (+0.0018 HE) and not statistically significant (DM p=0.617). Publishable as a methodology comparison with honest null-difference conclusion.
- **Best copula**: Gumbel (AIC=-6940, OOS HE=0.8880, upper tail dependence captures SPY-QQQ joint bull-market behavior)
- **OOS HE vs DCC**: Gumbel HE=0.8880 > DCC_Gaussian HE=0.8862 (+0.0018), DM t=0.50, p=0.617 — **not statistically significant**
- **Verdict rationale**: CONDITIONAL (not PASS) because the improvement over DCC is economically trivial and statistically non-significant. The honest conclusion is "copula methods match DCC; Gumbel marginally preferred on AIC grounds; all copula methods dominate simple OLS."

## Fix log 2026-06-04 (K1320_fix_dynamic_lookahead_DM)

Codex 24h review (`storage/reviews/codex_24h/mile_2c4efefa_review.md`) found 4 must-fix issues. All four resolved; experiment re-run end-to-end with seed=42.

### Fix 1 — Dynamic Gumbel `np.interp` lookahead removal (HIGH)

- **Before**: `rho_interp = np.interp(oos_indices, sampled_indices, sampled_rho)` linearly interpolated between the 21-day re-estimate sample points. For OOS day `i` falling between sample `j` and `j+1`, the interpolated rho used the *future* sample at `j+1` → t+21 information leaked into t.
- **After**: piecewise-hold (forward-fill). Each day `i` uses `rho_dynamic_values[max(k : k ≤ i)]` — the most recent already-estimated rho, no future leak.
- **Code**: `k1320.py` §9 (lines 575-595).
- **Impact**: Dynamic Gumbel OOS HE **0.8876 → 0.8874** (−0.0002). As Codex predicted, lookahead bias was small in magnitude because rho was very stable across re-estimate windows.

### Fix 2 — DM test loss object: r^4 → squared hedged returns (HIGH)

- **Before**: caller computed `e = rets**2`, passed to `dm_test_hln_hac`, which internally did `d = e1**2 - e2**2`. Final loss differential was `r_hedged_t^4 - r_hedged_t^4` — not a standard DM, not Patton volatility loss, not variance-reduction test. UNSOUND per Codex.
- **After**: `dm_test_hln_hac` now treats `e1, e2` as loss series directly: `d = e1 - e2`. Caller still passes `rets**2` (squared hedged return = daily variance proxy), so the test is now a proper DM on squared hedged returns → equivalent to a variance-reduction test (rejecting H₀ means one model genuinely produces lower hedged variance).
- **Code**: `k1320.py` §14 `dm_test_hln_hac` (lines 916-936).
- **Impact**: DM p-values change substantially:

  | Strategy vs DCC_Gaussian | Old DM t | Old p | New DM t | New p | New sig 5%? |
  |---|---|---|---|---|---|
  | Copula_Gumbel_static | 0.500 | 0.617 | **0.849** | **0.396** | no |
  | Copula_Gumbel_dynamic | 0.441 | 0.659 | **0.628** | **0.530** | no |
  | Copula_Student_t_static | 0.506 | 0.612 | **0.777** | **0.437** | no |
  | Copula_Normal_static | 0.507 | 0.612 | **0.753** | **0.452** | no |
  | Copula_Frank_static | 0.508 | 0.612 | **0.719** | **0.472** | no |
  | StudentT_Copula_static (was DCC_t) | 0.506 | 0.612 | **0.777** | **0.437** | no |
  | OLS | -0.838 | 0.402 | **-4.949** | **0.0000** | **YES** |
  | Rolling_OLS | -0.769 | 0.442 | **-2.436** | **0.0149** | **YES** |
  | Copula_Clayton_static | -1.739 | 0.082 | **-4.035** | **0.0001** | **YES** |

  Three findings that flip sign-class:
  - OLS, Rolling_OLS, Clayton are now **significantly worse** than DCC_Gaussian at 5% (previously masked by r^4 loss inflating variance).
  - Copula vs DCC (Normal/Student-t/Gumbel/Frank) remain **not significant** — Codex's "no statistical difference" conclusion still holds under the sound test, but with different p-values (0.40–0.53, not 0.61).

### Fix 3 — `DCC_t` rename → `StudentT_Copula_static`

- **Before**: label `DCC_t` suggested dynamic Student-t DCC; actual code was `rho_t * spy_sigma_oos / qqq_sigma_oos` (static t-copula rho × GARCH sigmas). HE numerically identical to `Copula_Student_t_static` (0.8879).
- **After**: renamed to `StudentT_Copula_static` throughout `k1320.py` (lines 720-722, 779, 851-855) and `k1320_results.json` (`hedge_effectiveness.IS.StudentT_Copula_static` / `.OOS.StudentT_Copula_static`, `performance_metrics_oos.StudentT_Copula_static`, `dm_tests_vs_dcc_gaussian.StudentT_Copula_static`). Numerical results unchanged (same code path); only label corrected.

### Fix 4 — First-day hedge consistency

- **Before**: docstring at `compute_hedged_returns` said "first observation has no hedge (unhedged)" but code `hr_lagged[0] = hedge_ratios[0]` applied the day-1 hedge. Same inconsistency in 5 inline `np.roll` sites for IS HE.
- **After**: all 6 sites set `hr_lagged[0] = 0.0` — first observation truly unhedged. Affects 1/3522 IS + 1/1509 OOS = 0.07% of observations.
- **Impact**: HE_IS changes by ≤0.0003 across all strategies (e.g. Gumbel_static IS HE 0.8516 → 0.8513). HE_OOS unchanged at displayed 4-decimal precision (e.g. Gumbel_static OOS HE remains 0.8880). Within rounding noise — as Codex noted, audit-trail-only fix.

### New OOS HE summary (after all fixes)

| Strategy | Old OOS HE | New OOS HE | Δ |
|---|---|---|---|
| Copula_Gumbel_static | 0.8880 | 0.8880 | 0.0000 |
| Copula_Gumbel_dynamic | 0.8876 | 0.8874 | −0.0002 (lookahead fix) |
| Copula_Student_t_static | 0.8879 | 0.8879 | 0.0000 |
| Copula_Normal_static | 0.8879 | 0.8879 | 0.0000 |
| Copula_Frank_static | 0.8878 | 0.8878 | 0.0000 |
| StudentT_Copula_static (was DCC_t) | 0.8879 | 0.8879 | 0.0000 (label only) |
| DCC_Gaussian | 0.8862 | 0.8862 | 0.0000 |
| Rolling_OLS | 0.8701 | 0.8701 | 0.0000 |
| OLS | 0.8584 | 0.8584 | 0.0000 |
| Copula_Clayton_static | 0.7133 | 0.7133 | 0.0000 |

OOS HE essentially unchanged; the substantive corrections are in the **DM tests** (loss object) and **interpretation** (OLS/Rolling/Clayton now significantly worse than DCC, copula vs DCC remains null at sound test).

### Article (`mile_2c4efefa`) implications

- Codex's lookahead concern is **confirmed but immaterial in magnitude** (HE moved −0.0002). The "no future information leak" claim was technically false for dynamic Gumbel; now true after fix.
- "Gumbel and DCC have no statistically distinguishable difference" remains the **honest conclusion** under the corrected DM test (Gumbel_static p=0.396, Gumbel_dynamic p=0.530). The article's caveat note about Codex review can stay; the underlying message holds.
- The article's claim "all models are within statistical noise" is **wrong for OLS/Rolling_OLS/Clayton vs DCC** — these are now significantly worse at 5%. Reference K1320 README v2 for the corrected DM table.
- `DCC_t` row in article should be renamed to `StudentT_Copula_static` (or replaced with the clarification that it is *static* t-copula × GARCH, not a real t-DCC).
