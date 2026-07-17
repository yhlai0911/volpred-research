# K1684 E2 — 參考文獻清單

## 模型
- Corsi, F. (2009). *A Simple Approximate Long-Memory Model of Realized Volatility.* Journal of Financial Econometrics, 7(2), 174–196. — log-HAR 規格（日/週/月）。
- Glosten, L. R., Jagannathan, R., & Runkle, D. E. (1993). *On the Relation between the Expected Value and the Volatility of the Nominal Excess Return on Stocks.* Journal of Finance, 48(5), 1779–1801. — GJR-GARCH 非對稱波動。

## Range-based realized measures（own-market 已實現測度）
- Parkinson, M. (1980). *The Extreme Value Method for Estimating the Variance of the Rate of Return.* Journal of Business, 53(1), 61–65.
- Garman, M. B., & Klass, M. J. (1980). *On the Estimation of Security Price Volatilities from Historical Data.* Journal of Business, 53(1), 67–78.
- Rogers, L. C. G., & Satchell, S. E. (1991). *Estimating Variance from High, Low and Closing Prices.* Annals of Applied Probability, 1(4), 504–512.
- Yang, D., & Zhang, Q. (2000). *Drift-Independent Volatility Estimation Based on High, Low, Open, and Close Prices.* Journal of Business, 73(3), 477–492.
- Molnár, P. (2016). *High-low range in GARCH models of stock return volatility.* Physica A / Applied Economics — range-based volatility 在 GARCH/HAR 的用法。
- Todorova, N., & Souček, M. (2014). *Realized range-based estimation…* — realized-range 與 HAR。
- Martens, M., & van Dijk, D. (2007). *Measuring volatility with the realized range.* Journal of Econometrics, 138(1), 181–207.

## 預測比較 / 公平性（E2 的核心防線）
- Patton, A. J. (2011). *Volatility forecast comparison using imperfect volatility proxies.* Journal of Econometrics, 160(1), 246–256. — QLIKE 在條件無偏 proxy 下對兩模型一致排序；有偏 proxy 偏袒校準到偏誤的模型。
- Hansen, P. R., & Lunde, A. (2006). *Consistent ranking of volatility models.* Journal of Econometrics, 131, 97–121.
- Diebold, F. X., & Mariano, R. S. (1995). *Comparing Predictive Accuracy.* Journal of Business & Economic Statistics, 13(3), 253–263.
- Harvey, D., Leybourne, S., & Newbold, P. (1997). *Testing the equality of prediction mean squared errors.* International Journal of Forecasting, 13(2), 281–291. — 小樣本修正因子。
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). *…and the Cross-Section of Expected Returns.* Review of Financial Studies, 29(1), 5–68. — 多重檢定 |t|>3 門檻。

## VaR / ES backtest
- Kupiec, P. H. (1995). *Techniques for Verifying the Accuracy of Risk Measurement Models.* Journal of Derivatives, 3(2), 73–84. — POF (unconditional coverage)。
- Christoffersen, P. F. (1998). *Evaluating Interval Forecasts.* International Economic Review, 39(4), 841–862. — conditional coverage / independence。
- Acerbi, C., & Székely, B. (2014). *Back-testing Expected Shortfall.* Risk, 27(11), 76–81. — ES 的 Z1 檢定。
- Fissler, T., & Ziegel, J. F. (2016). *Higher order elicitability and Osband's principle.* Annals of Statistics, 44(4), 1680–1707. — (VaR, ES) joint elicitability。
- Patton, A. J., Ziegel, J. F., & Chen, R. (2019). *Dynamic semiparametric models for expected shortfall (and value-at-risk).* Journal of Econometrics, 211(2), 388–413. — FZ0 0-homogeneous joint loss。
- Basel Committee on Banking Supervision (1996/2013). traffic-light backtesting（1% 250-day count rule）。

## 資料
- yfinance（^GSPC, ^N225 日 OHLC 2000–2026，auto_adjust=False）。
- 註：Oxford-Man Institute Realized Library（canonical 5-min RV）官方網域已停站不可得；n≥2500 尺度下改用 range-based realized measure（見上）。
