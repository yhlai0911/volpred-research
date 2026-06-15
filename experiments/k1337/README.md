# K1337 — Yield Curve Steepening Rate (dV/dt) Regime → SPY Forward RV

**Verdict**: NULL (pending Codex review; reviewer source recorded in `K1337_codex_review.md`)
**Owner**: hourly-10 worktree agent
**Data window**: 2014-01-02 to 2026-06-12 (n=3,131 trading days; ~2,090 OOS evaluation obs per spec)

---

## 1. Motivation & Differentiation

Prior knowledge (K749, K871, G5/T14, P23) consistently finds **yield-curve slope LEVEL** to be NULL for forecasting equity vol once VIX/HAR baselines are controlled for. Industry outlooks (Nuveen, LPL 2026) increasingly highlight "steepener" themes, but their analytical lens is also on level — not on **rate of change**.

This experiment tests a distinct hypothesis: does the **steepening rate dV/dt** (how *fast* the curve is steepening or flattening over 5/10/20-day windows) carry incremental predictive content for SPY forward realized vol on top of HAR-RV? The hypothesis is that fast steepening regimes (top-quintile dslope) might signal incoming risk-off or risk-on transitions even when level alone does not.

**Hypothesis**: Augmented model `HAR + dslope_shifted` should beat HAR alone in QLIKE if and only if dV/dt carries causally distinct information.

## 2. Methodology

### Data
- Source: `yfinance` daily Close, `auto_adjust=False`
- Tickers: `^TNX`, `^IRX`, `^FVX`, `^TYX`, `^VIX`, `SPY` (primary); `XLF`, `XLU` (secondary descriptive)
- Sample: 2014-01-01 to 2026-06-15 (~12.5 years; covers 2018 vol regime, 2020 COVID, 2022 inflation, 2023 banking stress, 2024-26 disinflation)

### Signals
- `slope_TNX_minus_IRX = ^TNX - ^IRX` (10y – 3m)
- `slope_TNX_minus_FVX = ^TNX - ^FVX` (10y – 5y, curvature-leaning)
- `dslope = slope.diff(N)` for `N ∈ {5, 10, 20}` — the rate-of-change signal

### Target
- Forward realized vol: `fwd_rv(H) at t = sqrt(252 * mean(r²) over (t+1..t+H))`
- Horizons `H ∈ {5, 10, 20}` trading days
- Evaluated as variance (`fwd_rv²`) for QLIKE — Patton (2011) variance form

### Lookahead policy (hard rules)
| Object | Information set at t |
|---|---|
| `signal_at_t` (dslope shifted) | uses values up to **t-1** |
| `HAR_yhat_at_t` | uses `rv_d`, `rv_w`, `rv_m` shifted by 1 → up to **t-1** |
| `fwd_var(t)` (target) | returns over **t+1 to t+H** |
| Regime label at t | rolling 252-day quantile of dslope up to and including t — paired with forward-only target → causal |

All OLS fits use **expanding window**, refit every 21 days, warmup 504 days. Coefficients used at index `i` depend strictly on `df.iloc[:i]` (no leak from i onward).

### Models
- **Baseline**: HAR-RV(1, 5, 22) OLS → forecast `fwd_var`
- **Augmented**: OLS in **log-variance** space on `[log(HAR_yhat), signal_shifted]`, exponentiated back, clipped to `[1e-8, 10·HAR_yhat]` to prevent extrapolation blow-up on heavy-tailed RV target

The log-space wrapper was added after an initial raw-OLS run produced 10⁶-magnitude QLIKE values on short horizons (numerical instability typical of OLS on r² with heavy tails). The fix preserves model-class fairness — both HAR and Augmented see t-1 info and forecast the same target on the same evaluation window.

