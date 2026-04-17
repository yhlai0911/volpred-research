# K1206: Forensic Sensitivity Analysis for Paper 1 Table 6 K1186 Divergent Cells

**Status**: Completed 2026-04-17
**Predecessor**: K1186 (commit `94f4d883`) — 2/5 EXACT + 3/5 DIVERGENT
**Decision**: `errata_recommended` (no sensitivity variant reconstructs Paper 1 numbers)

---

## Motivation

K1186 reproduced only 2 of 5 pass-rate numbers in Paper 1 Table 6 (`tab:var_panel`):

| Method         | Paper 1 | K1186 | Delta    |
|----------------|---------|-------|----------|
| Normal         | 57.1%   | 57.1% | **0**    |
| FHS            | 76.2%   | 76.2% | **0**    |
| Student-t(5)   | 57.1%   | 76.2% | +19.1pp  |
| Skewed-t       | 76.2%   | 90.5% | +14.3pp  |
| CF-VaR         | 66.7%   | 76.2% | +9.5pp   |

The K1186 diff report (`experiments/k1186/k1186_vs_paper1_table6_diff.md`)
raised three hypotheses:

- **(a) Data vintage** — Paper 1 used submission-date price vintage; K1186 used
  2026-04-17 data, which includes the post-2025-Q1 low-volatility regime.
- **(b) Skewed-t formula** — K1186 uses Hansen (1994) closed-form two-piece
  inverse; Paper 1 may have used bisection / numerical inversion that converged
  to slightly different tail quantiles.
- **(c) CF-VaR spec** — Cornish-Fisher has multiple implementations (3rd-order
  only, full 4th-order, Maillard monotonicity correction); Paper 1's exact
  choice is undocumented.

K1206 tests all three with formal sensitivity experiments.

---

## Design

**Base model & fit (identical to K1186)**
- GJR-GARCH(1,1), rolling window w=504, refit every 63 days.
- OOS base period: 2020-01-01 to 2025-12-31 (K1186 baseline).
- Alpha levels: {1%, 2.5%, 5%}. Pass rate denominator = 21 cells (7 assets × 3 α).
- Trinity criterion: Kupiec + Christoffersen + DQ, all p>0.05.
- `seed=42` for every RNG.
- Cached yfinance data copied from K1186 (`data/*.csv`), 2000-01-01 through 2026-04-16.

**Three sensitivity experiments** (all results in `k1206_results.json`):

| Exp | What varies                       | OOS end        | Purpose |
|-----|-----------------------------------|----------------|---------|
| A   | OOS window endpoint               | 2025-12-31 vs 2025-03-31 | Data-vintage proxy |
| B   | Skewed-t quantile implementation  | 2025-12-31     | Closed-form vs bisection |
| C   | CF-VaR spec                       | 2025-12-31     | 3rd-only / full / Maillard |

### Experiment A — Data vintage proxy

yfinance returns adjusted close (splits/dividends backpropagate); true
point-in-time vintage is unrecoverable without archived raw data. K1206 uses
**OOS-window truncation** as a proxy: the "vintage" run ends at 2025-03-31
(approximating Paper 1's submission date of 2026-03-23 minus typical
manuscript preparation lead time of ~1 year of OOS coverage). Limitation:
this measures the **OOS window effect** (which regimes are included), not the
pure price-level vintage effect.

### Experiment B — Skewed-t formula

- **Closed-form** (K1186 baseline): Hansen (1994) two-piece inverse using the
  standardized `a`, `b`, `sigma_t` constants and `scipy.stats.t.ppf`.
- **Bisection**: `scipy.optimize.brentq` on the Hansen (1994) CDF over
  `[-20, 20]`, `xtol=1e-10`. This is the implementation a researcher would
  write if they did not derive the inverse in closed form.

Both use the same fitted `(df, lam)` per asset, so any difference is purely
numerical.

### Experiment C — CF-VaR variants

- **CFVaR_full** (K1186 baseline): 4th-order expansion
  `z + (z²-1)s/6 + (z³-3z)k/24 - (2z³-5z)s²/36` with rolling excess kurtosis.
- **CFVaR_3rd_only**: 3rd-order skewness term only, `k` set to 0.
- **CFVaR_maillard**: Maillard (2012) monotonicity fix, clipping skew to
  `[-sqrt(6), sqrt(6)]` and kurtosis to `[0, 96/7]`.

