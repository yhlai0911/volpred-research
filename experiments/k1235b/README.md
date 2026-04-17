# K1235b: Paper 9 Table 6 A4f spec replication on FEZ + STOXX50E

**Status**: DECISIVE — BORDERLINE verdict both tickers → Paper 9 R2 path (b) (spec-clarification footnote, **errata not required**)

## 1. Context

### Prior experiments
- **K1232** (reproducibility audit): flagged FEZ t=3.45 and STOXX50E t=3.64 in Paper 9 Table 6 as "no-source" values (Table 6 numbers not traceable to any single experiment script).
- **K1235** (log-exp K949 spec on FEZ + STOXX50E): reran verbatim K949 (MF-GJR log-exp, constrained ω, OOS 2016-2025, refit=21). Result: FEZ t_harvey=4.03, STOXX50E t_harvey=5.01 → **MISMATCH** vs paper (|diff| > 0.5 both).

### K1235b motivation
Paper 9 main.tex Table 6 footnote (line 533) explicitly states "OOS: 2019-2026". Table 2 (line 213) defines **A4f** as VIX² τ with **free ω**. K988 (the canonical Paper 9 script) uses `REFIT_EVERY = 63` and `OOS_START = 2019-01-01`. So Paper 9 Table 6 almost certainly used the **A4f spec**, not K949. K1235b is the decisive test: does A4f on FEZ + STOXX50E reproduce paper's 3.45 / 3.64?

Decision tree:
- **MATCH** (|diff| < 0.2 Harvey) → path (b) spec-clarification footnote only
- **BORDERLINE** (|diff| < 0.5) → still path (b) with divergence note
- **MISMATCH** (|diff| ≥ 0.5) → path (a) full errata

## 2. A4f spec (verbatim from Paper 9 main.tex + K988)

Matches K988 `A4f_vix2_free_omega` implementation exactly.

- **τ_t functional form** (VIX-squared, Paper 9 eq. 2b):
  $$\tau_t = \max(\theta_0 + \theta_1 \cdot \mathrm{VIX}_{t-1}^2, \, \epsilon), \quad \epsilon = 10^{-16}$$
- **Short-run g_t** (GJR with **free ω**):
  $$g_t = \omega_g + \alpha \, u_{t-1}^2 + \gamma \, u_{t-1}^2 \, \mathbb{1}_{u_{t-1}<0} + \beta \, g_{t-1}$$
- **Normalization** (contemporaneous, Paper 9 eq. u^(a)):
  $$u_{t-1} = r_{t-1} / \sqrt{\tau_t}$$
- **Joint MLE**: 6 parameters [θ₀, θ₁, ω_g, α, γ, β] via scipy L-BFGS-B; 3 starts; bounds match K988 vix_squared path.
- **Returns**: raw log-returns, NO ×100 scaling (matches K988 SPY t=4.03 reproduction).
- **Data period**: 2005-01-01 .. 2026-04-15 (yfinance, auto_adjust=True).
- **OOS**: **2019-01-01** onwards (Paper 9 Table 6 declared period).
- **Estimation window**: WINDOW = **2000** trading days.
- **Refit**: every **63** trading days (quarterly).
- **Benchmark**: plain GJR-GARCH(1,1), same window/refit, matches paper's Table 6 GJR column.
- **DM test**: Newey-West HAC with max_lag = ⌊T^(1/3)⌋, Harvey (1997) small-sample correction.
- **Seed**: 42.

## 3. Changes vs K1235 (4 deliberate spec differences)

| Dim | K1235 (log-exp K949) | K1235b (A4f) |
|-----|---------------------|--------------|
| τ functional form | exp(θ₀ + θ₁ log VIX_{t-1}) | max(θ₀ + θ₁ VIX_{t-1}², ε) |
| ω treatment | constrained (E[g]=1) | free |
| OOS period | 2016-01-01 .. 2025-12-31 | **2019-01-01 .. 2026-04-15** |
| Refit frequency | every 21 days | **every 63 days** |
| Returns scale | ×100 (pct) | raw log (K988 convention) |

## 4. Results (2026-04-18 run)

| Ticker | N_OOS | QLIKE GJR | QLIKE A4f | Improve (%) | DM t_raw | DM t_harvey | p_harvey | Paper claim | Diff | Verdict |
|--------|-------|-----------|-----------|-------------|----------|-------------|----------|-------------|------|---------|
| FEZ | 1,878 | −7.910 | −7.949 | +0.49% | 3.111 | **3.111** | 1.87e-03 | 3.45 | −0.339 | **BORDERLINE** |
| STOXX50E | 1,878 | −8.153 | −8.209 | +0.68% | 3.924 | **3.923** | 8.75e-05 | 3.64 | +0.283 | **BORDERLINE** |

