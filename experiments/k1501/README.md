# K1501 — VRP Upside/Downside Decomposition × Horizon Predictability (SPY)

**Final Verdict: MIXED** (Codex review: CONDITIONAL_PASS — methodology clean; interpretive caveat on proxy decomposition.)

**Reviewer**: Codex CLI 0.139.0 (gpt-5.4), 2026-06-15.

## Research question

Does decomposing the variance risk premium (VRP) into upside (`VRP_up`) and
downside (`VRP_down`) components — built from realized semivariance shares
applied to implied variance — yield differential predictive power for SPY
returns across horizons {1, 21, 63, 126} trading days? And are the two
sign-specific premia in fact reverse-signed (negatively correlated)?

Differentiation from related K's:

| K | Result | Difference from K1501 |
|---|---|---|
| K430 | VRP IS significant; OOS DM null | Total VRP only, no decomposition |
| K450 | VRP + semivariance — no synergy | Adds semivar as 2nd regressor; not VRP-internal split |
| K190/K453/K460 | Realized semivariance pred RV | Pure RV target, not return; no VRP component |
| K459 | Weekly VRP cross-OOS 5 periods | Total VRP weekly, no up/down split |
| K1476 | TAIFEX OFI → RV (intraday) | Unrelated topic (OFI intraday TAIFEX) |

K1501's new angle: structure WITHIN VRP — does the downside leg do the work?

## Hypotheses (final form actually tested)

**H1 (Asymmetry)**: Monthly downside semivariance RV-² has a significantly
higher mean than upside RV+² (Welch t-test, plus mean-difference HAC-NW lag=3
robustness).

**H2 (Predictive power across horizons)**: For h ∈ {1, 21, 63, 126} trading
days, regress forward log return `log(P_{t+h}) - log(P_t)` on each lagged
predictor X_t at month-end t, with HAC NW lag = h+1. Predictors:
`{rv_up², rv_dn², vrp_total, vrp_down, vrp_up}`. Compare β_down vs β_up
under stationary block bootstrap.

**H3 (VRP sign decomposition)**: Build
`VRP_down_t = θ_dn,t · IV²_{t-1} − RV-²_t`,
`VRP_up_t   = θ_up,t · IV²_{t-1} − RV+²_t`,
where θ_dn is the 12-month TRAILING share `Σ RV-²_{t-12..t-1} / Σ RV_tot²_{t-12..t-1}`
(strictly ex-ante). Test: (a) corr(VRP_down, VRP_up) < 0 (reverse-sign as proxy
of news-shock asymmetry decomposition); (b) additivity VRP_down + VRP_up ≈
VRP_total (consistency check on the construction).

## Data

- `^GSPC` daily Close — yfinance, 2006-01-01 to 2026-05-31 (downloaded
  2026-06-15 UTC).
- `^VIX` daily Close — yfinance, same window.
- Aggregation: `ME` (month-end) resample. Monthly IV² = (VIX_eom/100)² / 12.
- Final monthly panel: **n = 244 months** (2006-02-28 to 2026-05-31).
- Horizon regression effective n: 232 / 231 / 230 / 226 for h = 1 / 21 /
  63 / 126.

## Lookahead controls (HARD)

| Item | Mechanism |
|---|---|
| IV ex-ante | `iv_monthly_lag1 = iv_monthly.shift(1)` — month-t IV comes from VIX at end of t-1. |
| θ ex-ante | `theta_dn = rv_dn².shift(1).rolling(12, min_periods=12).sum() / rv_tot².shift(1).rolling(12).sum()` — uses ONLY months t-12 … t-1. |
| Forward return | `searchsorted(month_end, side="right") - 1` → last trading day at/before month-end, then `+h` trading days ahead. No overlap with X_t. |
| HAC NW lag | `h + 1` for horizon-h overlapping return regressions. |
| Bootstrap | Single module-level `np.random.default_rng(42)`; stationary block bootstrap with `block_len = max(2, ceil(h/21)·2 + 2)`. |

## Results

### H1 — Asymmetry

| Stat | Value |
|---|---|
| mean(RV-²) | 0.001662 |
| mean(RV+²) | 0.001486 |
| mean(RV-² − RV+²) | +0.000176 |
| Welch t p-value (two-sided) | 0.590 |
| HAC NW lag=3 mean-diff p-value | 0.109 |

**H1 verdict: NULL.** Downside mean is numerically higher (+12%), consistent
with the literature direction, but neither Welch nor HAC NW achieves
conventional significance over the 2006-2026 SPY monthly sample. Most of the
gap originates from a handful of crisis months (2008, 2020-03) but is diluted
by 200+ tranquil months.

### H2 — Horizon predictive regressions

HAC NW t-stats (β coefficient, two-sided p in parentheses), R² in last block.

| Horizon | n | t(rv_up²) | t(rv_dn²) | t(VRP_total) | t(VRP_down) | t(VRP_up) | R²(VRP_dn) | R²(VRP_up) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1d   | 232 | −1.30 | −0.90 |  3.80*** |  4.20*** |  2.52** | 0.054 | 0.049 |
| 21d  | 231 |  0.21 |  0.96 |  0.55    |  0.61    |  0.43   | 0.018 | 0.006 |
| 63d  | 230 |  0.27 |  0.85 |  0.47    |  0.51    |  0.42   | 0.010 | 0.005 |
| 126d | 226 | −0.16 |  0.61 |  0.12    |  0.21    | −0.04   | 0.001 | 0.000 |

Stars: `*** p<0.01, ** p<0.05` under HAC NW.

Bootstrap (β_down − β_up) two-sided p:

