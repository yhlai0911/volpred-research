# K1512 — Double-ML factor causality test on US factor ETFs

**Verdict**: `CONDITIONAL_PASS` (essentially **NULL** after Codex-prompted multiple-testing correction and repeated cross-fitting).

## Research question

After controlling for macro / market confounders (VIX, term spread, lag-1 SPY return, lag-1 own return), does each US factor ETF's prior-12m momentum exposure carry a non-zero **partial causal-like effect** on next-month excess return over SPY? Or is the apparent factor return mostly **spurious correlation with regime / market vol**?

Framework: **Chernozhukov et al. (2018, EJ) — Double / Debiased Machine Learning Partial Linear Regression (DML PLR)**:

```
Y_{t+1}    = θ · D_t + g(X_t) + ε_{t+1}
D_t        = m(X_t)  + v_t
```

Estimate θ̂ via DML PLR with random-forest nuisance learners and Neyman-orthogonal moment.

## Data

| Field | Source | Period |
|------|--------|--------|
| `MTUM`, `VLUE`, `QUAL`, `SPY` adjusted close | yfinance | 2013-01 → 2026-05 (monthly) |
| `^VIX` month-end level | yfinance | same |
| `DGS10 − DGS2` term spread | FRED (pandas-datareader) | **FAILED** — fell back to constant 0 (caveat below) |

Build:
- Returns: monthly simple returns `mpx.pct_change()` (auto-adjusted).
- `D_t` = rolling 12-month gross return − 1, computed at month-end t.
- `Y_t` = `ret_own.shift(-1) − ret_SPY.shift(-1)` (next-month excess over SPY).
- `X_t` = `[VIX_t, term_spread_t, ret_SPY.shift(1), ret_own.shift(1)]`.
- All rows with NaN dropped → MTUM/VLUE n=145 months, QUAL n=142 months (different inception).

### Lookahead audit
- `Y` is strictly t+1; `X_lag_*` is `.shift(1)`; D rolling window ends at t (known at t close).
- Same-date `VIX_t` / `term_spread_t` controls are defensible under "execution at month-end close after data observed" — flagged as caveat for live-trading interpretation.
- Codex 2026-06-16 review confirmed no lookahead bug in Y/D/X construction.

## Method

| Component | Choice |
|---|---|
| Estimator | `doubleml.DoubleMLPLR(score="partialling out")` |
| Nuisance ML | `RandomForestRegressor(n_estimators=100, max_depth=4, min_samples_leaf=5, random_state=42)` for both ℓ(X)=E[Y\|X] and m(X)=E[D\|X] |
| Cross-fitting | `n_folds=2, n_rep=20` (repeated cross-fitting for fold-randomness robustness; **upgraded from n_rep=1 after Codex review** — single-rep QUAL artifact disappeared) |
| Standard error | DML default (HC) + **manual Newey-West HAC** on orthogonal score residuals (`ψ_i = (Y_resid − θ·D_resid)·D_resid / E[D_resid²]`, mean-centered, Bartlett kernel) at lag ∈ {1,3,6,12} |
| Multiple-testing | **Bonferroni** across 3 factors → α = 0.05/3 = 0.0167 |
| Seed | 42 throughout |

### Verdict gate (NW lag-3 SE)
- `PASS_PRELIMINARY` per factor: Bonferroni-pass (`p < 0.0167`) AND 95% NW CI excludes 0
- `NULL` per factor: `|t| ≤ 1`
- `EXPLORATORY_SIGNAL` per factor: in between (e.g. `0.0167 < p < 0.317`)
- Aggregate: `PASS_PRELIMINARY` if any factor passes; `NULL` if all NULL; else `CONDITIONAL_PASS`

## Results

| Factor | n | θ̂ | NW SE (lag 3) | NW t | NW p | 95% NW CI | Bonferroni (α=0.0167) | Per-factor verdict |
|---|---:|---:|---:|---:|---:|---:|:---:|:---|
| MTUM | 145 | +0.0164 | 0.0166 | +0.99 | 0.322 | [−0.016, +0.049] | × | **NULL** |
| VLUE | 145 | +0.0178 | 0.0333 | +0.53 | 0.593 | [−0.047, +0.083] | × | **NULL** |
| QUAL | 142 | −0.0065 | 0.0061 | −1.07 | 0.286 | [−0.019, +0.005] | × | **EXPLORATORY_SIGNAL** |

**Aggregate verdict**: `CONDITIONAL_PASS` (all per-factor verdicts are NULL or EXPLORATORY; none Bonferroni-significant). Substantively this is essentially a **NULL** result.

NW SE at lag {1, 6, 12} is stable to within ±10% of the lag-3 value for all factors (see `k1512_results.json`).

### Comparison to n_rep=1 (initial run, pre-Codex)

