# 3. Data and Methodology

## 3.1 Data

We use daily closing prices for seven assets: SPDR S&P 500 ETF Trust (SPY), Invesco QQQ Trust (QQQ), iShares MSCI Emerging Markets ETF (EEM), SPDR Gold Shares (GLD), iShares Silver Trust (SLV), iShares 20+ Year Treasury Bond ETF (TLT), and Bitcoin (BTC-USD). Data are sourced from Yahoo Finance for the period January 2017 through December 2025. Daily returns are computed as simple percentage changes r_t = (P_t − P_{t−1})/P_{t−1}.

Table 1 reports descriptive statistics. All return series reject normality (Jarque-Bera p < 0.001), exhibit significant ARCH effects (Engle's LM test p < 0.001), and are stationary (ADF p < 0.001). Excess kurtosis ranges from 3.52 (GLD) to 14.61 (SPY), motivating the consideration of fat-tailed distributions for VaR estimation.

## 3.2 Volatility Models

We consider two specifications from the GARCH(1,1) family:

**GARCH(1,1):**
$$\sigma^2_t = \omega + \alpha \varepsilon^2_{t-1} + \beta \sigma^2_{t-1}$$

**GJR-GARCH(1,1)** (Glosten et al., 1993):
$$\sigma^2_t = \omega + (\alpha + \gamma \mathbf{1}_{\varepsilon_{t-1}<0}) \varepsilon^2_{t-1} + \beta \sigma^2_{t-1}$$

where $\gamma$ captures the asymmetric response to positive versus negative innovations. When $\gamma > 0$, negative returns produce higher conditional variance (standard leverage effect). When $\gamma < 0$, positive returns increase variance (inverted leverage).

All models are estimated with zero-mean specification and Normal distribution using the `arch` package in Python (Sheppard, 2023). For VaR applications, we additionally consider Student-t distributed innovations with estimated degrees of freedom.

## 3.3 Rolling Estimation

We employ a rolling window approach with re-estimation at each forecast origin. The primary window size is 504 trading days (approximately 2 calendar years), which satisfies the minimum sample size recommendation for GARCH estimation (≥500 observations; see Hwang & Valls Pereira, 2006) while avoiding contamination from distant regime changes.

For each out-of-sample date $t$, we estimate the model using data from $t−504$ to $t−1$, and produce a one-step-ahead variance forecast $\hat{\sigma}^2_t$. The realized variance proxy is the squared daily return $r^2_t$.

## 3.4 Evaluation Criteria

### 3.4.1 Statistical Loss Functions

The primary evaluation metric is the QLIKE loss function (Patton, 2011):
$$\text{QLIKE} = \frac{1}{T} \sum_{t=1}^{T} \left( \frac{r^2_t}{\hat{\sigma}^2_t} + \ln \hat{\sigma}^2_t \right)$$

QLIKE is robust to noise in the realized variance proxy and ranks forecasts consistently regardless of the proxy used, provided the proxy has equal bias across models.

### 3.4.2 Diebold-Mariano Test

We test the null hypothesis of equal predictive accuracy between models using the Diebold-Mariano test (Diebold & Mariano, 1995) with Newey-West HAC standard errors (5 lags):
$$DM = \frac{\bar{d}}{SE_{NW}(\bar{d})} \sim N(0,1)$$
where $d_t = L(r^2_t, \hat{\sigma}^2_{1,t}) - L(r^2_t, \hat{\sigma}^2_{2,t})$ is the loss differential using QLIKE.

### 3.4.3 VaR Backtesting

Value-at-Risk at confidence level $\alpha$ is computed as:
- **Normal:** $\text{VaR}_\alpha = \Phi^{-1}(\alpha) \cdot \hat{\sigma}_t$
- **Student-t:** $\text{VaR}_\alpha = t^{-1}_\nu(\alpha) \cdot \sqrt{(\nu-2)/\nu} \cdot \hat{\sigma}_t$

where $\nu$ is the degrees of freedom (fixed at 5 in our baseline, consistent with typical empirical estimates).

We apply Kupiec's (1995) unconditional coverage test (LR statistic, χ² with 1 d.f.) and Christoffersen's (1998) independence test to assess violation clustering. Annual violation counts are classified per the Basel III traffic light system (Green: 0–4, Yellow: 5–9, Red: ≥10 violations per approximately 250 trading days).

### 3.4.4 Leverage Direction Analysis

To analyze the temporal stability of the leverage direction, we estimate GJR-GARCH on non-overlapping quarterly windows (63 trading days apart, each using 504 days of data) and collect the gamma estimates. We test:
- **H0:** $E[\gamma] \geq 0$ vs. **H1:** $E[\gamma] < 0$ (inverted leverage)
using a one-sided t-test on the quarterly gamma series.

## 3.5 Volatility Targeting

Following Moreira and Muir (2017), the volatility-managed portfolio weight is:
$$w_t = \frac{\sigma_{\text{target}}}{\hat{\sigma}_t}$$

We set $\sigma_{\text{target}} = 10\%$ annualized, apply a 5-day moving average to weights for slow adjustment, and clip weights to $[0, 1.5]$. Transaction costs are not deducted as we focus on the risk-return tradeoff rather than implementable returns.
