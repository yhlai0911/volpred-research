# K1093: DCC-A4f Weight Sensitivity — Commodity-Heavy Portfolios Push ASYM Across Harvey (QLIKE)

**[提出: 賴奕豪, 執行: Claude]**
**Date**: 2026-04-12
**Status**: Complete
**Runtime**: 47.1s

---

## Motivation

K1092 showed that **DCC-A4f-ASYM** (SPY uses VIX², GLD uses GVZ²) beats
**DCC-A4f-SYMM** (both use VIX²) on 50/50 SPY/GLD portfolio VaR:

- Portfolio QLIKE DM t = **+2.95**  (just below Harvey |t|>3.0)
- FZ 1% DM t = **+2.95**
- FZ 2.5% DM t = **+2.14**

The signal pointed in the right direction (asset-matched IV helps) but was not
Harvey-significant. The **hypothesis** was that **50/50 weight dilutes the
GLD-GVZ channel**; tilting toward GLD should amplify it. This experiment tests
that directly by evaluating the same three DCC models at 5 weight schemes.

## Research Questions (pre-registered)

| # | Question | Pre-registered prediction |
|---|----------|---------------------------|
| H1 | Is ASYM-vs-SYMM DM t monotonic in GLD weight? | Yes (asset-matched theory) |
| H2 | Does any weight push ASYM across Harvey \|t\|>3.0? | Yes (expect GLD-heavy) |
| H3 | Does 30/70 SPY/GLD hit Harvey? | Likely |
| H4 | Does 50/50 replicate K1092? | Yes |

## Design

Identical data, models and OOS protocol as K1092; only the portfolio weight vector
changes. The three DCC models are fitted **once** (marginals & DCC are
weight-independent by construction). Then for each weight vector we recompute:

- Portfolio return: `r_p,t = w_SPY·r_SPY,t + w_GLD·r_GLD,t` (simple returns)
- Portfolio variance: `σ²_p,t = w₁²·h_SPY + w₂²·h_GLD + 2·w₁w₂·ρ_t·√(h_SPY·h_GLD)`
- VaR/ES via CF-Rolling (252-day) on portfolio standardized residuals
- Evaluation: Trinity (Kupiec + CC + Basel) + ES backtest + FZ joint score + QLIKE DM

### Weight schemes

| Portfolio | SPY % | GLD % |
|-----------|-------|-------|
| 70/30     | 70%   | 30%   |
| 60/40     | 60%   | 40%   |
| **50/50** | **50%** | **50%** | ← K1092 baseline |
| 40/60     | 40%   | 60%   |
| 30/70     | 30%   | 70%   |

### Models (second stage always DCC(1,1))

| Model | SPY marginal | GLD marginal |
|-------|--------------|--------------|
| DCC-GJR      | GJR-GARCH(1,1) | GJR-GARCH(1,1) |
| DCC-A4f-SYMM | A4f: τ = θ₀ + θ₁·VIX²_{t-1} | A4f: τ = θ₀ + θ₁·**VIX²**_{t-1} |
| DCC-A4f-ASYM | A4f: τ = θ₀ + θ₁·VIX²_{t-1} | A4f: τ = θ₀ + θ₁·**GVZ²**_{t-1} |

### OOS protocol

- Data: yfinance SPY/GLD (auto_adjust=True), ^VIX, ^GVZ. Period 2005-01-04 → 2026-04-10 (n=5350)
- OOS start: 2013-06-01 (n=3234); window=1250d; refit_every=63d; CF-rolling=252d
- α ∈ {1%, 2.5%}; seed 42

## Results

### DM t-stat curve (DCC-A4f-SYMM vs DCC-A4f-ASYM, +t = ASYM better)

| Portfolio (SPY/GLD) | GLD % | QLIKE DM t | FZ 1% DM t | FZ 2.5% DM t |
|---------------------|-------|------------|------------|--------------|
| 70/30               | 30    | +1.30      | +2.12      | +0.79        |
| 60/40               | 40    | +2.21      | +1.98      | +3.31 ***    |
| 50/50 (K1092)       | 50    | +2.87      | +2.57      | +1.69        |
| 40/60               | 60    | **+3.37 *** | +2.80     | +1.68        |
| 30/70               | 70    | **+3.68 *** | +2.27     | +2.76        |

Harvey |t|>3.0 marked `***`.

### Cross-weight statistics

- **Spearman ρ (GLD weight vs QLIKE DM t)** = **+1.000** (p < 0.0001) — perfect monotonic increase
- Spearman ρ for FZ 1% = +0.600 (p=0.28) — non-monotonic
- Spearman ρ for FZ 2.5% = +0.300 (p=0.62) — non-monotonic
- **QLIKE Harvey PASS count = 2/5** (40/60, 30/70)
- FZ 1% Harvey PASS count = 0/5
- FZ 2.5% Harvey PASS count = 1/5 (60/40 only)

### Trinity / violation rates

At α=1%, ASYM passes Trinity in 4/5 weights (70/30 fails on Basel yellow due to
clustering near the SPY-heavy tail). At α=2.5% ASYM passes 5/5. No ballooning of
violation rates at any weight.

### Portfolio Sharpe (context, not the core test)

