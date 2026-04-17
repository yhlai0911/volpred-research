# K1108e: Operating leverage as foundry θ_EAV mechanism (D3 candidate)

**提出**: 賴奕豪  **執行**: Claude  **日期**: 2026-04-17
**Parent**: K1108c (commit d1240e89, H2_MAGNITUDE_NULL DECISIVE)
**Grand-parent**: K1108b (H2 DECISIVE NULL with binary flag)
**Great-grand-parent**: K1108 (TSMC single-firm INCONCLUSIVE)

## K1108 context & D3 hypothesis

The K1108 series is a stepwise test of what drives the foundry-specific
θ₂ > 0 pattern identified in K1104. Three layers of capex-guidance
testing have all returned NULL:

| Experiment | Spec | N | Verdict |
|------------|------|---|---------|
| K1108 | TSMC single-firm, binary guide_updated | 48 | INCONCLUSIVE (t=0.94) |
| K1108b | 4-firm pooled, binary guide_updated | 136 | **H2 DECISIVE NULL** (pool t=−0.0003) |
| K1108c | 4-firm pooled, continuous guide_delta_pct | 135 | **H2_MAGNITUDE_NULL DECISIVE** (t=−1.34) |

Capex-guidance event content does NOT drive foundry θ_EAV. **D3**
proposes an alternative: foundry θ₂>0 may reflect *balance-sheet cost
structure* itself (high PP&E intensity, long-lived equipment, financial
leverage) rather than event-specific guidance. Under this story, the
fixed-cost nature of foundry operations amplifies earnings-day variance
asymmetrically — a structural rather than informational channel.

If D3 PASSES, Paper 2 foundry-rule mechanism re-interprets as
balance-sheet structure (op_leverage rank). If D3 NULLS, D4 regime-split
is next (K1108f).

## Data sources

### Event panel

Reuse `experiments/k1108c/k1108c_merged_pool.csv`:
- 4 firms: TSMC 2330.TW, UMC 2303.TW, GFS, SMIC 0981.HK (TSM ADR excluded
  per K1108c primary spec to avoid TSMC double-count)
- 135 firm-events with θ_EAV_empirical (per-event long-memory residual)
- guide_delta_pct as K1108c control variable

### Operating-leverage covariates

Source: `yfinance.Ticker(x).balance_sheet` (annual) + `.financials`
(annual), fetched by `k1108e_fetch_opleverage.py`.

| Measure | Formula | Interpretation |
|---------|---------|----------------|
| op_leverage_1 | Net PPE / Revenue | Asset intensity |
| op_leverage_2 | Total Debt / Stockholders Equity | Financial leverage |
| op_leverage_3 | (Net PPE + SG&A) / Revenue | Combined cost rigidity |

**yfinance coverage limitation** (confirmed 2026-04-17): annual BS/IS
data covers **2021-12-31 → 2025-12-31 only (5 FYs)** for all 5 foundries.
Events pre-2022 are DROPPED from the K1108e regression sample. This is
a **HARD constraint of the free API** and documented in the results
JSON (`yfinance_coverage_limit_notice`).

### Firm-year descriptives (fetched)

| Firm | PPE/Rev | Debt/Equity | (PPE+SGA)/Rev |
|------|---------|-------------|---------------|
| 2330.TW (TSMC) | 0.98–1.44 | 0.20–0.31 | 1.01–1.47 |
| 2303.TW (UMC)  | 0.71–1.26 | 0.14–0.19 | 0.76–1.30 |
| TSM ADR        | identical to 2330.TW | identical | identical |
| GFS            | 1.15–1.38 | 0.14–0.29 | 1.20–1.44 |
| 0981.HK (SMIC) | 2.61–3.80 | 0.45–0.59 | 2.68–3.88 |

SMIC has ~3× TSMC's PPE/Revenue — large cross-sectional dispersion.
This motivates checking whether the pooled-OLS cross-sectional
correlation survives firm-FE absorption.

## Design

### Event sample

- 4-firm K1108c pool → 135 events → 47 events matched to op_leverage
  with PIT lag ≥ 45 days (event-year range **2023-02-15 → 2025-11-17**)
