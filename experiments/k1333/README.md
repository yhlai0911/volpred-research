# K1333: VIX vol-of-vol (self-constructed) as predictor of next-day VIX

- **K id**: K1333
- **Status**: completed
- **Verdict**: **CONDITIONAL_PASS** (weak positive OOS evidence; does not survive Bonferroni across 4 cells)
- **Created**: 2026-06-14

## Research Question

Does a self-constructed vol-of-vol on VIX log-returns predict next-day VIX
level and next-day `|ΔVIX|`, beyond an AR(1) baseline on VIX changes?

This is intentionally a no-options proxy. It does NOT use VVIX directly —
it constructs an analogous rolling realized vol on `dlog(VIX)`.

## Differentiation

- Bekaert and Hoerova (2014) decompose VIX into conditional variance + VRP
  using option-implied VVIX-style measures; here we replace the option
  channel with realized vol of VIX log-returns to test whether the realized
  channel alone carries incremental signal over AR(1) on dVIX.
- Andersen, Bollerslev, Diebold (2007) use realized vol-of-vol on
  high-frequency returns to forecast volatility levels; we apply the same
  concept on daily VIX with short (5d) and long (22d) windows.
- Patton (2011) — Patton QLIKE and HAC-DM evaluation framework adopted
  here as the primary forecast-loss comparison.

## Data

- Source: yfinance, `^VIX` daily close
- Period: 2010-01-04 to 2026-06-12 (4,137 raw rows; 4,115 after feature build)
- Splits:
  - Train: 2010-02 to 2019-12 (n=2,494)
  - Val:   2020-01 to 2023-12 (n=1,006)  — covers COVID + 2022 Fed hike
  - Test:  2024-01 to 2026-06 (n=615)    — strict OOS

## Method

### Features (all `.shift(1)` aligned)

- `rv_short_lag1` = sqrt(252 * mean(r²[t-5:t-1]))
- `rv_long_lag1`  = sqrt(252 * mean(r²[t-22:t-1]))
- `VIX_lag1`      = VIX_{t-1}
- `r_lag1`        = log(VIX_{t-1} / VIX_{t-2})
- `jump_proxy`    = |r_{t-1}| · 1{|r_{t-1}| > 2 · sigma_daily_{t-1}}
  where `sigma_daily_{t-1} = rv_long_{t-1} / sqrt(252)`

### Specs

- **M1**: `rv_short_lag1 + rv_long_lag1`
- **M2**: M1 + `jump_proxy + VIX_lag1 + r_lag1`

### Targets

- `target_level`     = VIX_t
- `target_abs_change`= |VIX_t − VIX_{t-1}|

### Baselines (same lag convention)

- **naive**: random walk on level (VIX_t̂ = VIX_{t-1});
  last-value on |dVIX| (|dVIX|_t̂ = |dVIX|_{t-1}).
- **AR(1)**: expanding OLS, refit every 21 days, using only past info.
  For level target, AR(1) is on dVIX and converted back: VIX_t̂ = VIX_{t-1} + α + φ·dVIX_{t-1}.
  For |dVIX| target, AR(1) is directly on |dVIX|.

### Tests

- HAC-DM (Newey-West, h=1) — **not** Harvey-Leybourne-Newbold finite-sample adjusted.
- Patton QLIKE on positive targets (Patton 2011).
- Paired stationary bootstrap CI on loss differential (B=2000, block_len=10, seed=42).
- R²_OOS Campbell-Thompson vs each baseline.

### Multiple testing

4 (target × spec) cells. Bonferroni family α=0.05 ⇒ cell α=0.0125.

### Verdict tiers

- **PASS**: ≥1 cell beats AR(1) at p < 0.0125 (Bonferroni-survival) with R²_OOS > 0.
- **CONDITIONAL_PASS**: ≥1 cell beats AR(1) at p < 0.05 unadjusted.
- **NULL**: no cell beats AR(1).

## Results

### Headline (OOS n=615)

| target / spec | R²_OOS vs AR1 | DM t (MSE) | p | DM t (QLIKE) | p |
|---|---:|---:|---:|---:|---:|
| level / M1 | -3.188 | +4.44 | 0.0000 | -- | -- |
| level / M2 | +0.025 | -2.04 | 0.041 | -2.24 | 0.026 |
| abs_change / M1 | -0.032 | +0.74 | 0.461 | -- | -- |
| abs_change / M2 | +0.136 | -2.05 | 0.041 | -- | -- |