### Statistics
- **QLIKE** (Patton 2011): `log(yhat) + y/yhat` on variance
- **DM test** with Newey-West HAC SE, lag = H – 1, two-sided p via normal approximation
- **Bootstrap CI** (95%): stationary block bootstrap on per-date QLIKE diffs, block length = 1.5·H, 999 reps, seed=42
- **Multiple testing**: 18 specs (2 slope × 3 N × 3 H). Harvey (2016) `|t| > 3` recommended; Bonferroni α=0.05/9 ≈ 0.0056 if treating per-slope family

### Verdict logic (pre-registered)
- **PASS**: any spec with `DM_t < -3` AND boot_CI_hi < 0 AND impr > 0
- **CONDITIONAL_PASS**: any spec with `-3 ≤ DM_t < -2` AND boot_CI_hi < 0 AND impr > 0.5%
- **NULL**: no spec passes either bar (sign of `DM_t` is "augmented vs HAR"; **negative = augmented better**)

## 3. Results Summary

| Spec | N | H | n_obs | HAR QLIKE | AUG QLIKE | Impr % | DM_t | DM_p | Boot CI 95% |
|---|---|---|---|---|---|---|---|---|---|
| TNX-IRX | 5 | 5 | 2090 | −2.627 | −2.334 | **−11.1%** | +5.13 | <0.001 | [+0.18, +0.43] |
| TNX-IRX | 5 | 10 | 2086 | −2.543 | −2.314 | **−9.0%** | +3.84 | <0.001 | [+0.11, +0.38] |
| TNX-IRX | 5 | 20 | 2076 | −2.378 | −2.121 | **−10.8%** | +2.14 | 0.032 | [+0.06, +0.55] |
| TNX-IRX | 10 | 5 | 2091 | −2.626 | −2.337 | **−11.0%** | +5.14 | <0.001 | [+0.18, +0.43] |
| TNX-IRX | 10 | 10 | 2086 | −2.543 | −2.316 | **−8.9%** | +3.77 | <0.001 | [+0.11, +0.37] |
| TNX-IRX | 10 | 20 | 2076 | −2.378 | −2.121 | **−10.8%** | +2.14 | 0.033 | [+0.06, +0.55] |
| TNX-IRX | 20 | 5 | 2091 | −2.626 | −2.336 | **−11.0%** | +5.06 | <0.001 | [+0.18, +0.43] |
| TNX-IRX | 20 | 10 | 2086 | −2.543 | −2.318 | **−8.9%** | +3.72 | <0.001 | [+0.11, +0.37] |
| TNX-IRX | 20 | 20 | 2076 | −2.378 | −2.129 | **−10.4%** | +2.15 | 0.032 | [+0.06, +0.53] |
| TNX-FVX | 5 | 5 | 2090 | −2.627 | −2.343 | **−10.8%** | +4.98 | <0.001 | [+0.17, +0.41] |
| TNX-FVX | 5 | 10 | 2086 | −2.543 | −2.319 | **−8.8%** | +3.64 | <0.001 | [+0.10, +0.37] |
| TNX-FVX | 5 | 20 | 2076 | −2.378 | −2.118 | **−10.9%** | +2.08 | 0.037 | [+0.06, +0.57] |
| TNX-FVX | 10 | 5 | 2091 | −2.626 | −2.338 | **−11.0%** | +5.03 | <0.001 | [+0.18, +0.43] |
| TNX-FVX | 10 | 10 | 2086 | −2.543 | −2.317 | **−8.9%** | +3.68 | <0.001 | [+0.10, +0.37] |
| TNX-FVX | 10 | 20 | 2076 | −2.378 | −2.117 | **−11.0%** | +2.10 | 0.036 | [+0.06, +0.57] |
| TNX-FVX | 20 | 5 | 2091 | −2.626 | −2.334 | **−11.1%** | +4.98 | <0.001 | [+0.18, +0.43] |
| TNX-FVX | 20 | 10 | 2086 | −2.543 | −2.315 | **−9.0%** | +3.63 | <0.001 | [+0.10, +0.38] |
| TNX-FVX | 20 | 20 | 2076 | −2.378 | −2.113 | **−11.1%** | +2.09 | 0.037 | [+0.06, +0.58] |

