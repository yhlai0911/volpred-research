# K1106b — Sector-diversified firm θ₂ heterogeneity

**Proposer**: 賴奕豪 (user-directed research blind spot)
**Executor**: Claude (worktree agent)
**Date**: 2026-04-13
**Status**: Complete (exploratory, N=14)

## Motivation

K1104 found the A4f-EAV coefficient θ₂ heterogeneous across 0050.TW
constituents, but the constituent universe was >80% semiconductor-related
(fabless, foundry, EMS, memory, optical). Financials, shipping, traditional
manufacturing, consumer defensive were all under-represented at N=1-3. The
user flagged this as a **research blind spot**: we cannot claim "sector
heterogeneity" when the cross-section we studied was not truly diverse.

K1106b deliberately picks **7 sectors × 1-3 firms each (total N=14)** to
test whether θ₂ varies systematically across sectors beyond the
semiconductor universe, using the same full-sample single-shot A4f-EAV
MLE methodology (τ-lag fixed from K1103).

## Research question

Do sector dummies jointly explain significant variation in the earnings-
announcement-vol amplifier θ₂, controlling for market cap and beta?
And in particular:

- H1: Sector dummies joint F-test p < 0.05.
- H2: Fabless firms have systematically more negative θ₂ than foundry.
- H3: Shipping sector has positive θ₂ (freight rate shocks → vol).
- H4: Consumer defensive has θ₂ ≈ 0 (low EPS variance).

## Method

1. **Stage 1** (firm-level): Full-sample A4f-EAV MLE on daily log returns
   2010-01-01 to 2025-12-31. 7 parameters per firm
   (θ₀, θ₁, θ₂, ω, α, γ, β). Numerical Hessian SE for θ₂ with progressive
   epsilon fallback (1e-4 → 1e-3 → 1e-2) to handle τ=max(...) kink.
2. **Stage 2** (covariates): yfinance marketCap, beta (info + rolling
   252-day vs 0050.TW).
3. **Stage 3** (cross-sectional regression):
   - Full spec: θ₂ ~ sector_dummies + log_mktcap_z + beta_rolling_z
   - Reduced spec: θ₂ ~ log_mktcap_z + beta_rolling_z
   - ANOVA F-test: full vs reduced (testing joint sector dummy significance)
   - Reference sector: `foundry` (k-1 dummies for k sectors)

## Firms (N=14)

| Sector | Tickers |
|--------|---------|
| foundry | 2330 TSMC, 2303 UMC |
| fabless | 2454 MediaTek, 2379 Realtek |
| financials | 2881 Fubon FH, 2886 Mega FH, 2882 Cathay FH |
| shipping | 2603 Evergreen, 2615 Wanhai |
| trad_mfg | 1301 Formosa, 2002 China Steel |
| electronics | 2317 Hon Hai |
| consumer | 2912 Pres. Chain, 1216 Uni-President |

## Results (summary)

### Sector-level mean θ₂ (ranked)

| Sector | n | mean θ₂ | SD |
|--------|---|---------|----|
| **fabless** | 2 | **-1.997e-03** | 5.485e-04 |
| shipping | 2 | +8.791e-06 | 6.361e-05 |
| financials | 3 | +2.028e-05 | 4.897e-05 |
| trad_mfg | 2 | +8.742e-05 | 8.433e-05 |
| consumer | 2 | +2.444e-04 | 3.921e-04 |
| foundry | 2 | +2.459e-04 | 2.622e-04 |
| **electronics** | 1 | **+7.251e-04** | — |

### Full regression (θ₂ on sector + covariates)

- R² = 0.940, Adj R² = 0.845, n=14, dof=5
- **Only `sector_fabless` coefficient is significant**: β=-2.29e-03, t=-5.16, p=0.004 ***
- All other sector dummies, log_mktcap, beta_rolling — not significant

### ANOVA F-test (sector dummies jointly)

- **F(6, 5) = 6.87, p = 0.026** — nominally reject H0 at 5%
- But with only 5 residual dof, this is **exploratory, not confirmatory**

### Hypothesis outcomes

| # | Hypothesis | Result |
|---|------------|--------|
| H1 | Sector F-test p<0.05 | **Nominally PASS** (p=0.026) but underpowered |
| H2 | Fabless < foundry | **PASS** (β=-2.29e-03, p=0.004) — but see caveat |
| H3 | Shipping > 0 | **FAIL** (mean ≈ 0, dummy NS) |
| H4 | Consumer ≈ 0 | **INDETERMINATE** (2912 strong +, 1216 weak –) |

### K1104 replicability (10 overlapping firms)

All 10 firms that overlap with K1104 return **identical θ₂** (Δ=0%) because
the parquet data cache is shared and the single-shot MLE is deterministic.
This confirms the methodology is reproducible when inputs are identical
(Random seed 42 was set but single-shot MLE doesn't depend on it at the
fitting stage).