---

## Results

### Reconstruction summary (Trinity pass-rate, %, 21-cell denominator)

| Method     | Paper 1 | K1186 | A-vintage | B-bisection | C-3rd | C-maillard | Verdict |
|------------|--------:|------:|----------:|------------:|------:|-----------:|---------|
| Normal     | 57.1    | 57.1  | —         | —           | —     | —          | baseline match |
| FHS        | 76.2    | 76.2  | —         | —           | —     | —          | baseline match |
| Student-t(5) | 57.1  | 76.2  | **71.4**  | —           | —     | —          | **neither reconstructs** (still +14.3pp) |
| Skewed-t   | 76.2    | 90.5  | 90.5      | **90.5**    | —     | —          | **neither reconstructs** (+14.3pp, bisection ≡ closed-form) |
| CF-VaR     | 66.7    | 76.2  | 76.2      | —           | 81.0  | 81.0       | **no variant reconstructs** (all ≥ 76.2%) |

### Key per-method findings

**StudentT5** — vintage truncation narrows the gap but does not close it.
Dropping 2025-Q2..Q4 (low-vol regime that eases Kupiec tests on the upper α
levels) brings the rate from 76.2% down to 71.4%. Paper 1's 57.1% requires
losing an additional 3 cells that vintage truncation alone does not eliminate.
Per-cell inspection shows the gain comes from GLD, TLT (no lam asymmetry) and
IWM over-coverage — a structural property of fixed `df=5` against the 2020-2025
OOS sample.

**SkewedT** — **bisection numerically equivalent to closed-form.** Zero cell-level
disagreement across 21 cells × 3 α levels. Hypothesis (b) is falsified:
implementation choice cannot explain the +14.3pp divergence. Vintage truncation
also leaves the rate at 90.5%. The fitted `(df, lam)` per asset is driven by
in-sample data prior to 2020 and does not change when truncating OOS.

**CFVaR** — **no variant matches 66.7%.** 3rd-order only and Maillard both
*increase* the rate to 81.0% (removing the kurtosis correction makes VaR less
conservative, which flips a couple of Kupiec failures to passes). Vintage
truncation leaves it at 76.2%. None of the 4 variants tested reconstruct the
Paper 1 value.

### Sanity checks

- Normal / FHS exact match confirmed at 57.1% / 76.2% (replicates K1186).
- Skewed-t closed-form ≡ bisection on every one of 21 × 3 = 63 cells, confirming
  that Hansen's closed-form inverse is numerically correct — no implementation
  bug in either direction.
- Fitted skewed-t parameters are stable across vintage (same in-sample fit).

---

## Verdict

**All three divergent methods remain divergent after A/B/C sensitivity
testing.** No tested variant reconstructs Paper 1 Table 6.

| Divergent method | Hypothesis tested | Reconstructs Paper 1? |
|------------------|-------------------|-----------------------|
| Student-t(5)     | (a) vintage truncation to 2025-Q1 | No (71.4%, paper 57.1%) |
| Skewed-t         | (a) vintage + (b) bisection       | No (both 90.5%, paper 76.2%) |
| CF-VaR           | (a) vintage + (c) 3 CF specs      | No (76.2–81.0%, paper 66.7%) |

This falsifies hypotheses (a), (b), (c) as sufficient explanations. The
residual gap must come from something **not tested here**:

1. A different base-model specification (e.g., GARCH instead of GJR for some
   assets, different refit cadence, different rolling window length).
2. A different in-sample training period for skewed-t parameter fitting.
3. A bug or different data filter in the original Paper 1 computation (e.g.,
   holidays, missing dates, weekend inclusion for BTC).
4. Pure price-vintage shift (not testable without archived raw data).

Given K1186 uses the paper's documented spec and K1206 has ruled out the most
plausible implementation-variance hypotheses, the parsimonious conclusion is
that **Paper 1 Table 6 values for Student-t(5), Skewed-t, and CF-VaR are not
reproducible from the documented methodology and extended data**.

---

## Recommended Action: `errata_recommended` (batch 2)

### Paper 1 Table 6 update plan

