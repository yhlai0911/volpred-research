# References — K1481 Inventory-surprise commodity RV regime feature

## Core methodology

1. **Corsi, F.** (2009). A simple approximate long-memory model of realized volatility. *Journal of Financial Econometrics*, 7(2), 174–196. doi:10.1093/jjfinec/nbp001.
   - HAR-RV baseline specification with daily/weekly/monthly lagged log-RV.

2. **Patton, A. J.** (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246–256. doi:10.1016/j.jeconom.2010.03.034.
   - QLIKE loss function robust to noise in the RV proxy. Justifies QLIKE as the primary metric here given Garman-Klass is itself a proxy.

3. **Diebold, F. X., & Mariano, R. S.** (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics*, 13(3), 253–263. doi:10.1080/07350015.1995.10524599.
   - DM test of equal predictive accuracy. We use Newey-West HAC variance (lag = 5) and stationary block bootstrap (block ≈ √n) for finite-sample p-values per Diebold (2015) recommendations.

## Inventory shocks and crude vol

4. **Kilian, L.** (2008). Exogenous oil supply shocks: How big are they and how much do they matter for the U.S. economy? *Review of Economics and Statistics*, 90(2), 216–240. doi:10.1162/rest.90.2.216.
   - Identifies inventory disturbances as structural supply shocks driving WTI price dynamics. Frames the research question.

5. **Bjornson, B., & Carter, C. A.** (1997). New evidence on agricultural commodity return performance under time-varying risk. *American Journal of Agricultural Economics*, 79(3), 918–930. doi:10.2307/1244435.
   - Treats commodity inventories as a state variable for time-varying risk premia — generalisable rationale for inventory-conditioned vol modelling.

6. **Garman, M. B., & Klass, M. J.** (1980). On the estimation of security price volatilities from historical data. *Journal of Business*, 53(1), 67–78. doi:10.1086/296072.
   - Garman-Klass range-based RV estimator used as our daily RV proxy.

## ML-on-commodities context

7. **CFA Institute Research Foundation** (2025). *Machine Learning in Commodity Futures: An Empirical Survey*. (Section on inventory features as fundamental regressors for energy vol prediction.)

## Prior intra-project K notes (not citations, audit trail)

- K1129 — GAS-t commodity NULL (vol-model family change, no exog feature).
- K1136 — Robust vol methods commodity NULL.
- K1135 — Skew-t GAS commodity (QLIKE NULL, VaR/ES rescued).
- K1402/K1403 — HAR-RV quantile commodity (had fair-comparison-violation + bootstrap-bug; symmetric refinement applied here).

## Data sources

- **WTI futures (CL=F)**: yfinance daily OHLC, 2010-01-04 → 2026-05-29.
- **EIA WCESTUS1**: Weekly U.S. Ending Stocks excluding SPR of Crude Oil, downloaded from `https://www.eia.gov/dnav/pet/hist_xls/WCESTUS1w.xls` on 2026-06-14. 1982-08-20 → 2026-06-05 weekly observations.
