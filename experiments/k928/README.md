# K928: Factor GARCH — Common Volatility Factor Across SPY/QQQ/GLD

## Research Question
Does a data-driven common volatility factor (PCA on cross-asset squared returns) improve individual asset volatility forecasting beyond what VIX already provides?

## Background
- **T24**: PCA on 22-day RV found PC1 explains 76.6%, r(PC1,VIX)=-0.81, incremental R²=0.00%
- **K907**: TCI=50% (Diebold-Yilmaz) but TCI ≠ VIX (r=0.001) — different risk dimension
- **K912**: MF-GJR advantage strongest in LOW VIX regimes
- **K918**: BEKK found no cross-spillover (SPY-GLD independent)
- **This experiment**: Uses daily r² (not smoothed 22-day RV), Factor-Augmented GJR with proper OOS, rolling PCA

## Literature
- Engle, Ng & Rothschild (1990): Factor ARCH — common volatility factors in asset returns
- Patton (2011): Proxy-robust QLIKE for fair model comparison
- Harvey (2016): |t| > 3.0 threshold for multiple testing
- Engle & Rangel (2008): Spline-GARCH, multiplicative decomposition

## Method
1. PCA on 5-asset daily r² matrix (SPY, QQQ, IWM, GLD, TLT), 2006-2026
2. Factor characteristics: explained variance, loadings, VIX correlation, autocorrelation
3. Rolling PCA (250-day window) for OOS factor extraction
4. Factor-Augmented GJR using multiplicative approach: h_aug = h_gjr * exp(delta * X_{t-1})
5. OOS evaluation: QLIKE on r², DM test (Harvey t>3.0), Spearman rank correlation

## Results

### PCA Analysis
- **PC1 explains 59.1%** of cross-asset daily r² variation (cf. T24: 76.6% on 22d RV — lower because daily r² is noisier than smoothed RV)
- **PC2 = 18.7%** (nearly pure GLD factor, loading 0.982)
- **PC3 = 16.4%** (nearly pure TLT factor, loading 0.949)
- **PC1-VIX correlation**: Pearson r=0.543, Spearman rho=0.480 (lower than T24's -0.81 on smoothed RV)
- **Rolling PC1 explained variance**: 57.3% +/- 6.6%, range [42.9%, 72.0%]
- **Loadings stable**: SPY/QQQ/IWM dominate PC1 (0.53-0.55), GLD/TLT minor (0.18-0.29)

### OOS Forecasting (2016-05 to 2026-04, ~2,490 days)

| Asset | GJR QLIKE | GJR-X(VIX) | GJR-X(PC1) | GJR-X(VIX+PC1) |
|-------|-----------|------------|------------|-----------------|
| SPY   | **1.576** | 1.600 | 1.611 | 1.658 |
| QQQ   | **1.543** | 1.559 | 1.554 | 1.574 |
| GLD   | 1.481 | **1.472** | 1.480 | 1.477 |

**All DM tests |t| < 3.0** — no factor-augmented model significantly beats GJR baseline.

### Key DM Statistics
- SPY: GJR-X(VIX) vs GJR: t=+1.16 (worse), GJR-X(PC1) vs GJR: t=+1.28 (worse)
- QQQ: GJR-X(PC1) vs GJR: t=+2.57 (worse, but below Harvey threshold)
- GLD: GJR-X(VIX) vs GJR: t=-0.69 (better direction but insignificant)
- **PC1 incremental beyond VIX**: All |t| < 2.0 — zero incremental value

### Spearman Rank Correlation (forecast vs actual)
- SPY: GJR 0.414, GJR-X(VIX) **0.436**, GJR-X(PC1) 0.408
- QQQ: GJR 0.396, GJR-X(VIX) **0.410**, GJR-X(PC1) 0.389
- GLD: GJR **0.237**, similar across all models

## Conclusions (NULL Result)
1. **PC1 captures equity commonality but is noisy at daily frequency** (59.1% vs 76.6% on smoothed RV)
2. **Factor augmentation HURTS for SPY/QQQ** — the multiplicative correction introduces noise
3. **GLD is the only asset where VIX augmentation helps** (lower QLIKE), but not significantly
4. **PC1 provides ZERO incremental value beyond VIX** in any asset
5. **VIX sufficiency confirmed again** — this is the 32nd+ confirmation across the project
6. **Own-asset GJR is already optimal** — cross-asset information is redundant for daily vol forecasting

## Interpretation
- At daily frequency, r² is extremely noisy (chi-squared distribution), making PCA factors noisy too
- T24's stronger result (76.6%, r=-0.81) used 22-day smoothed RV which averages out the noise
- The cross-asset factor structure exists (59.1% common variance) but it's already captured by:
  (a) VIX (which is a market-wide implied vol measure)
  (b) Each asset's own vol persistence (beta ~0.85 in GJR)
- Factor GARCH is theoretically elegant but empirically unnecessary for individual asset forecasting

## Data Source
- yfinance: SPY, QQQ, IWM, GLD, TLT daily prices (2006-01-04 to 2026-04-02, N=5093)
- VIX (^VIX) from yfinance

## Files
- `k928_factor_garch.py` — Main experiment script
- `k928_factor_garch_results.json` — Complete results
- `k928_pca_explained.png` — PCA explained variance scree plot
- `k928_factor_vs_vix.png` — PC1 vs VIX time series
- `k928_model_comparison.png` — QLIKE comparison bar chart
- `k928_rolling_explained.png` — Rolling PC1 explained variance over time
