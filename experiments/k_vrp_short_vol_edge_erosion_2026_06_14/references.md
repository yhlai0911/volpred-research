# K1476 References

## Core literature

1. **Bollerslev, T., Tauchen, G., & Zhou, H. (2009).** Expected stock returns and variance risk premia. *Review of Financial Studies*, 22(11), 4463–4492.
   - DOI: https://doi.org/10.1093/rfs/hhp008
   - Canonical VRP construction: `VRP_t = E_t^Q[var(t,t+1)] − E_t^P[var(t,t+1)]`, empirically proxied by `VIX^2 − RV^2`.
   - Establishes VRP's positive in-sample predictability for short-horizon equity returns.

2. **Carr, P., & Wu, L. (2009).** Variance risk premiums. *Review of Financial Studies*, 22(3), 1311–1341.
   - DOI: https://doi.org/10.1093/rfs/hhn038
   - Cross-asset documentation of variance swap rates above realized variance; sign and economic magnitude of VRP.

3. **Cboe (2024).** Variance Risk Premium Research Note.
   - https://www.cboe.com/insights/posts/the-variance-risk-premium/
   - Industry view of VRP persistence and short-vol strategy implications, including the Feb 5, 2018 XIV blowup episode.

4. **Chicago Fed (2025).** "The Decline of the Variance Risk Premium" (working paper / blog framing — task trigger source).
   - The hypothesis source for K1476: post-2018 VRP magnitude allegedly compresses.

## Related VolPred-internal K entries (knowledge.json)

- K430: VRP Predictability — IS significant (t=4.38) but OOS DM p=0.163 — null at OOS.
- K734: VRP NOT tradeable beyond 12/VIX threshold.
- K913: VRP Return Prediction — NULL at all horizons (OOS R² negative).
- K1040: VRP Return Predictability — VIX monthly effective (R²=5.63%), g_t no incremental info.
- K539: VRP Carry strategies — 4 specs all null; VRP<0 actually a bullish reversal signal.

## Data

- Yahoo Finance: ^VIX, ^GSPC daily close (2006-01 onward).
- Yahoo Finance: SVXY daily close (2011-10-04 onward; ProShares Short VIX Short-Term Futures ETF).
- Yahoo Finance: VXX daily close — note: only the iPath Series B VXX (post Jan 25, 2018 reissue) is available; original Barclays VXX (2009-01 to 2018-01) is not retrievable via yfinance, so short-VXX comparisons are only meaningful in regime B.

## Methodology references

- **Newey, W. K., & West, K. D. (1994).** Automatic lag selection in covariance matrix estimation. *Review of Economic Studies*, 61(4), 631–653. DOI: https://doi.org/10.2307/2297912 — used for HAC lag formula `lag = floor(4 * (T/100)^(2/9))`.
- **Diebold, F. X., & Mariano, R. S. (1995).** Comparing predictive accuracy. *Journal of Business & Economic Statistics*, 13(3), 253–263.
