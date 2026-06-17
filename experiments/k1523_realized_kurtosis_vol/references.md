# K1520 References

## Core methodology
- **Corsi, F. (2009).** "A Simple Approximate Long-Memory Model of Realized Volatility." *Journal of Financial Econometrics*, 7(2), 174–196. — HAR-RV baseline; log-RV specification.
- **Patton, A. J. (2011).** "Volatility forecast comparison using imperfect volatility proxies." *Journal of Econometrics*, 160(1), 246–256. — QLIKE consistency under imperfect proxy; choice of loss function.
- **Diebold, F. X., & Mariano, R. S. (1995).** "Comparing Predictive Accuracy." *Journal of Business & Economic Statistics*, 13(3), 253–263. — DM test for OOS forecast comparison.
- **Harvey, C. R. (2017).** "Presidential Address: The Scientific Outlook in Financial Economics." *Journal of Finance*, 72(4), 1399–1440. — |t|>3 threshold for new empirical claims (multiple-testing adjustment).
- **Newey, W. K., & West, K. D. (1987).** "A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix." *Econometrica*, 55(3), 703–708. — HAC estimator for overlapping DM loss differences.

## Higher-moment vol forecasting
- **Amaya, D., Christoffersen, P., Jacobs, K., & Vasquez, A. (2015).** "Does realized skewness predict the cross-section of equity returns?" *Journal of Financial Economics*, 118(1), 135–167. — Original realized skewness / kurtosis definitions; standardized moments.
- **Neuberger, A. (2012).** "Realized Skewness." *Review of Financial Studies*, 25(11), 3424–3455. — Martingale-consistent realized skewness; theoretical grounding.
- **Bollerslev, T., Li, S. Z., & Zhao, B. (2020).** "Good Volatility, Bad Volatility, and the Cross-Section of Stock Returns." *Journal of Financial and Quantitative Analysis*, 55(3), 751–781. — Higher-order moment risk premia.
- **Conrad, J., Dittmar, R. F., & Ghysels, E. (2013).** "Ex Ante Skewness and Expected Stock Returns." *Journal of Finance*, 68(1), 85–124. — Option-implied higher moments; supplementary lit on tail-risk forecasting.

## Semi-variance / signed jump (baseline for comparison)
- **Barndorff-Nielsen, O. E., Kinnebrock, S., & Shephard, N. (2010).** "Measuring downside risk-realised semivariance." In *Volatility and Time Series Econometrics*. — Semi-variance decomposition; K1063 baseline.
- **Patton, A. J., & Sheppard, K. (2015).** "Good Volatility, Bad Volatility: Signed Jumps and the Persistence of Volatility." *Review of Economics and Statistics*, 97(3), 683–697. — Signed-jump as RV+ minus RV-.

## Prior experiments in this lineage
- K471: Time-varying higher moments scoping memo (knowledge.json).
- K1057: Realized jump NULL.
- K1063: Semi-variance PASS (HAR-SV beats HAR-RV).
- K1084: Higher moments NULL on 60-day 5-min sample (PRELIMINARY); recommended longer-sample re-test → this is K1520.
- K1213/K1216b/K1216c: Pooled-MLE multi-start lessons (informs methodology rules).