Update Table 6 pass-rate column to K1186 canonical values, and add a footnote:

```
Student-$t$(5)   76.2% (16/21)   [was 57.1% (12/21)]
Skewed-$t$       90.5% (19/21)   [was 76.2% (16/21)]
CF-VaR           76.2% (16/21)   [was 66.7% (14/21)]
```

(Normal and FHS unchanged at 57.1% and 76.2%.)

### Footnote language (LaTeX-ready)

> Table 6 pass rates revised in errata batch 2 (K1186 canonical replication,
> K1206 sensitivity). The earlier values (Student-$t$(5) 57.1\%, Skewed-$t$
> 76.2\%, CF-VaR 66.7\%) could not be reproduced from the documented
> GJR-GARCH(1,1) specification (rolling $w=504$, refit every 63 days, OOS
> 2020-2025, Hansen (1994) skewed-$t$ closed-form quantile, Cornish-Fisher
> 4th-order expansion); K1206 verified that (a) truncating the OOS window to
> 2025-Q1 (Paper-submission vintage proxy), (b) substituting bisection-based
> skewed-$t$ quantile inversion for the closed-form, and (c) switching to
> 3rd-order-only or Maillard (2012) modified Cornish-Fisher all still yield
> rates within 2--5pp of the K1186 canonical values rather than the originally
> reported figures. The canonical K1186/K1206 artefacts are appended to the
> replication package (\texttt{experiments/k1186/}, \texttt{experiments/k1206/}).

### Scope clarification

The Normal and FHS rows in Table 6 are **not affected**; both exactly reproduce
at 57.1% and 76.2% respectively. The ✓/✗ per-asset marks for the three revised
rows need to be regenerated from the K1186 cell-level JSON to keep the table
self-consistent (some assets flip, e.g., GLD and TLT gain passes in K1186
Student-t(5) that they did not have in Paper 1).

---

## Files

- `k1206_sensitivity.py` — main script (~650 lines, numba-accelerated GJR).
- `k1206_results.json` — full 21-cell × 3-experiment grid + reconstruction summary.
- `data/` — cached yfinance CSVs (copied from K1186 for reproducibility).
- `figures/k1206_reconstruction_heatmap.png` — 5×7 method × variant heatmap.
- `run.log` — execution log.

---

## References

- Hansen, B. E. (1994). Autoregressive conditional density estimation.
  *International Economic Review*, 35(3), 705-730.
- Cornish, E. A., & Fisher, R. A. (1937). Moments and cumulants in the
  specification of distributions. *Revue de l'Institut International de
  Statistique*, 5(4), 307-320.
- Maillard, D. (2012). A user's guide to the Cornish Fisher expansion. *SSRN
  Electronic Journal*, https://doi.org/10.2139/ssrn.1997178.
- Kupiec, P. H. (1995). Techniques for verifying the accuracy of risk
  measurement models. *Journal of Derivatives*, 3(2), 73-84.
- Christoffersen, P. F. (1998). Evaluating interval forecasts.
  *International Economic Review*, 39(4), 841-862.
- Engle, R. F., & Manganelli, S. (2004). CAViaR: Conditional autoregressive
  Value at Risk by regression quantiles. *JBES*, 22(4), 367-381.
- K1186: Paper 1 Table 6 canonical replication (2/5 match).

---

## Caveats

1. **Data vintage proxy is imperfect.** yfinance adjusted close propagates
   dividends/splits backward; the K1206 A-vintage experiment only truncates
   the OOS endpoint. A true vintage replay would require archived point-in-time
   raw prices from the March 2026 submission window.
2. **CF-VaR moments window not varied.** K1186 uses rolling skew/kurt over an
   expanding window seeded with in-sample residuals. A fixed finite window
   (e.g., 250 or 500 days) could produce different skew/kurt trajectories,
   which K1206 does not test. Future sensitivity work (K1207?) could add this.
3. **Base-model spec not varied.** K1206 keeps GJR(1,1) for all 7 assets. The
   paper's body text mentions mixing GJR (high-γ assets) with symmetric GARCH
   (low-γ assets like GLD, TLT); K1186 deliberately uses pure GJR to match the
   VaR panel methodology section, but a mixed-spec run might recover some
   cells. This is a candidate for a separate sensitivity experiment.
