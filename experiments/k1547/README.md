# K1547: Managed-futures ETF proxy crisis-alpha test

- **Experiment ID**: `K1547`
- **Task**: `research_cta_crisis_alpha_etf_proxy_trend_following_stres`
- **Status**: completed
- **Created**: 2026-06-24

## Research Question

CTA / managed-futures literature often frames trend-following as a source of "crisis alpha". This experiment asks a narrower, investable-proxy question:

> Using only free yfinance ETF proxies (`DBMF`, `KMLM`, `CTA`) plus `SPY`, `AGG`, and `^VIX`, does a managed-futures ETF proxy deliver positive excess return versus SPY in stress regimes, and does a 12-month time-series momentum timing overlay improve that result?

## Literature Preamble

- Moskowitz, Ooi, and Pedersen (2012), *Time Series Momentum*, Journal of Financial Economics: documents 1-12 month return persistence across futures markets and motivates the 12-month signal.
- Hurst, Ooi, and Pedersen (2017), *A Century of Evidence on Trend-Following Investing*, Journal of Portfolio Management: reports long-run positive trend-following performance and low correlation to traditional assets.
- Greyserman and Kaminski (2014), *Trend Following with Managed Futures: The Search for Crisis Alpha*, and Kaminski (2011), *In Search of Crisis Alpha*: motivate the crisis-alpha framing for managed futures.

## Design

1. Download adjusted close prices from yfinance for `DBMF`, `KMLM`, `CTA`, `SPY`, `AGG`, and `^VIX`.
2. Build `CTA_EW`: equal-weight daily return across listed/available managed-futures ETFs. There is no pre-launch backfill.
3. Build `CTA_TSMOM_252D`: `sign(trailing 252-day CTA_EW return).shift(1) * CTA_EW return`. Dates before a 252-day signal exists are excluded, not counted as cash alpha.
4. Define stress regimes only with lagged information:
   - `stress_vix80_lagged`: prior-close VIX above its rolling 756-day 80th percentile.
   - `stress_spy_dd10_lagged`: prior-close SPY drawdown at or below -10%.
   - `stress_union`: either condition.
5. Compare `CTA_EW` and `CTA_TSMOM_252D` against SPY using paired excess-return t-stats and block-bootstrap confidence intervals.

## Anti-Bias Rules

- Signals explicitly use `.shift(1)`.
- VIX and drawdown regime labels use prior-close information.
- Random seed is fixed at `1547`.
- Pass gate requires paired excess-return `t > 3` plus bootstrap 95% CI lower bound above zero.

## Files

- `k1547.py`: reproducible script.
- `k1547_results.json`: results.
- `codex_review.md`: source-level review.
- `k1547_data.csv`: adjusted close input cache from yfinance.
- `fig1_cumulative_returns.png`: cumulative returns.
- `fig2_stress_excess.png`: stress-regime cumulative excess return.
- `fig3_regime_excess_ci.png`: annualized excess returns with bootstrap CI.
- `fig4_crisis_windows.png`: crisis-window returns.

## Result Summary

Verdict: **NULL_OR_NEGATIVE_STRESS_ALPHA_FOR_FREE_ETF_PROXY**.

The long-only managed-futures ETF proxy (`CTA_EW`) did not beat SPY in the lagged stress-union regime. Annualized mean excess return vs SPY was `-26.0%`, paired `t=-1.13`, and the block-bootstrap daily mean CI crossed zero (`[-0.00247, 0.00047]`). The 252-day timing overlay was weaker: annualized mean excess return `-35.7%`, paired `t=-1.60`, CI crossing zero.

The one strong-looking subperiod is 2022 inflation stress: `CTA_EW` beat SPY by `+77.2%` annualized mean excess, paired `t=2.12`, bootstrap CI above zero. This does **not** pass the project Harvey gate (`t>3`) and does not survive as a full stress-regime statement because 2025 tariff stress was negative and 2020 has no valid 252-day timing signal.

Interpretation: free ETF proxies show that managed-futures products can help in specific equity bear markets, especially 2022, but this sample does not support a general crisis-alpha claim under the strict gate. It also does not support adding a simple 12-month timing overlay on top of the ETF proxy.