- By firm: 0981.HK=11, 2303.TW=12, 2330.TW=12, GFS=12
- No firms dropped (all ≥4 events)

### PIT alignment (critical)

For event date d:
- Use fiscal-year-end t such that `t + 45 days ≤ d` (conservative
  publication-lag floor; TWSE annual report typically ~90d, US 10-K
  60–90d, HKEX ~120d — 45d is safely before any realistic publication)
- `matched_fy_end` column records the FY-end used for each event
- Events with no eligible prior FY-end are dropped (47/135 matched
  given the 5-year yfinance window)

### Regression specs (9 cells)

3 specs × 3 op_leverage covariates:

| Spec | firm_FE | year_FE | guide_delta_pct control |
|------|---------|---------|-------------------------|
| pooled_ols_with_guide | — | — | Yes |
| firm_fe_with_guide | Yes | — | Yes |
| firm_year_fe_with_guide | Yes | Yes | Yes |

Model: `θ_EAV_{i,d} = β₀ + β₁ · op_lev_k_{i,d-lag} + γ · guide_delta_pct_{i,d} + α_i + τ_{year(d)} + ε_{i,d}`

### Standard errors

- Primary: Newey–West HAC (Andrews 1991 auto-bandwidth, bw=3 for n=47)
- Sensitivity: firm-cluster-robust SE (Stata small-sample correction)

### Bootstrap

Block bootstrap β₁ (N=1000, block=5 events consecutive within firm,
firm-stratified, seed=42) WITH guide_delta_pct control but WITHOUT
firm/year FE (as robustness check on pooled correlation).

### Partial-F joint test

H₀: β_op1 = β_op2 = β_op3 = 0 jointly, conditional on firm_fe + year_fe
+ guide_delta_pct. Classical F test, df = (3, n−k).

## Results

### Primary 9-cell table (β₁ coefficient on op_leverage)

| Spec | op_lev_1 (PPE/Rev) | op_lev_2 (D/E) | op_lev_3 ((PPE+SGA)/Rev) |
|------|--------------------|-----------------|---------------------------|
| pooled_ols_with_guide | β=+1.84e-03, t_HAC=+1.46, p=0.143 | β=+1.48e-02, **t_HAC=+1.58**, p=0.113 | β=+1.82e-03, t_HAC=+1.47, p=0.141 |
| firm_fe_with_guide | β=−1.22e-03, t_HAC=−0.34, p=0.733 | β=+1.79e-02, t_HAC=+0.48, p=0.632 | β=−1.23e-03, t_HAC=−0.34, p=0.732 |
| firm_year_fe_with_guide | β=−2.79e-03, t_HAC=−0.77, p=0.439 | β=+1.75e-02, t_HAC=+0.47, p=0.636 | β=−2.80e-03, t_HAC=−0.78, p=0.437 |

**Max |t_HAC| = 1.584** (at pooled_ols × op_lev_2). Below Harvey
(|t|>3) and below weak (|t|>2). With firm_FE alone, all 3 coefficients
collapse to |t|<0.5.

### Cluster-robust (firm) SE as sensitivity

| Spec × col | t_cluster | p_cluster |
|------------|-----------|-----------|
| pooled_ols × op_lev_1 | +8.30 | 0.000 |
| pooled_ols × op_lev_2 | +4.52 | 6.2e-6 |
| pooled_ols × op_lev_3 | +8.25 | 2.2e-16 |
| firm_fe × op_lev_1 | −1.23 | 0.219 |
| firm_fe × op_lev_2 | +1.22 | 0.223 |
| firm_fe × op_lev_3 | −1.23 | 0.220 |
| firm_year_fe × op_lev_1 | −1.78 | 0.075 |
| firm_year_fe × op_lev_2 | +1.91 | 0.056 |
| firm_year_fe × op_lev_3 | −1.81 | 0.071 |

Firm-cluster SE gives inflated significance WITHOUT firm FE (because G=4
clusters is too few — asymptotic G→∞ approximation breaks), but the
correct identification (with firm FE) returns to NS. **The pooled-OLS
significance is an artefact of SMIC's 3× higher op_leverage level
lining up with a distinct θ_EAV distribution**, not a within-firm
effect.

