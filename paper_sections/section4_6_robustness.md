# 4.6 Robustness Checks

## 4.6.1 Window Size and Proxy Sensitivity

We verify that our leverage direction findings are robust to the estimation window. Re-estimating all models with w = 252 and w = 756 produces qualitatively identical gamma sign classifications for all five primary assets. Gold's gamma remains negative in >85% of quarterly estimates regardless of window size.

The QLIKE ranking between GARCH and GJR is preserved when using the Parkinson (1980) range-based realized variance estimator as proxy instead of squared returns (DM test p < 0.001 for SPY, confirming GJR superiority). This is consistent with the theoretical result of Patton (2011) that QLIKE rankings are invariant to the choice of consistent variance proxy.

The optimal window for QLIKE minimization is asset-specific: SPY and GLD perform best with w = 504, while TLT performs best with w = 252 (reflecting faster regime changes in interest rate volatility). We adopt w = 504 as the baseline for cross-asset comparability.

We also verify that EGARCH's leverage parameter exhibits consistent sign alignment with GJR's γ: SPY (EGARCH γ = −0.20, standard), GLD (EGARCH γ = +0.09, inverted), TLT (EGARCH γ ≈ 0, neutral)—all consistent with the GJR classification, accounting for the opposite sign convention between the two models.

## 4.6.2 Cross-OOS Period Robustness

All key findings are tested on at least two non-overlapping out-of-sample periods: a primary period (2023–2024) and a validation period (2025). For SPY, we additionally test on 2022–2023 (high-volatility environment) and 2020–2025 (6-year comprehensive test).

The leverage direction taxonomy is consistent across all tested periods. GJR-GARCH significantly outperforms for SPY across all OOS periods (DM p < 0.03), while GARCH and GJR remain statistically equivalent for GLD and TLT across all periods (DM p > 0.10).

## 4.6.3 Distribution Robustness

The Student-t VaR results are robust to the choice of degrees of freedom. We test df ∈ {4, 4.5, 5, 5.5, 6, 7, 8, 10} and find that Basel III Green Zone compliance for SPY is achieved for all df ≤ 6 (Table 4b). At df = 7, years 2020 and 2024 each produce 5 violations (Yellow Zone), and the result deteriorates further at higher df.

Rolling estimation of df jointly with GARCH parameters reveals substantial time variation: df ranges from 4.27 (2019, post-volatility surge) to over 100 (2023–2024, quiet market where returns approach normality). The mean estimated df is approximately 6.5 but with high variance. We directly compare fixed df = 5 against jointly estimated df in each rolling window. The jointly estimated approach produces *more* violations (24 vs. 17 for SPY) and achieves Green Zone in only 5/6 years versus 6/6 for fixed df. The failure occurs because estimated df increases sharply during quiet markets (averaging 46–52 in 2023–2024, approaching the Normal distribution), narrowing the VaR threshold precisely before the market transitions to higher volatility. When turbulence returns, the previously narrow VaR is breached immediately.

This finding strongly supports using a fixed conservative df (≤ 6) rather than estimated df for VaR applications. The fixed approach provides robust coverage across the full sample at the cost of slight over-conservatism during calm periods—a preferable trade-off for regulatory compliance.

## 4.6.4 The GARCH Forecasting Ceiling

We investigate whether more complex models can improve upon the GJR-GARCH(1,1) baseline for SPY. The standardized residuals z_t = ε_t / σ̂_t from the optimal GJR model show no significant autocorrelation at any lag (Ljung-Box test on z²_t: p = 0.76 at 5 lags, p = 0.94 at 10 lags, p = 0.97 at 20 lags). This indicates that the GARCH filter has extracted all exploitable variance dynamics from daily returns.

Consistent with this diagnostic, we conduct a comprehensive ablation study with twelve alternative approaches: LSTM/GRU cascades (DM p > 0.27), GARCH-LSTM hybrids (unstable factor, std = 1.16), HAR multi-scale features (QLIKE worse by 0.28%), EMD decomposition (−0.04%), GARCH Stacking with Ridge regression (−5.3%, Ridge zeroes all features), GARCH-X with VIX (no improvement, time-scale mismatch), expanding windows (worst QLIKE, distant regime contamination), and residual higher-order moments (+2.7pp R² only). All fail to improve upon GJR-GARCH(1,1).

The unified explanation for these null results is that three parameters (ω, α+γ, β) are sufficient to capture all exploitable variance autocorrelation structure in daily returns. Improvements can only come from information beyond daily close-to-close returns—specifically, intraday microstructure data. We note that overnight returns contribute 44.3% of total variance, confirming that return-based GARCH models process all available daily information.

These null results establish a practical ceiling for daily-frequency volatility forecasting: QLIKE ≈ −9.034 for SPY with GJR-GARCH(1,1), w = 504.

## 4.6.5 Mincer-Zarnowitz Forecast Evaluation

We assess forecast unbiasedness via the Mincer-Zarnowitz regression r²_t = α + β σ̂²_t + ε_t, with HAC standard errors (Newey-West, 5 lags). An unbiased forecast implies α = 0 and β = 1.

For SPY (GJR, 2023–2024), we find α ≈ 0 (p = 0.051, borderline) and β = 0.65 (p = 0.014 for H₀: β = 1). The β < 1 result indicates that GARCH underestimates variance during high-volatility episodes, consistent with the delayed response documented in our crisis adaptation analysis. For TLT, both α = 0 and β = 1 are not rejected (p > 0.05), indicating well-calibrated forecasts for the asset with the most stable volatility dynamics. For GLD, the regression R² is extremely low (0.004), reflecting the high noise level of the squared return proxy for gold's volatile daily returns.

The low R² values (0.004–0.047) across assets are expected when using r² as the realized variance proxy, as a single squared daily return has a signal-to-noise ratio of approximately unity. This does not invalidate the GARCH forecasts—QLIKE ranking, which is proxy-invariant (Patton, 2011), confirms that GJR-GARCH is the optimal specification regardless of proxy noise.

## 4.6.6 Model Specification

Our main results use GJR-GARCH(1,1) with zero-mean and Normal distribution for the forecast generation. We verify that using AR(1)-GARCH instead of Zero-mean GARCH does not materially change the QLIKE rankings or the gamma sign classifications. The choice of p = q = 1 is supported by information criteria (AIC/BIC both favor (1,1) over (2,1) or (1,2) for all assets in over 90% of estimation windows).