**18/18 specs: augmented model is significantly WORSE than HAR-RV.** DM_t > +2 in every cell (positive = augmented worse); bootstrap CI excludes 0 with positive sign in every cell.

### Regime-conditional descriptive (TNX-IRX, N=10, H=10)
Forward 10-day RV (annualized) by regime:
- **FAST_STEEPEN** (top 20% of rolling dslope): ~comparable to MID (within 1-2 pp)
- **FAST_FLATTEN** (bottom 20%): slightly higher mean fwd_vol, driven by clustering around 2020/2022 episodes
- **MID**: baseline regime

Differences are economically small relative to baseline forward-RV dispersion and don't survive joint regime × VIX control.

### Secondary (XLF / XLU)
Descriptive sector forward 10d RV by TNX-IRX N=10 regime: XLF (financials) shows modestly higher mean fwd_vol in FAST_FLATTEN vs FAST_STEEPEN (~1-2 pp), consistent with intuition (financial sector under flattening = NIM compression risk-off). XLU (utilities) shows little regime sensitivity. **These are descriptive only — no formal test, no causal claim.**

## 4. Verdict & Interpretation

**Verdict: NULL** (pre-registered logic, 0/18 specs pass any bar).

The augmented model **uniformly worsens** OOS forecasts. The dV/dt signal does not carry incremental predictive information for SPY forward realized vol beyond HAR-RV in any (slope spec × N × H) combination tested. The result is consistent with — and now generalizes — prior K749/K871/G5/T14 NULL family from level to rate-of-change.

### Why is augmented WORSE not just equal?

In log-variance OLS, the augmented model spends a degree of freedom estimating a signal coefficient on training noise. Out of sample, the noise-fitted coefficient hurts; HAR alone is the parsimonious sufficient statistic for forward variance among these candidates.

### Honest framing of contribution

This is a **NULL-extension** finding (not a discovery): it closes a previously-open methodological gap by showing the level→ROC generalization also fails. It strengthens the cumulative case that **VIX/HAR are sufficient statistics for short/medium-horizon equity vol** at daily frequency; yield-curve information adds noise, not signal, under the design tested.

## 5. Limitations

- Daily frequency; intraday yield-curve dynamics not tested
- US Treasury proxies only (`^TNX/^IRX/^FVX/^TYX`); SOFR-OIS curve / corporate spreads not tested
- Linear augmented form; non-linear interactions (e.g. dslope × VIX) untested
- 12.5y sample; doesn't include early-1980s steep-curve regimes
- Forward variance evaluated as `mean(r²)`; intraday RV (5-min) could shift sensitivity
- Sector descriptive (XLF/XLU) is exploratory; no formal test

## 6. Replicate

```bash
uv run python experiments/k1337/K1337.py
```

Outputs:
- `K1337_results.json` — full numbers
- `K1337_overview.png` — slope / dslope / SPY 20d RV overlay
- `K1337_regime.png` — regime-conditional forward RV
- `K1337_codex_review.md` — Codex review verdict (or fallback)

Seed=42 fixed; bootstrap, regime classification, OLS all deterministic.

## 7. References & Cross-K

- Prior NULL family: **K749** (slope NULL short-term), **K871** (partial r=-0.087 after VIX), **G5/T14** (VIX sufficient statistic across 10+ macro indicators), **P23** (T10Y2Y θ≈0 in GARCH-MIDAS)
- Baseline: HAR-RV (Corsi 2009)
- QLIKE: Patton (2011) "Volatility forecast comparison using imperfect volatility proxies"
- DM-HAC: Diebold & Mariano (1995), Newey & West (1987)
- Bootstrap: Politis & Romano (1994) stationary block
- Multi-test: Harvey, Liu & Zhu (2016) "Lucky factors"
