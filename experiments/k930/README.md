# K930: MF-GJR Parameter Stability Over Time

## Motivation
K889v2 confirmed MF-GJR(VIX) improves upon GJR-GARCH for SPY and QQQ (QLIKE improvement of 6.6% and 5.2% respectively). K889b validated this with 5/5 cross-OOS periods. However, the **temporal stability of estimated parameters** has not been examined.

If MF-GJR parameters drift substantially over time, the model may be unreliable in certain regimes. Conversely, stable parameters would strengthen the case for MF-GJR as a robust forecasting tool.

## Research Questions
1. Are MF-GJR parameters ($\theta_0$, $\theta_1$, $\alpha$, $\gamma$, $\beta$) stable across rolling estimation windows?
2. Is there a structural break around COVID-19 (2020)?
3. Does parameter stability differ across assets (SPY, QQQ, 0050.TW)?
4. Does $\theta_1$ (VIX elasticity) — the key innovation parameter — remain stable?
5. Is there a relationship between parameter values and forecasting performance?

## Method
- **Rolling window estimation**: window=2000, step=63 (quarterly refit), same as K889v2
- **Assets**: SPY, QQQ, 0050.TW
- **Period**: 2005-01-01 to 2026-04-01
- **Models**: MF-GJR and GJR-GARCH (baseline)
- **Stability tests**: Coefficient of Variation (CV), ADF on parameter series, Chow test (pre/post COVID), CUSUM
- **Parameter-performance analysis**: Correlation between rolling parameters and rolling QLIKE

## Data Source
- yfinance: SPY, QQQ, 0050.TW, ^VIX
- 0050.TW cleaned via `clean_tw50_data`

## References
- Engle, Ghysels & Sohn (2013) RES 95(3):776-797
- Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics
- Patton (2011) J Econometrics 160:246-256

## Key Findings

### 1. theta_1 (VIX Elasticity) — Moderate Stability
- **Within-asset CV**: SPY=0.096, QQQ=0.132, 0050.TW=0.099 (all < 15%)
- **Cross-asset CV**: 0.211 (SPY=2.42, QQQ=1.84, 0050.TW=1.44) — SPY has strongest VIX sensitivity
- **Trend**: Significant upward trend for SPY and QQQ (p<0.001), indicating VIX influence is **strengthening** over time
- **Chow test**: Significant pre/post COVID break for all three assets (p<0.01)
- **ADF**: Non-stationary for SPY and 0050.TW — theta_1 is drifting, not mean-reverting
- **CUSUM**: Break detected for 0050.TW (peak at 2020-03-26, i.e. COVID)

### 2. Structural Break: COVID-19
- All three assets show significant Chow-test breaks (pre/post 2020-03) for theta_1
- SPY theta_1 shifted from ~2.1 to ~2.6 post-COVID (VIX became more influential)
- 0050.TW theta_1 shifted from ~1.55 to ~1.39 (10.8% decrease)
- beta and persistence also shifted significantly for all assets

### 3. alpha Parameter Anomaly (SPY)
- SPY alpha is stuck at the lower bound (0.0001) for **all 54 refits**
- This means the MF-GJR short-run component for SPY has essentially no direct ARCH effect
- All short-run dynamics come from gamma (leverage effect) and beta (persistence)
- QQQ and 0050.TW have more variation in alpha

### 4. beta and Persistence — Most Stable Across Assets
- Cross-asset CV for beta: 0.023 (very consistent)
- Cross-asset CV for persistence: 0.021 (very consistent)
- Persistence ranges: SPY=0.88, QQQ=0.93, 0050.TW=0.91

### 5. Parameter-Performance Correlation
- No significant correlation between theta_1 value and QLIKE improvement (all p>0.05)
- This means MF-GJR improvement is consistent regardless of the exact theta_1 estimate
- Good news for robustness: the model improves prediction whether theta_1 is 1.2 or 3.0

### 6. Convergence
- 100% convergence rate for all three assets (54/54 SPY, 54/54 QQQ, 36/36 0050.TW)

## Conclusion
MF-GJR parameters show **moderate temporal stability** with important caveats:
- theta_1 is drifting (non-stationary) with a **significant COVID structural break**
- Within-asset variation is modest (CV < 15%) but cross-asset differences are meaningful
- The model's benefit does not depend on specific parameter values (no performance correlation)
- **For paper**: Can claim "reasonably stable" but must discuss COVID break and trend
- **SPY alpha at boundary** is a concern — may indicate model specification issue for this asset

## Output Files
- `k930_parameter_stability.py` — Main experiment script
- `k930_parameter_stability_results.json` — Full results
- `k930_parameter_trends.png` — Parameter time series plots (6 panels, 3 assets)
- `k930_cross_asset.png` — Cross-asset parameter box plots
- `k930_theta1_vs_qlike.png` — theta_1 vs QLIKE improvement scatter plots