(QLIKE on |dVIX| not computed: 0 in observed |dVIX| series breaks log domain.)

### Coefficients (full-sample, HAC SE lag=5)

**level / M2 target = VIX_t**

| Term | Coef | HAC SE | t |
|---|---:|---:|---:|
| intercept     | 0.716 | 0.154 | 4.65 |
| rv_short_lag1 | -0.221 | 0.075 | -2.94 |
| rv_long_lag1  | 0.005 | 0.077 | 0.07 |
| jump_proxy    | 1.420 | 1.422 | 1.00 |
| VIX_lag1      | 0.973 | 0.007 | 133.21 |
| r_lag1        | -2.298 | 0.774 | -2.97 |

VIX_lag1 dominates, as expected (VIX is near unit-root in level). The
incremental signal in `rv_short_lag1` (negative) and `r_lag1` (negative)
hints at short-horizon mean reversion in VIX changes that the model
captures slightly better than AR(1).

**abs_change / M2 target = |dVIX_t|**

| Term | Coef | HAC SE | t |
|---|---:|---:|---:|
| intercept     | -0.987 | 0.193 | -5.12 |
| rv_short_lag1 | 0.433 | 0.059 | 7.35 |
| rv_long_lag1  | 0.088 | 0.052 | 1.70 |
| jump_proxy    | 1.870 | 0.917 | 2.04 |
| VIX_lag1      | 0.082 | 0.010 | 8.44 |
| r_lag1        | 1.337 | 0.448 | 2.98 |

Short-window realized vol of VIX changes is the strongest predictor of
next-day VIX-change magnitude. This is consistent with vol clustering of
VIX itself.

### Bootstrap CI on mean (SE_model − SE_AR1)

- level / M2: [-0.200, -0.010] — fully below zero ⇒ model loss strictly less than AR1's
- abs_change / M2: [-0.673, -0.103] — fully below zero ⇒ same

Both CIs are inconsistent with zero loss-differential, but the effect
sizes are small.

## Interpretation

**Weak positive evidence** that self-constructed vol-of-vol features add
to AR(1) on dVIX, primarily through:
1. Short-window realized vol of VIX log-returns predicting next-day |dVIX|.
2. Lagged VIX return (`r_lag1`) carrying a mean-reverting signal on VIX_t
   that AR(1) on dVIX alone does not fully exploit.

`level / M1` (vol-of-vol features only, no `VIX_lag1`) badly underperforms
because the level target is near unit-root — any spec lacking lagged level
is mis-specified. This is an expected failure mode, not a bug.

Two of four cells survive unadjusted p<0.05 but **neither survives
Bonferroni** correction across the 4-cell family. The effect, while
plausibly real, is small and should be reported as **CONDITIONAL_PASS**
weak evidence, not strong PASS.

## Honesty / Defense Checklist

- [x] All predictors `.shift(1)` (Codex-verified)
- [x] AR(1) baseline uses identical lag convention (Codex-verified)
- [x] Seed = 42 fixed for bootstrap
- [x] OOS split strict (test starts 2024-01-02, model fits use `[:i]` only)
- [x] DM described as HAC-DM (not HLN — original "HLN-adjusted" comment removed)
- [x] Verdict aggregation Bonferroni-corrected across 4 cells
- [x] NULL `level / M1` reported, not hidden
- [x] Codex review: CONDITIONAL_PASS (`codex_review.md`)

## Files

- `k1333.py` — reproducible script (single entry: `uv run python experiments/k1333/k1333.py`)
- `k1333_results.json` — full metrics + coef tables + bootstrap CIs
- `k1333_vix_volofvol.png` — VIX + rv_short + rv_long time series with split lines
- `codex_review.md` — Codex review record (primary path)

## References

1. Bekaert, G., Hoerova, M. (2014). "The VIX, the variance premium and stock market volatility." *Journal of Econometrics* 183(2), 181-192.
2. Andersen, T. G., Bollerslev, T., Diebold, F. X. (2007). "Roughing it up: Including jump components in the measurement, modeling, and forecasting of return volatility." *Review of Economics and Statistics* 89(4), 701-720.
3. Patton, A. J. (2011). "Volatility forecast comparison using imperfect volatility proxies." *Journal of Econometrics* 160(1), 246-256.
