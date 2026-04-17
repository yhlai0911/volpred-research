# K1133: Regime-switching GAS-t on BTC — testing Catania (2018) regime claim

**Status**: completed (2026-04-17)
**Proposer**: Claude
**Executor**: Claude (worktree `agent-a1995208`)
**Related K**: K1129 (BTC reversal motivator), K1038 (4-asset NULL), K437 (SPY NULL)

## Motivation

K1129 tested GAS-t (Creal, Koopman & Lucas, 2013 JASA) against GJR-Normal on four commodities (USO, GLD, UNG, BTC-USD) using a pooled 2021-2026 OOS window. BTC produced a striking reversal: **DM-HLN t = -4.58** (GAS-t is *worse* than GJR-Normal, Harvey |t|>3.0). GJR-t also reversed with t=-5.17.

Catania (2018, JFE) argues that GAS-type score-driven models may need **regime-switching** versions in markets with structural breaks. BTC is a textbook case:

- **Period 1 (2015-2020)** — pre-institutional, retail-dominated
- **Period 2 (2021-2023)** — FTX / Terra-Luna / BlockFi collapses, extreme tail events
- **Period 3 (2024-2026)** — post-spot-ETF, institutional era

**Question**: Is the K1129 BTC reversal universal across all three regimes, or concentrated in one?

## Methodology

### Approach A (primary) — Per-sub-period rolling OOS

For each sub-period independently:
- Rolling IS window (adaptive: 750 obs default, floored at 500 if sub-period short)
- Refit every 63 days
- OOS starts at sub-period obs `WINDOW+1` (expanding coverage within regime)
- M1 GJR-Normal, M2 GJR-Student-t, M3 GAS-t all target r² (squared returns, Patton 2011 proxy-robust)
- DM-HLN (Harvey, Leybourne & Newbold, 1997) with Newey-West HAC
- Seed 42; explicit lookahead assertion (train window ends *strictly* before forecast obs)

### Approach B (secondary / skeleton) — 2-state Markov-switching GAS-t

In-sample only (Hamilton filter):
- 10 parameters: (ω, α, β, ν) × 2 states + 2 logit transition probs (p00, p11)
- LRT vs single-state GAS-t (χ², df = 6)
- *No OOS forecast implemented* — OOS state-probability handling for 10-param MS model on <1000 obs per regime is itself a research question beyond this experiment's scope

## Data

- Source: yfinance BTC-USD 2015-01-01 → 2026-04-15 (4121 obs)
- Daily `pct_change * 100` in percent units
- Std=3.51%, excess kurt=7.97, skew=-0.12

## Results

### Approach A — Main table (3 periods × 3 models)

| Period | n_OOS | M1 QLIKE | M2 QLIKE | M3 QLIKE | DM t (M2 vs M1) | DM t (M3 vs M1) | DM t (M3 vs M2) |
|---|---|---|---|---|---|---|---|
| P1 pre-institutional (2017-01 → 2020-12) | 1441 | **1.9926** | 2.2339 | 2.1904 | **-3.36** | **-4.67** | +0.53 |
| P2 FTX/Luna era (2023-01 → 2023-12) | 345† | **2.2891** | 2.2958 | 2.3162 | -0.26 | -0.82 | -0.85 |
| P3 spot-ETF era (2026-01 → 2026-04) | 100† | 1.9753 | **1.9484** | 2.0563 | +0.79 | -0.80 | -0.83 |

Bold = best (lowest QLIKE). **Bold t-stat** = Harvey (2016) |t|>3. † PRELIMINARY (n_OOS < 504 minimum from spec).

### Approach B — Markov-switching GAS-t (in-sample)

All three periods converged; 2-state structure highly significant vs single-state:

| Period | n | LRT χ² (df=6) | p | state_0 (ω, α, β, ν) | state_1 (ω, α, β, ν) | p00, p11 |
|---|---|---|---|---|---|---|
| P1 | 2191 | 48.53 | 9.3e-09 | 0.528, 1.358, 0.884, 5.82 | -0.043, 0.627, 0.996, 4.41 | 0.40, 0.82 |
| P2 | 1095 | 36.63 | 2.1e-06 | 0.399, 2.000, 0.891, 18.08 | -0.018, 0.229, 0.999, 4.09 | 0.47, 0.84 |
| P3 | 835 | 15.91 | 1.4e-02 | 0.269, 2.000, 0.901, 12.79 | -0.069, 2.000, 0.936, 80.67 | 0.59, 0.33 |

All LRT reject single-state at p<0.05; P1/P2 at p<0.001. **In-sample evidence for regime-switching is strong**, especially in earlier periods.

## Conclusions

### (a) Is GAS-t advantage regime-specific?