The single-rep DML showed QUAL θ̂ = −0.0125, NW-t = −2.10, unadjusted p = 0.036 — apparently a marginal signal. With repeated cross-fitting (n_rep=20) the estimate **shrinks to θ̂ = −0.0065, NW-t = −1.07**. **Conclusion**: the n_rep=1 "signal" was fold-randomness artifact, exactly the failure mode Codex flagged. This justifies the n_rep=20 default; researchers using n_rep=1 DML on small monthly panels (n < 200) risk false positives.

## Interpretation

In an ETF-level monthly sample (2014–2026, ≤145 obs), **prior-12m momentum on MTUM, VLUE, and QUAL has no statistically detectable DML-partial association with next-month excess return over SPY** once VIX, term spread (omitted — see caveats), lag-1 SPY return, and lag-1 own return are controlled out via random-forest nuisance learners. The lone borderline factor (QUAL) does **not** survive 3-test multiple-testing correction.

This is consistent with two readings:
1. **Factor "alpha" at ETF level is largely a confounder story** (regime, market vol, momentum-of-the-market). Once a flexible nuisance learner absorbs those, the residual partial effect is statistically zero.
2. **Power is genuinely thin** at n ≤ 145. We cannot rule out small true effects (CI widths ±2–8% per unit of prior-12m return).

Mission alignment: this is a defensible **NULL/CONDITIONAL** preliminary; it does **not** justify a "real factor" claim for a premium-tier dashboard. Follow-up at stock-level panel (Russell 1000 cross-section) would have ~1000× more power per month and could discriminate (1) from (2).

## Limitations / Caveats

- **ETF-level proxy, not stock cross-section**. Cannot disentangle "factor premium" from "ETF-specific noise". K1510-style firm-level panel is the proper next step.
- **D = own prior-12m return**. This is closer to a price-momentum signal than a true value/quality fundamental exposure. For VLUE/QUAL especially, this measures "ETF momentum", not the latent factor.
- **Term-spread control unavailable** — `pandas_datareader` FRED endpoint broke (`deprecate_kwarg() missing 1 required positional argument`). Substituted constant 0 → reduces nuisance-model richness; potential omitted-confounder bias toward residual non-zero θ̂.
- **n ≤ 145 monthly obs** with 2-fold cross-fitting is exploratory; CIs are wide.
- **Same-date VIX / term-spread** controls assume execution after month-end close.
- **No skip-1-month convention** in D (standard momentum drops the most recent month).
- **VIX-regime sub-sample DML** (stretch goal) skipped due to 50-min budget.

## Files

- `k1512.py` — runnable, idempotent, seed=42
- `k1512_results.json` — verdicts, θ̂, all SE variants, per-factor sample windows
- `fig_a_dml_theta_with_ci.png` — θ̂ ± 95% NW CI bar chart
- `k1512_panel.parquet` — raw monthly panel (debug / audit)
- `codex_review.md` — Codex CONDITIONAL_PASS verdict + applied fixes log

## References

1. Chernozhukov, V., Chetverikov, D., Demirer, M., Duflo, E., Hansen, C., Newey, W., Robins, J. (2018). "Double/debiased machine learning for treatment and structural parameters." *Econometrics Journal*, 21(1), C1-C68. — Foundational DML / PLR / Neyman-orthogonal moment.
2. Harvey, C. R., Liu, Y., Zhu, H. (2016). "...and the Cross-Section of Expected Returns." *Review of Financial Studies*, 29(1), 5-68. — Multiple-testing in factor zoo; justifies Bonferroni gating here.
3. Bali, T. G., Goyal, A., Huang, D., Jiang, F., Wen, Q. (2023). "Predicting individual corporate bond returns." *Journal of Finance*, forthcoming. — Modern DML / ML factor-causality on financial returns.
4. Bryzgalova, S., Pelger, M., Zhu, J. (2024). "Forest through the trees: Building cross-sections of stock returns." *Journal of Finance*. — Tree-based nuisance learners on factor cross-sections (justifies RF choice).
5. Newey, W. K., West, K. D. (1987). "A simple, positive semi-definite, heteroskedasticity and autocorrelation consistent covariance matrix." *Econometrica*, 55(3), 703-708. — HAC SE.

## Codex review chain

- 2026-06-16 16:30 — Codex CLI 0.132.0 (gpt-5.4) verdict: **CONDITIONAL_PASS**.
- 5 fixes applied: (1) n_rep=20 repeated cross-fitting, (2) Bonferroni 3-test gate, (3) mean-centered ψ for NW SE, (4) lag-sensitivity NW SE {1,3,6,12}, (5) per-factor sample-window metadata, plus docstring correction. Aggregate verdict downgraded `PASS_PRELIMINARY → CONDITIONAL_PASS` as Codex required.
- Re-run with n_rep=20 reproduced Codex's predicted shrinkage of QUAL signal (NW-t −2.10 → −1.07); the marginal-significance result was indeed a fold-randomness artifact.