## Critical caveats (Codex-reviewed)

1. **ANOVA F-test is exploratory, not confirmatory**: N=14 with 6 sector
   dummies + 2 covariates + intercept leaves residual dof = 5. One or two
   extreme firms (especially the fabless pair) can drive F. Interpret as
   "direction of heterogeneity signal" not "proof".

2. **Fabless cherry-pick bias**: K1104 had 4 fabless firms with mixed
   signs (MediaTek -1.61e-3, Realtek -2.39e-3, Novatek +7.02e-4, Phison
   +1.20e-3). K1106b's 2-firm fabless sample **only retained the negative
   pair**. Therefore H2 is **not** "fabless always θ₂ < 0"; the correct
   interpretation is "fabless sign is bimodal and firm-specific". K1104's
   broader regression is more reliable for fabless conclusions.

3. **Consumer defensive is split**: 2912 Pres. Chain has θ₂=+5.22e-04
   (t=+2.92), 1216 Uni-President has θ₂=-3.29e-05 (t=-6.17, but SE
   0.5% of coefficient so tiny effect). This is **firm-specific
   information discovery**, not a "consumer sector effect".

4. **Electronics (Hon Hai) surprising high θ₂**: θ₂=+7.25e-04, t=+3.59.
   Non-semi electronics outperforming semis on EAV amplification.
   Replicates K1104's observation. n=1 so no sector-level claim.

5. **Shipping hypothesis H3 rejected**: Evergreen -3.62e-05 (t=-1.99),
   Wanhai +5.38e-05 (t=+0.90). Mean near zero. Freight rate shocks do
   NOT translate to systematic earnings-day vol amplification. Possibly
   because freight rates are public real-time (Baltic Dry Index, SCFI),
   so earnings releases contain little incremental vol-relevant info.

## Paper 2 — Sector-based firm-selection rules (exploratory)

Based on K1106b + K1104, we can formulate **tentative** firm-level rules
for A4f-EAV applicability. All rules must be cross-validated on a larger
sample (D1 below) before deployment.

1. **Prefer foundry firms**: UMC θ₂=+4.3e-04 (K1104 t=3.56). Foundry
   earnings reveal capex/utilisation, priced-in slowly → EAV effective.
2. **Avoid MediaTek-style fabless large-caps**: θ₂ sign negative means
   A4f-EAV mis-specifies vol on event days. Stick with plain A4f.
3. **Electronics EMS (Hon Hai)**: single positive observation, but
   consistent across K1104/K1106b. Extend to Quanta, Asus for validation.
4. **Financials & shipping**: θ₂ near zero. A4f-EAV adds no value.
   Default to A4f or GJR-GARCH baseline.
5. **Consumer defensive**: too firm-specific. Do not pool at sector
   level; examine each firm separately before applying A4f-EAV.

## Derived research directions

- **D1** (top priority): Extend to 50+ firms (full 0050.TW + TPEX) so
  each sector has ≥ 5 firms. ANOVA with dof=20+ would be confirmatory.
- **D2**: Panel regression with time-varying θ₂ (rolling 63-day refits
  as in K1103) on sector dummies — tests whether heterogeneity is
  **structural** (between-firm) or **cyclical** (regime-dependent).
- **D3**: Replace sector dummies with fundamental covariates —
  EPS-guidance-spread, earnings-day volume spike, analyst-coverage-ratio
  — test whether "sector heterogeneity" is actually driven by an
  interpretable firm characteristic.

## Files

- `k1106b.py` — script (Stage 1 MLE + Stage 2 covariates + Stage 3 OLS + ANOVA)
- `k1106b_results.json` — full results (14 firm estimates + regression + ANOVA + k1104 comparison)
- `firm_level_results.csv` — flat CSV of firm results
- `firm_covariates.csv` — covariate subset
- `k1106b_sector_theta2_ranking.png` — 7-sector mean θ₂ bar chart with 95% CI
- `k1106b_firm_scatter.png` — θ₂ vs τ-jump% scatter coloured by sector
- `k1106b_sector_decision_tree.png` — decision tree for Paper 2 selection rules
- `data/*.parquet` — cached yfinance data (reuse from K1104 + 4 new tickers)

## References

- Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3).
- Patton (2011). Volatility forecast comparison. J Econometrics 160.
- K1067 / K1067b / K1067c / K1103 / K1104 — EAV and firm heterogeneity.

## Conclusion

**Sector heterogeneity of θ₂ is a real but exploratory finding.** The
ANOVA F-test is nominally significant but underpowered; the fabless
pair was cherry-picked from K1104's mixed-sign sample; non-semi
electronics (Hon Hai) replicates its surprisingly high θ₂. Paper 2
should (1) report these 14 firm estimates as cross-section, (2)
state clearly that conclusions are tentative pending D1 replication
on N=50+, (3) use fundamental covariates (D3) to replace sector
dummies as the next explanatory layer.