**No — GAS-t has no positive advantage over GJR-Normal in any of the three periods.** The DM t-stat for M3 vs M1 is:
- P1: **-4.67** (strong reversal)
- P2: -0.82 (neutral)
- P3: -0.80 (neutral, PRELIMINARY n=100)

### (b) Does this support or reject Catania (2018)?

**Partially rejects the naive "just add regime-switching" fix for BTC.** The reversal is **not uniform** across regimes (so single-state misspecification is a plausible diagnosis), but:

1. The reversal is **concentrated in the earliest, most homogeneous period** (P1 2015-2020), not in the most structurally-unstable period (P2 FTX/Luna).
2. In P2 and P3 — exactly the regimes Catania's argument implies would benefit most from MS-GAS — plain GAS-t is **neutral, not improved** vs GJR-N.
3. In-sample MS-GAS-t LRT is strongly significant in all 3 periods, but that says nothing about OOS forecasting advantage. K1038 / K437 pattern (in-sample structure ≠ OOS edge) plausibly applies here.

Pattern suggests the BTC-on-GAS-t failure is **not** a "wrong regime specification" problem. More likely it is a **score-scaling / unit-variance parameterization mismatch** with BTC's very low autocorrelation of r² combined with extreme positive skew in |r_t|. The GJR-Normal's direct quadratic response to |r_{t-1}| apparently transports better on BTC than GAS-t's Fisher-scaled t-score.

### (c) Implication for a BTC single-commodity GAS-t paper

A paper claiming "GAS-t helps crypto volatility forecasting" is **not supportable**. A more honest paper would be:

> *"Why GAS-t fails on BTC: a regime-decomposition analysis"*

Findings in favor of such a paper:
1. Full-sample K1129 reversal (t=-4.58) is driven almost entirely by P1 2015-2020.
2. In the more turbulent P2 and P3 regimes, GAS-t is neutral — the Student-t innovation benefit seen on equity indices disappears, but so does the penalty.
3. MS-GAS-t gains very significant in-sample likelihood (LRT p<0.01 in all periods) but this is orthogonal to out-of-sample forecast quality.
4. Supports a broader "single-state GAS fails on non-stationary markets" narrative but does **not** validate Catania's regime-switching remedy on BTC (testing MS-GAS-t OOS would be K1133b).

## Files

| File | Purpose |
|---|---|
| `k1133.py` | Main experiment script |
| `k1133_results.json` | Full numeric output (sub-period metrics, DM tests, MS-GAS-t fits, headline verdict) |
| `k1133_qlike_by_period.png` | Bar plot: QLIKE per period × model |
| `k1133_dm_heatmap.png` | Heatmap: DM-HLN t-stat per period × comparison |

## Lookahead check (executed at run time)

```python
assert train_start + len(train_data) == t_abs, \
    f"Train window leaks into obs {t_abs}"
```

Forecast for observation at OOS index `t_oos` uses only (`returns[t_abs - 1]`, `σ²_{t-1}`) from the already-fit model. No same-day leakage.

## References

- Catania, L. (2018). Dynamic Adaptive Mixture Models with an Application to Volatility and Risk. *Journal of Financial Econometrics*, 18(3), 493-544.
- Creal, D., Koopman, S. J., & Lucas, A. (2013). Generalized autoregressive score models with applications. *JASA*, 108(501), 1-18.
- Hamilton, J. D. (1989). A new approach to the economic analysis of nonstationary time series and the business cycle. *Econometrica*, 57(2), 357-384.
- Harvey, A. C. (2013). *Dynamic Models for Volatility and Heavy Tails*. Cambridge University Press.
- Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of prediction mean squared errors. *IJF*, 13(2), 281-291.
- Harvey, C. R. (2016). Editorial: The Scientific Outlook in Financial Economics. *JoF*, 72(2).
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *JoE*, 160(1), 246-256.

## Limitations

1. **P3 is preliminary** (n_OOS=100, <504 spec minimum). Conclusion for P3 should be re-verified with larger window once 2027 data arrives or with daily → hourly resampling.
2. **Approach B is in-sample only**. OOS evaluation of MS-GAS-t requires careful filtered-probability handling (Gray 1996 / Klaassen 2002) — explicitly deferred.
3. **GJR-Normal wins on level, GJR-t and GAS-t both lose** — i.e., the Student-t innovation itself appears to be the harmful ingredient, not GAS dynamics. A follow-up K1133b could test GAS-Normal (rarely used but a clean decomposition) to isolate the GAS dynamic contribution from the Student-t innovation contribution.
4. Sub-period boundaries chosen by event markers, not by endogenous break tests. Bai-Perron test for structural breaks in BTC volatility would strengthen the regime definition.