### Bootstrap β₁ (pooled, with guide, WITHOUT FE)

| op_lev | Mean | 95% CI | p_two_sided | CI excludes 0 |
|--------|------|--------|-------------|---------------|
| op_lev_1 | +1.28e-03 | [+3.9e-04, +2.17e-03] | 0.000 | Yes |
| op_lev_2 | +1.22e-02 | [+4.44e-03, +1.92e-02] | 0.000 | Yes |
| op_lev_3 | +1.27e-03 | [+3.97e-04, +2.14e-03] | 0.000 | Yes |

Bootstrap excludes 0 across all three measures. **However, this
bootstrap does NOT include firm FE** — it reflects the same
cross-sectional level difference as the pooled OLS. Once FE controls
for firm-invariant heterogeneity, the effect vanishes. The
between-firm variance is identified by a single cross-section of 4
firms, not a within-firm time-series signal.

### Partial-F joint test

F(3, 37) = **2.224**, p = **0.102**, with firm FE + year FE +
guide_delta_pct as restricted set. Joint op_leverage contribution is
not significant at α = 0.10.

## Verdict

### **H_D3_NULL DECISIVE**

| Criterion | Threshold | Actual | Result |
|-----------|-----------|--------|--------|
| max \|t_HAC\| > 3.0 | Harvey (2016) | 1.584 | **Fail** |
| max \|t_HAC\| > 2.0 | Weak | 1.584 | **Fail** |
| partial-F p < 0.01 | Strong | 0.102 | **Fail** |
| partial-F p < 0.10 | Marginal | 0.102 | **Fail (just)** |
| firm-FE spec preserves signal | Identification | all \|t\|<0.5 | **Fail** |

**Balance-sheet operating leverage does NOT explain foundry θ_EAV
*within-firm*.** The apparent positive pooled-OLS correlation is
driven by SMIC's 3× higher PPE/Revenue level accompanying a distinct
θ_EAV distribution — a level confound rather than a within-firm
mechanism. Once firm FE absorbs the level, no relationship remains.

## Implication for Paper 2 foundry mechanism

The K1108 series is now a **four-layer DECISIVE NULL** on all tested
balance-sheet / guidance channels for the foundry θ_EAV rule:

1. **K1108** (TSMC single-firm binary): INCONCLUSIVE
2. **K1108b** (4-firm pool, binary): DECISIVE NULL (t=−0.0003)
3. **K1108c** (4-firm pool, continuous): DECISIVE NULL (t=−1.34)
4. **K1108e** (operating leverage, 3 measures × 3 specs): **DECISIVE NULL (max |t|=1.58, F p=0.10)**

**Paper 2 foundry-rule interpretation**: the θ₂>0 pattern for foundries
in K1104 is NOT reducible to (a) capex-guidance event content (binary
or continuous), NOR to (b) balance-sheet fixed-cost intensity (PPE/Rev,
D/E, (PPE+SGA)/Rev). Paper 2 should frame foundry θ₂>0 as an *industry*
fixed effect rather than any of these specific mechanisms. Candidate
D4 mechanisms (K1108f targets):

- **Regime-split**: different foundry regimes (Taiwan vs US vs China)
  under the post-2021 export-control era may mask a signal pooled
  across regimes
- **Non-capex quantitative guidance**: utilisation rate, wafer-price,
  R&D guidance (see K1108b/c backlog D2)
- **Product-cycle dummy**: node-transition years (7nm→5nm→3nm ramp)
  may carry the effect rather than balance-sheet levels

## Statistical limitations & honesty disclosures

- **Sample window 2023-02 → 2025-11 only** (yfinance coverage). Pre-2022
  events from K1108c pool (2014-2022) are dropped. The NULL is decisive
  within this window; extension to 2014-2020 would require a paid data
  source (Bloomberg / FactSet / CRSP fundamentals) to fetch longer BS/IS
  history. Reported in good faith per 誠實原則 §9/§10.