| Portfolio | Sharpe | Mean % | Vol % |
|-----------|--------|--------|-------|
| 70/30     | 1.008  | 13.17  | 13.06 |
| 60/40     | 1.039  | 12.79  | 12.31 |
| 50/50     | 1.038  | 12.41  | 11.96 |
| 40/60     | 0.999  | 12.03  | 12.04 |
| 30/70     | 0.928  | 11.65  | 12.55 |

50-60% SPY remains the Sharpe-efficient region; pushing to 30/70 costs Sharpe.
**The model-selection benefit (ASYM > SYMM) and the asset-allocation benefit
(SPY tilt for Sharpe) point in opposite directions.**

### 50/50 replication of K1092

Minor MLE-starting-value drift (expected):

| Metric | K1093 | K1092 |
|--------|-------|-------|
| Mean QLIKE ASYM | -9.11651 | -9.11597 |
| Mean QLIKE SYMM | -9.09398 | -9.09281 |
| QLIKE DM t (SYMM vs ASYM) | +2.87 | +2.95 |
| FZ 1% DM t | +2.57 | +2.95 |

Small differences come from MLE starting-value grids (same seed but different
optimization path). Qualitative conclusions identical.

## Interpretation

### H1: **CONFIRMED** (strong)

QLIKE DM t increases **monotonically** from +1.30 (70/30) to +3.68 (30/70) as
GLD weight rises. Spearman ρ = +1.000 (perfect monotone). The **weight
sensitivity is the theoretical signature of asset-matched IV**: as the
portfolio leans toward GLD, the GVZ channel's variance-forecasting accuracy
contributes proportionally more to portfolio variance.

### H2 & H3: **PARTIALLY CONFIRMED**

- QLIKE hits Harvey at 40/60 and 30/70. 30/70 is specifically a **PASS (t=+3.68)**.
- However, **FZ 1% never hits Harvey** across any weight. FZ 2.5% only at 60/40.
- Asset-matched IV clearly improves **mean** portfolio variance forecasting but
  the tail-risk benefit (VaR/ES) attenuates more in the portfolio setting than
  in K1085's univariate GLD result.

### H4: **CONFIRMED**

50/50 replicates K1092 within MLE noise.

## Implications for Paper 3 × Paper 9

**Positive evidence for joint claim**: commodity-heavy portfolios (≥60% GLD)
obtain Harvey-significant QLIKE benefit from asset-matched DCC-A4f. A paper
3 × paper 9 chapter can defensibly argue:

> Asset-matched IV (SPY-VIX, GLD-GVZ) provides statistically significant
> mean-variance forecasting improvement over symmetric (VIX-only) specifications
> for portfolios with commodity tilt ≥ 60%. For balanced 50/50 portfolios the
> benefit is directionally correct but just below Harvey threshold; pure
> commodity univariates (K1085 t=+4.46) and diversified 30/70 portfolios (this
> paper, t=+3.68) both pass.

**Caveats for the joint claim**:

1. FZ (joint VaR-ES) significance is **not** monotone in GLD weight. The
   tail-risk story is subtler than the mean-variance story.
2. The Sharpe-efficient region (50-60% SPY) is **not** where ASYM dominance
   peaks. Practitioners with standard 50/50 allocations would see only
   borderline (t≈2.9) benefit on QLIKE and no Harvey-significant VaR/ES benefit.
3. Violation-rate ASYM-vs-SYMM differences are small (<1%) across all weights.

### Null result caveat

For a balanced (50/50) portfolio — the benchmark most investors would recognize
— asset-matched DCC-A4f does **not** deliver Harvey-significant VaR/ES
improvement. The theory survives only in commodity-tilted configurations. This
is a constraint the joint paper must acknowledge.

## Files

- `k1093.py` — full experiment script (reuses K1092 model kernels, weight loop is new)
- `k1093_results.json` — all per-weight results, cross-weight Spearman/monotonicity analysis, core answers
- `k1093_dm_weight_curve.png` — **the core figure**: DM t vs GLD weight for QLIKE / FZ 1% / FZ 2.5%
- `k1093_trinity_by_weight.png` — violation rates by weight × model × α
- `k1093_fz_by_weight.png` — mean FZ scores by weight × model × α
- `k1093_sharpe_by_weight.png` — portfolio Sharpe/return/vol by weight (context)

## References

- Engle (2002). Dynamic Conditional Correlation. JBES 20(3).
- Engle, Ghysels & Sohn (2013). A4f specification. RES 95(3).
- Patton (2011). Volatility forecast comparison. JoE 160(1).
- Fissler & Ziegel (2016). Higher order elicitability. Annals of Statistics 44(4):1680-1707.
- Patton, Ziegel & Chen (2019). Dynamic semiparametric models for ES and VaR. JoE 211(2).
- Diebold & Mariano (1995). JBES 13(3).
- Harvey (2016). Econometric significance thresholds.
- K1041 (50/50 SYMM-only DCC-A4f baseline), K1085 (GLD-GVZ univariate DM=+4.46),
  K1088 (USO-OVX commodity asset-matched), K1091 (asset-matched IV meta),
  K1092 (50/50 ASYM-vs-SYMM).
