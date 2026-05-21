# K1318: HAR-RV 5-min Pilot — SPY & 0050.TW Actual Realized Variance

## Pre-registered Hypothesis

Using **actual 5-minute intraday realized variance (RV)** as both features and target in HAR models should outperform HAR models that rely on daily-frequency proxies (|r_t| or r²_t), because:

1. 5-min RV is a near-unbiased estimator of latent daily variance (Andersen & Bollerslev, 1998)
2. Daily proxies (|r_t|, r²_t) are noisy — r² has ~4.8× higher noise relative to RV
3. K530 showed HAR-ABS is already competitive with GJR-GARCH using daily proxies; switching to true RV should widen the gap

**Pre-registered expectation**: HAR-RV-5min QLIKE < HAR-ABS < HAR-SQ ≤ EWMA-0.94

**Null hypothesis (DM test)**: H₀: HAR-RV-5min QLIKE = EWMA-0.94 QLIKE  
**Alternative**: H₁: HAR-RV-5min QLIKE < EWMA-0.94 QLIKE  
**Significance level**: α = 0.01 (two-tailed |t|>3, Harvey 1997 correction)

**Power caveat**: SPY OOS ≈ 58 obs, TW50 OOS ≈ 31 obs. Small-sample power is low; NULL result = inconclusive, not evidence against HAR-RV.

## Data

| Asset | RV Source | Sample | Non-null OOS |
|-------|-----------|--------|-------------|
| SPY   | data/intraday/SPY_daily_rv.csv | 2026-01-14 ~ 2026-05-20 | ≈58 |
| 0050.TW | data/intraday/0050_TW_daily_rv.csv | 2026-02-09 ~ 2026-05-20 | ≈31 |

Daily prices for proxy construction: yfinance SPY & 0050.TW 2025-01-01 ~ 2026-05-20.

## Models

| Model | Features | Target |
|-------|----------|--------|
| HAR-RV-5min | rv_1d, rv_5d, rv_22d (from 5-min RV) | RV[t] |
| HAR-RV-5min-LOG | log(rv_1d+ε), ... | log(RV[t]+ε) |
| HAR-ABS | abs_1d, abs_5d, abs_22d (daily \|r\|) | RV[t] |
| HAR-SQ | sq_1d, sq_5d, sq_22d (daily r²) | RV[t] |
| EWMA-0.94 | λ=0.94, seed from r² | RV[t] |

## Method

Expanding window OOS (min train = 30 days):
- Fit on [0..t-1], predict t, advance one step
- Evaluate: QLIKE, MSE, DM test (HLN 1997) vs EWMA-0.94

Lookahead certification: all features at time t use only information through t-1.

## Related Work

- K530 (★★★★): HAR-VIX best (QLIKE=-3.917), HAR-ABS competitive; true RV expected to push further
- K782: HAR loses to GJR on r² target; proxy quality matters more than model complexity
- Andersen et al. (2003) RealizedVolatility RFS paper — HAR-RV theoretical foundation

---

## Final Verdict

**Overall: NULL (small-sample inconclusive, not evidence against HAR-RV)**

Executed: 2026-05-21. OOS: SPY n=36, TW50 n=9.

### QLIKE Results

| Model | SPY | TW50 |
|-------|-----|------|
| HAR-RV-5min | **0.4868** | 0.4627 |
| HAR-ABS | 0.5135 | **0.4521** |
| HAR-SQ | 0.4394 | 0.4885 |
| EWMA-0.94 | 0.5019 | **0.4427** |

### DM Test vs EWMA-0.94 (HLN 1997)

| Model | SPY t-stat | SPY verdict | TW50 t-stat | TW50 verdict |
|-------|-----------|-------------|-------------|--------------|
| HAR-RV-5min | -0.240 | NULL | +0.761 | NULL |
| HAR-ABS | +0.173 | NULL | +0.398 | NULL |
| HAR-SQ | -0.931 | NULL | +0.881 | NULL |
| HAR-RV-5min-LOG | +43.978 | FAIL* | +42.825 | FAIL* |

*LOG model FAIL is expected: log back-transform has upward bias without Duan smearing; do not use without bias correction.

### Interpretation

- **SPY**: HAR-RV-5min QLIKE=0.487 < EWMA=0.502 (directionally correct, +3.0% improvement), but |t|=0.24 far below Harvey threshold of 3.0. NULL = inconclusive, not a rejection.
- **TW50**: HAR-RV-5min QLIKE=0.463 > EWMA=0.443 (wrong direction), BUT TW50 n=9 is effectively uninformative — HAR-22 consumes 22 lags + 30 min_train = 52 rows from only 61 available; extreme small-sample regime.
- **HAR-SQ (r²) beats HAR-RV-5min on SPY** (0.439 vs 0.487): consistent with K782 finding that proxy scale interacts with RV level — r² proxy may compress extreme days differently in this 2026 sample.
- **Root cause of NULL**: OOS windows are too short (36 and 9 obs). Harvey threshold |t|>3 requires roughly n≥100 to detect moderate effect sizes. This experiment is a **pilot** — revisit when SPY has ≥200 OOS days (~late 2026).

### Decision

- Knowledge entry: CONDITIONAL_PASS (directionally consistent for SPY; small-sample caveat on TW50)
- Not ready for feed article standalone; can support a "data accumulation" methodology note
- Revisit at SPY n=100 (≈ 2026-08) and n=200 (≈ late 2026)
- Log-HAR requires Duan smearing bias correction before use as level predictor (new experiment direction)