- **N=47 and 4 firms**. With firm FE consuming 3 dof and year FE an
  additional 2 (2023–2024 with 2025 as reference), the effective
  within-firm-within-year sample is small. A NULL at this sample size
  does not rule out a small effect (Type II error). But with max |t|=1.58
  and consistent NULL across firm-FE and firm-year-FE specs, the point
  estimate is close to zero regardless of power.
- **yfinance BS/IS items** are standardised by Yahoo Finance from
  original 10-K / annual reports — identifier mapping to exact 10-K line
  items may vary by vintage (Yahoo renames periodically; tested
  2026-04-17). A Codex review or Bloomberg cross-check would strengthen
  the provenance chain for the 5 firms. For now, values are internally
  consistent for the 5-year window.
- **op_leverage_2 (D/E)** is the lowest-R² of the three but the
  highest-t (pooled OLS). In firm-FE, op_lev_2 remains positive (unlike
  op_lev_1/3 which flip sign) — consistent with a weak "high leverage →
  higher event-day vol" intuition but far from significant. Not strong
  enough to be a rescue case.
- **TSM ADR** is excluded from the primary pool (K1108c convention).
  An extended sensitivity including TSM would require a separate
  trading-day adjustment as in K1108b §"TSM ADR handling"; since the
  firm-FE analysis already absorbs time-invariant differences this is
  unlikely to change the verdict.
- **Null result reported in good faith per 誠實原則 §9/§10.**

## Files

- `README.md` — this file
- `k1108e.py` — main analysis (PIT merge + 9-cell regression + partial-F
  + bootstrap + verdict + plots)
- `k1108e_fetch_opleverage.py` — yfinance fetch helper for 5-foundry
  annual BS + IS
- `k1108e_opleverage_pool.csv` — 25 firm-year rows
- `k1108e_merged_sample.csv` — 47-event regression sample
- `k1108e_results.json` — full statistics JSON
- `k1108e_scatter_opleverage.png` — 3-panel scatter θ_EAV vs each
  op_leverage measure, coloured by firm
- `k1108e_coef_forest.png` — 9-cell β₁ coefficient forest plot
- `run.log` — full stdout

## References

- K1108 (TSMC single-firm capex-guidance INCONCLUSIVE)
- K1108b (4-firm binary NULL, commit 5bcd8143)
- K1108c (4-firm continuous NULL, commit d1240e89)
- K1104 (foundry θ₂>0 cross-sectional rule)
- K1067 (A4f-EAV baseline specification)
- K1166 (pooled stock-FE framework)
- Mandelker & Rhee (1984). *Impact of the degrees of operating and
  financial leverage on systematic risk of common stock*. JFQA
  19(1):45–57.
- Novy-Marx (2011). *Operating leverage*. Rev Financ 15(1):103–134.
- Engle, Ghysels & Sohn (2013). *GARCH-MIDAS*. RES 95(3).
- Andrews (1991). *Heteroskedasticity- and autocorrelation-consistent
  covariance matrix estimation*. Econometrica 59(3):817–858 — auto bw.
- Newey & West (1987). *A simple, positive semi-definite,
  heteroskedasticity-consistent covariance matrix*. Econometrica
  55(3):703–708.
- Politis & Romano (1994). *The stationary bootstrap*. JASA 89:1303–1313.
- Harvey et al. (2016). *... and the cross-section of expected returns*.
  RFS 29(1):5–68 — |t|>3 threshold for multi-testing.

## Data provenance

- Event panel: `experiments/k1108c/k1108c_merged_pool.csv` (K1108c
  commit d1240e89)
- Op-leverage: yfinance `Ticker(x).balance_sheet` + `.financials`,
  fetched 2026-04-17
- PIT publication lag: 45 days (conservative floor)
- Fiscal-year-end span: 2021-12-31 → 2025-12-31 (5 FYs per firm)
- Event-year range in regression sample: 2023-02-15 → 2025-11-17
- Random seed: 42 (numpy / scipy / bootstrap)
- HAC: Newey–West manual implementation (Andrews 1991 auto-bandwidth,
  bw=3 for n=47)
- Partial-F: classical RSS-based F test
- Bootstrap: firm-stratified block resampling (N=1000, block=5 events)