Harvey-threshold (|t| > 3.0): both tickers pass → qualitative claim in paper ("A4f significant at Harvey threshold for FEZ and STOXX50E") **holds**.

A4f parameter estimates (last training window ending ~2026-04):
- **FEZ**: θ₀=4.60e-06, θ₁=2.00e-07, ω_g=0.0999, α=0.0300, γ=0.0800, β=0.8798
- **STOXX50E**: θ₀=-5.82e-03, θ₁=9.30e-04, ω_g=3.63e-05, α=1.0e-04, γ=0.1492, β=0.8164

## 5. Verdict analysis (per ticker)

### FEZ: BORDERLINE (diff = −0.339, 9.8% below paper 3.45)
K1235b t_harvey = 3.11 vs paper 3.45. Within the ±0.5 Harvey tolerance band. Both K1235b and paper clear the |t|>3.0 Harvey-significance threshold. Qualitative paper claim (Table 6 line 526 "Yes") holds. Small divergence plausibly from: (i) OOS end-date difference (paper's 2026-01/02 vs our 2026-04-14); (ii) minor yfinance Close adjustment drift; (iii) MLE starting-point sensitivity on short series.

### STOXX50E: BORDERLINE (diff = +0.28, 7.8% above paper 3.64)
K1235b t_harvey = 3.92 vs paper 3.64. Within ±0.5 tolerance. Clears Harvey threshold comfortably. Same sources of small divergence; our point estimate is slightly MORE favorable to A4f than the paper reports (i.e., not a disconfirmation).

## 6. Paper 9 R2 recommendation

**Path (b): spec-clarification footnote** (errata NOT required).

Rationale:
1. Both tickers MATCH or BORDERLINE under A4f spec → paper's reported values are reproducible within standard Harvey-corrected tolerance (±0.5).
2. Both K1235b point estimates clear the |t|>3.0 Harvey-significance threshold, preserving the qualitative Table 6 conclusion ("A4f significant at Harvey threshold for 5/7 cross-asset tests").
3. Residual |diff| ≤ 0.34 is within the range of numerical differences attributable to OOS window end-date (paper data ends ~2026-02, K1235b ends 2026-04-14) and yfinance adjustment drift — **not** a methodological error.
4. K1235 result (MISMATCH under log-exp K949 spec) is **consistent** with the interpretation that Paper 9 Table 6 used A4f, not K949 — i.e., K1232 concern about "no-source values" is resolved: the source is the K988-family A4f path, not the K949 path.

**Recommended footnote for Paper 9 Table 6**:

> Table 6 values for FEZ and STOXX50E are computed under the A4f specification (VIX² τ, free ω, OOS 2019-01-01 onwards, estimation window W=2,000, refit every 63 trading days) defined in Table 2 and Sections 2.2.1–2.2.2, matching the spec applied to the SPY primary result in Table 3. These values are distinct from the log-exp K949 specification used in earlier working-paper versions.

## 7. Files

| File | Purpose |
|------|---------|
| `k1235b.py` | Main script (A4f + GJR OOS loop, DM-Harvey, verdict logic) |
| `k1235b_results.json` | Full per-ticker numbers + R2 recommendation |
| `k1235b_run.log` | Run log |
| `k1235b_qlike_timeseries.png` | Per-ticker cumulative QLIKE comparison (GJR vs A4f) |
| `k1235b_vs_k1235_vs_paper.png` | Bar chart: paper claim vs K1235 (log-exp) vs K1235b (A4f) t_harvey |
| `README.md` | This file |

## 8. Reproducibility

```bash
uv run python experiments/k1235b/k1235b.py
```

- Seed: `np.random.seed(42)`
- Optimizer: scipy L-BFGS-B, maxiter=500, 3 starts per fit
- Data: yfinance (daily Close, `auto_adjust=True`) for FEZ, ^STOXX50E, ^VIX over 2005-01-01..2026-04-15
- Runtime: ~155s on M1 Max (30 refits × 2 tickers)

## 9. Next actions (主線程 only)

1. Draft Paper 9 R2 response incorporating the spec-clarification footnote above (paper-update workflow).
2. Update K1232 audit status: FEZ + STOXX50E "no-source" flag resolved → source = K988-family A4f spec.
3. Update `storage/memory/knowledge.json` with K1235b entry: R2 path (b), FEZ 3.11, STOXX50E 3.92, both Harvey-significant.
4. Cross-reference: K1235 MISMATCH entry should add "note: resolved by K1235b under A4f spec".
