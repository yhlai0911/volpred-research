# K912: MF-GJR Regime Decomposition -- When Does MF-GJR Add Value?

## Problem
K889 proved MF-GJR beats GJR overall (QLIKE -6.6% for SPY). But is this advantage **uniformly distributed across all periods**, or **concentrated in certain regimes**? Understanding "when" MF-GJR is most valuable matters for both the paper and practice.

## Motivation
- K889: MF-GJR overall Harvey-level improvement
- K889v2: Bug-fixed verification -- DM t=-2.569 (no longer Harvey PASS, but still significant at 5%)
- K783c: Regime-dependent window structures are real but cannot be robustly exploited
- **Academic value**: If MF-GJR advantage is larger during crises, this supports "multiplicative structure matters more in extremes"
- **Practical value**: Investors can know when to trust MF-GJR vs fall back to GJR

## Method
1. Re-run MF-GJR vs GJR for SPY (OOS 2019-01 to 2026-03) to get daily QLIKE sequences
2. Compute daily QLIKE difference: delta_qlike = qlike_gjr - qlike_mfgjr (positive = MF-GJR better)
3. VIX regime analysis (Low <15, Medium 15-25, High 25-35, Crisis >35)
4. Rolling 63-day advantage analysis overlaid with VIX
5. Event window analysis (COVID, Fed tightening, SVB, Yen carry trade)
6. Multiplicative factor tau analysis across regimes
7. Bootstrap confidence intervals (10000 reps) per regime

## Data
- Asset: SPY (most statistical power)
- Source: yfinance
- Period: 2005-01-01 to 2026-04-01
- OOS: 2019-01-01 to latest
- VIX from yfinance (^VIX)

## Expected Results
- High VIX regime: MF-GJR advantage likely larger (theta_1=2.34 has bigger impact at extremes)
- Low VIX regime: GJR and MF-GJR likely similar (tau approximately constant)
- If advantage is concentrated in crises: paper can frame MF-GJR as "crisis-adaptive model"
- If advantage is uniform: multiplicative structure value is general

## References
- Engle, Ghysels & Sohn (2013) RES 95(3):776-797
- Engle & Rangel (2008) RFS 21(3):1187-1222
- Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics
- Patton (2011) J Econometrics 160:246-256
- Harvey et al. (2016) JBES 34:92-104

## Output Files
- `k912_mfgjr_regime_decomposition.py` -- Main experiment script
- `k912_mfgjr_regime_decomposition_results.json` -- Full results
- `k912_regime_advantage.png` -- VIX regime bar chart
- `k912_rolling_advantage.png` -- Rolling delta_qlike + VIX
- `k912_event_windows.png` -- Event window analysis
