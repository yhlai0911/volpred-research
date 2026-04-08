# Completed Session 2026-04-06

## Session Overview
15 experiments (K932-K945), 7 articles, 1 experience record (E051).
Focus: CARR range-based models, ML vol prediction, MF-GJR robustness, hedging.

## Experiments

### CARR Research Chain (K934→K935→K937→K938→K939)
- **K934 ★**: CARR(1,1) Parkinson — best rank (ρ=0.474) but worst calibration (QLIKE=1.815). Root cause: Parkinson σ²=λ²/(4ln2) assumes continuous paths, overnight gaps violate
- **K935 ★**: Yang-Zhang CARR fixes Parkinson bias — +8.04% improvement (DM t=-3.28 Harvey✓). YZ includes overnight + open jump + intraday components
- **K937 NULL**: CARR-GARCH Ensemble — 4 methods all lose to MF-GJR(VIX). OLS Stacking assigns 41.7% to MF-GJR, only 15.4% to CARR
- **K938 ★★**: Cross-asset YZ CARR validation — 4/4 assets all significant (Harvey✓). Gap ratio explains 80% of improvement (r=0.80). 0050.TW gap=84% → +37.3%, GLD gap=50% → +27.5%
- **K939 ★**: CARR_YZ-MF(VIX) — lowest QLIKE (1.462) but NS vs MF-GJR (DM t=-1.59). VIX dominates both range and return channels

### MF-GJR Robustness (K942, K943)
- **K942 ★★**: Subsample stability — 13/13 all win. VIX info highest in extreme regimes (Low +8.7%, High +17.3%), near zero in normal range (+0.5%)
- **K943 ★★**: Multi-horizon — Inverted-U pattern. h=5 weekly optimal (+18.4%, DM t=-4.12). h=22 monthly degrades (-5.7%, constant-tau breaks down)

### VIX Sufficiency Extensions (K933, K936)
- **K933 NULL**: FIGARCH-MF(VIX) — VIX already captures long memory. FIGARCH-MF numerically unstable. G3-3 closed
- **K936 NULL**: Time-varying Hurst exponent — R/S and DFA both NS. H(t) uncorrelated with VIX (r=0.121) but adds nothing

### ML Direction (K940, K944)
- **K940 NULL**: Neural Net — MLP catastrophic (QLIKE=651K, daily r² skew=15.7 kurt=347). RF viable (QLIKE=1.524) but loses to MF-GJR. Feature importance: VIX 35.1%
- **K944 NULL**: KAN/B-spline — B-spline basis expansion worse than RF. GARCH recursive dynamics h[t]=f(h[t-1],r²[t-1]) irreplaceable by feedforward ML

### Other
- **K932 rebuild**: Min-CVaR + Max CRRA allocation — 50/50 irreducible #14 (script recovered from worktree)
- **K941 ★**: Quantile vol forecasting — CAViaR-SAV best for intervals (pinball=0.000040). Point prediction ≠ interval prediction
- **K945 NULL**: Quadratic vs MV hedging — QH≈MV at daily frequency (mean return O(10^-5) negligible)

## Key Insights
1. VIX sufficiency proven from 6 new angles (long memory, Hurst, range, ML features, ensemble, subsample)
2. Different tasks need different models: point→MF-GJR, interval→CAViaR, monthly→GARCH
3. Yang-Zhang is the correct range estimator (overnight component is key)
4. GARCH recursive structure irreplaceable by feedforward ML
5. VIX is regime indicator (U-shape: extreme regimes most valuable)

## Infrastructure Fix
- `scripts/merge_worktree.sh` — permanent fix for worktree script loss (K923/K924/K932 lesson)
- K923 script recovered from stale worktree