| Horizon | mean(β_dn − β_up) | 95% CI | p two-sided |
|---:|---|---|---|
| 1d   |  ≈ + | spans 0 | 0.56 |
| 21d  | ≈ + | spans 0 | 0.56 |
| 63d  | ≈ + | spans 0 | 0.81 |
| 126d | ≈ + | spans 0 | 0.20 |

**H2 verdict: PARTIAL.**
- At **1-day** horizon, both VRP_down and VRP_up are individually significant
  predictors of next-day return (t=4.20 and t=2.52). VRP_down's coefficient
  magnitude is consistently larger than VRP_up's at every horizon, but the
  bootstrap difference test never rejects equality.
- At horizons ≥ 21 days the predictive power **collapses to null** for all
  five regressors. This contradicts the brief's prior of "power concentrated
  3-5 months" and is consistent with K430's IS-significant / OOS-null finding
  for total VRP — the 1-day reflex is the main empirical signal, not a
  quarterly-horizon return premium.
- The Bonferroni-adjusted min-p across 8 H2 tests (VRP_down/up × 4 horizons)
  is p_min·8 = 0.000031·8 ≈ 2.5e-4 → "H2_strong" by the internal Harvey rule,
  driven entirely by h=1.

### H3 — Sign decomposition consistency & sign

| Stat | Value |
|---|---|
| corr(VRP_down, VRP_up) | **+0.879** |
| Fisher-z p (corr ≠ 0) | < 0.001 |
| mean abs(VRP_total − (VRP_down + VRP_up)) | 2.4e-19 (numerical zero) |
| corr(VRP_total, VRP_down + VRP_up) | 1.000 |

**H3 verdict: NULL on the sign hypothesis; PASS on additivity.**
- Additivity check: VRP_down + VRP_up ≡ VRP_total identically (because
  θ_dn + θ_up = 1 by construction, so the IV terms add to IV_{t-1}). This
  is a sanity check, not a discovery.
- Sign hypothesis **rejected**: VRP_down and VRP_up are *highly positively*
  correlated (ρ = +0.88), not negatively. This is mechanically driven: in
  the construction, both legs share the same IV_{t-1} input scaled by θ
  shares which move slowly (12m rolling); the realized leg dominates
  cross-sectional variation, so a high-RV month makes BOTH RV-² and RV+²
  large, lowering both VRP_down and VRP_up together.
- **Interpretation**: a θ-based decomposition cannot produce reverse-signed
  premia. To get a true sign-reverse decomposition would require option-
  implied downside variance (e.g. from put-only or moment-based extraction
  à la Kilic & Shaliastovich 2019), which the K1501 data scope does not
  include.

## Verdict logic

Internal Harvey (2016) + Bonferroni rule applied:
- H1: weak (HAC p = 0.11) — neither strong nor weak threshold met.
- H2: strong (h=1 dominates Bonferroni 8 tests).
- H3 corr: rho ≠ 0 strongly significant **but in the wrong direction** vs
  hypothesis prior — counted as null on the substantive claim, even though
  the test statistic is highly significant.

→ Internal rule output: **MIXED**.

Codex review verdict: **CONDITIONAL_PASS** — methodology clean; conditional
caveat: VRP_down/VRP_up here are *proxy* decompositions using trailing
realized shares of total RV, not directly observed option-implied
sign-specific premia. Conclusions must not imply observed option-implied
sign-specific VRP.

Final K1501 verdict: **MIXED** with explicit interpretive caveat retained.

## Implications and follow-up

1. **VRP's 1-day return reflex is real and meaningful** (t > 4 for downside
   leg, t > 2.5 for upside leg, n=232). At weekly+ horizons there is no
   exploitable cross-section in any of the 5 regressors — corroborates K430.
2. **θ-share decomposition is not a substitute** for option-implied sign
   extraction. To test the true reverse-sign hypothesis, K1501-followup must
   use option-implied downside variance (CBOE SKEW, moment extraction from
   option prices, or replicate Kilic-Shaliastovich downside).
3. **Asymmetry at the mean level is weaker than expected** in the 2006-2026
   SPY sample — the canonical "RV- > RV+" stylised fact (Bekaert-Hoerova
   2014; Feunou-Jahan-Parvar-Tedongap 2013) survives in sign but loses
   statistical significance in this 244-month window.

## Files

- `k1501.py` — reproducible script (`uv run python experiments/k1501/k1501.py`)
- `k1501_results.json` — all numerics, hypothesis blocks, lookahead doc,
  reviewer record
- `figs/H1_semivariance_dist.png` — RV+ vs RV- monthly distribution
- `figs/H2_horizon_betas.png` — t-stats of VRP_down vs VRP_up across horizon

## References

1. Bollerslev, T., Tauchen, G., Zhou, H. (2009). *Expected stock returns and variance risk premia.* Review of Financial Studies 22(11), 4463-4492.
2. Feunou, B., Jahan-Parvar, M. R., Tedongap, R. (2013). *Modeling market downside volatility.* Review of Finance 17(1), 443-481.
3. Bekaert, G., Hoerova, M. (2014). *The VIX, the variance premium and stock market volatility.* Journal of Econometrics 183(2), 181-192.
4. Barndorff-Nielsen, O. E., Kinnebrock, S., Shephard, N. (2010). *Measuring downside risk: realised semivariance.* In Volatility and Time Series Econometrics (eds. Bollerslev, Russell, Watson).
5. Kilic, M., Shaliastovich, I. (2019). *Good and bad variance premia and expected returns.* Management Science 65(6), 2522-2544.
