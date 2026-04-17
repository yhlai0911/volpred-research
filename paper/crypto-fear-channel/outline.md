# Paper 6: The Crypto Fear Channel — Asymmetric BTC–Equity Volatility Spillover

**Status**: kick-off (outline only, body pending)
**Created**: 2026-04-17
**Lead**: Yi-Hao Lai (Da-Yeh University)
**Target journal**: Journal of International Financial Markets, Institutions & Money (1st), Journal of Empirical Finance (2nd), Finance Research Letters (backup for short-form)

## Key empirical material

All from VolPred experiments (2015-02 ~ 2026-04, N=2,812 daily obs):

- **K639** — Confirmed BTC → SPY RV Granger causality at lag 1-10.
- **K746b** — BTC volatility asymmetrically Granger-causes VIX (negative-BTC branch dominates).
- **K1025** — Full spillover framework: asymmetric Granger, quantile regression, rolling Diebold-Yilmaz spillover index, EWMA correlation by VIX regime, 5-subperiod structural change.

## Central claim

**The crypto fear channel is asymmetric, tail-concentrated, and regime-dependent.**

1. BTC downside volatility predicts VIX / SPY RV (statistically and economically).
2. BTC upside volatility has no analogous effect on equity fear.
3. Tail dependence (QR β) amplifies 8.5× between τ=0.5 and τ=0.95 — spillover is a **crisis-time phenomenon**, not a uniform channel.
4. COVID 2020 is a structural watershed: Granger-significance appears only in that sub-period; 2015-2017, 2018-2019, 2021-2022, 2023-2026 are all non-significant.
5. BTC is a net **receiver** (not sender) in the Diebold-Yilmaz framework — rehabilitates the narrative to "crypto as a fear amplifier, not a fear originator".

## Honest negative findings

- Out-of-sample forecasting: BTC RV does **not** statistically improve AR(VIX) forecasts (DM t < 2). Granger ≠ predictive power. Must be reported transparently.
- Rolling correlation shows BTC-SPY correlation rises in crisis → BTC is **not a safe-haven**, contradicting 2017-era media claims.

## Paper outline (12 sections, ~30 pages target)

1. Introduction (3 pages)
2. Literature review — spillover, crypto, fear gauge (3 pages)
3. Data and preliminaries (2 pages)
4. Methodology
   - 4.1 Granger causality (symmetric and asymmetric)
   - 4.2 Quantile regression for tail dependence
   - 4.3 Diebold-Yilmaz spillover index (252-day rolling)
   - 4.4 DCC / EWMA correlation by VIX regime
   - 4.5 Forecasting evaluation framework (DM test + Harvey threshold)
5. Main results
   - 5.1 Asymmetric Granger causality (table + fig)
   - 5.2 Tail dependence (QR coefficient path)
   - 5.3 Regime-conditional correlation (bar chart by VIX regime)
6. Robustness
   - 6.1 Rolling spillover (COVID vs pre/post)
   - 6.2 Sub-period Granger (5 regimes)
   - 6.3 BTC-specific microstructure checks (ETF era vs pre-ETF 2015-2018)
7. Forecasting and economic significance
   - 7.1 Out-of-sample DM test (honest NULL)
   - 7.2 Crisis-period sub-forecast
8. Discussion
   - Asymmetry mechanism — retail sentiment / margin / liquidation cascade
   - Why Granger ≠ forecastability
   - Policy implications for crypto ETF vol management
9. Conclusion
10. References
11. Appendices
12. Data availability statement

## Target results table skeleton

| Claim | Source | Key stat |
|-------|--------|----------|
| BTC downside Granger-causes VIX | K746b | F(5) = [from asymmetric_granger.btc_neg_to_vix] |
| BTC upside does not | K746b | F(5) not significant |
| Tail dependence amplification | K1025 | QR β ratio (τ=0.95 / τ=0.5) = 8.5× |
| COVID-only Granger | K1025 | F(5)=11.05 in 2020; NS in other sub-periods |
| Crisis correlation rise | K1025 | corr(BTC, SPY) by VIX regime |
| No OOS forecasting improvement | K1025 | DM t < 2, honest NULL |

## Literature gaps (to close in lit review)

- Prior BTC-equity spillover literature focuses on level/return, not **asymmetric volatility** spillover.
- Most prior work stops at 2020 or excludes COVID.
- No prior paper combines asymmetric Granger + tail QR + Diebold-Yilmaz + honest OOS null in one framework.
- Closest: Matkovskyy & Jalan (2019), Corbet et al. (2018), Bouri et al. (2020) — but each covers subset.

## Open decisions (before kick-off writing)

1. Include dog-tail / GME-like memecoin as "alternative fear channel" comparison? (would need new experiment)
2. Add implied-vol derivatives (Deribit BTC options IV) — data availability issue (not free historically).
3. One-asset (SPY) vs multi-asset (SPY + GLD + TLT) receiver?
4. Forecasting section length — report honestly-NULL or relegate to appendix?

## Next concrete steps (main thread)

1. ✅ This outline (done 2026-04-17)
2. Draft Abstract + Introduction (~3 pages) — main thread, 1-2 hour session
3. Literature review drafting — may dispatch subagent for focused lit collection
4. Methodology section — reuse K1025 method descriptions directly
5. Results tables from K1025/K639/K746b JSON (no new experiment needed at this stage)
6. Pre-review checklist using `latex-academic-reviewer` + `citation-verifier` skills
7. First review via `academic-finance-reviewer` skill

## Abstract draft (v0, 150 words target)

*Using daily returns on SPY, BTC, and VIX from 2015-02 to 2026-04 (N=2,812), we document three stylized facts about the crypto-equity volatility spillover: (i) the spillover is asymmetric — BTC downside volatility Granger-causes VIX, but upside volatility does not; (ii) the spillover is tail-concentrated — quantile regression coefficients amplify 8.5× between the median and the 95th quantile; (iii) the spillover is regime-dependent — COVID-2020 is a structural watershed, with Granger significance concentrated in that sub-period and absent in both pre-COVID and post-COVID regimes. In the Diebold-Yilmaz framework, BTC is a net receiver of spillovers, reframing the narrative from "crypto as fear originator" to "crypto as fear amplifier". Out-of-sample forecasting shows BTC volatility does not statistically improve AR(VIX) forecasts, highlighting the distinction between Granger causality and predictive power.*

## References (starter list — to be expanded in lit review draft)

- Diebold, F.X. & Yilmaz, K. (2012). *Journal of Econometrics*, 182(1), 119-134. "Better to Give than to Receive"
- Engle, R.F. (2002). *JBES*, 20(3), 339-350. "Dynamic Conditional Correlation"
- Koenker, R. & Bassett, G. (1978). *Econometrica*, 46(1), 33-50. "Regression Quantiles"
- Harvey, C.R., Liu, Y., Zhu, H. (2016). *RFS*, 29(1), 5-68. "... and the Cross-Section of Expected Returns"
- Bouri, E. et al. (2020). *Finance Research Letters*, 37, 101764. "Cryptocurrencies and stock market indices"
- Corbet, S. et al. (2018). *Economics Letters*, 165, 28-34. "Cryptocurrency reaction to FOMC Announcements"
- Matkovskyy, R. & Jalan, A. (2019). *Finance Research Letters*, 31, 388-393.
