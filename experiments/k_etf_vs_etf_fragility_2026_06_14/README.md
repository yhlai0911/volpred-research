# k_etf_vs_etf_fragility_2026_06_14

## Research Question

Do broad country and sector ETFs show the two-sided pattern implied by the recent ETF literature: strong same-day market-stress co-movement, followed by post-shock reversal or stronger common-factor dominance?

This is an honest public-data proxy experiment. It does **not** observe ETF primary-market create/redeem flows, ETF ownership, or underlying-stock order flow. It tests whether the pattern is visible in a tradable ETF panel using daily public prices.

## Motivation and Differentiation

`research_program.md` queued this direction from the 2026-06-14 journal-topic-discovery batch:

- ETF macroefficiency: ETFs may help markets incorporate macro information faster.
- ETF fragility: ETF trading/arbitrage may propagate non-fundamental demand and increase reversal or co-movement under stress.

Nearby VolPred results make this worth checking but require caution:

- K1375 found ETF-level ex-div volatility can be diluted relative to individual stocks.
- K1441 found EM ETF common-vol structure, but prior article language around high-correlation regimes needed downgrade.
- K1425 showed ETF/sector structure can be a latent factor, not necessarily alpha.

This experiment therefore avoids causal language and asks only whether a reduced-form ETF-panel signature appears in public daily data.

## Literature Preamble

1. ETF adoption and equity market macroefficiency (2025): ETF introduction can improve how markets incorporate macro information, especially in developed markets.
2. Lazo-Paz (2025), *Journal of Financial Markets*: ETF primary-market data can measure stock price fragility and non-fundamental demand exposure.
3. Ben-David, Franzoni, and Moussawi (2018), *Journal of Finance*: ETF arbitrage and flows can transmit shocks to underlying securities and create reversals.
4. Pan and Zeng (2017), ESRB working paper: liquidity mismatch can make ETF arbitrage fragile under stress.

## Data

- Source: `yfinance`
- Sample request: `2012-01-01` to `2026-06-14`
- ETF panel: `EFA`, `EEM`, `EWJ`, `EWG`, `EWZ`, `INDA`, `XLK`, `XLF`
- Shock controls: `SPY`, `^VIX`
- Return type: daily adjusted-close log returns

## Shock Definition

A macro-shock day is defined as:

`abs(SPY return)` or positive `VIX` log change above its own lagged 252-day 95th percentile.

The threshold is lagged by one day, so the event definition uses information available before the current day's return is classified. The shock **label** still uses same-day SPY/VIX returns, so H1 is a same-day market-stress co-movement test, not independent proof of macro-information efficiency and not a trading signal.

## Tests

### H1: market-stress co-movement proxy

The equal-weight ETF basket should move more on SPY/VIX shock days than normal days if ETF panel returns co-move strongly with broad market stress.

- Compare same-day absolute ETF-basket return on shock days vs normal days.
- Mann-Whitney test for distribution difference.
- Compare same-day shock absolute return vs next-day absolute return to see whether the move mostly occurs on the event day.

### H2: fragility proxy

Fragility should show up as reversal or stronger common-factor dominance after shock days.

- Reversal panel: `r_{i,t+1} = a + b r_{i,t} + c shock_t + d r_{i,t} * shock_t + asset FE + e`, with date-clustered robust standard errors.
- Common-factor event study: for shock dates spaced at least 43 trading days apart, compare ETF-panel PC1 share in the 21 trading days before the event vs the 21 trading days after the event. The 43-day gap prevents adjacent event windows from sharing observations.

## Files

- `k_etf_vs_etf_fragility_2026_06_14.py`
- `k_etf_vs_etf_fragility_2026_06_14_results.json`
- `fig_h1_response_decay.png`
- `fig_h2_common_factor_share.png`

## Main Result

Verdict: **REDUCED_FORM_SUPPORT_WITH_CAVEATS**.

The public ETF panel supports a reduced-form two-sided pattern, but only after downgrading the claim from "ETF macroefficiency / ETF fragility" to "same-day market-stress co-movement / post-shock stress signatures":

- H1 same-day stress co-movement is strong: ETF basket same-day absolute return is `2.09%` on SPY/VIX shock days vs `0.66%` on normal days, a `3.17x` ratio. Mann-Whitney p-value is `9.83e-103`.
- Same-day shock absorption is front-loaded: shock-day absolute return is `2.09%`, while next-day absolute return falls to `1.16%`; paired t-stat is `10.59`, p-value `1.83e-22`.
- H2 reversal proxy is directionally supportive and still passes at the 5% level after date clustering: the interaction term `ret_t * shock_t` in the next-day return panel is `-0.183`, date-clustered t-stat `-2.01`, p-value `0.0449`.
- H2 common-factor proxy is stronger after enforcing non-overlap: post-shock 21-day PC1 share rises from `0.605` to `0.691`, delta `+0.085`; t-stat `4.40`, p-value `4.79e-05`; Wilcoxon p-value `0.00012`; `58` non-overlapping events.

The honest reading is:

1. ETFs in this panel co-move strongly on SPY/VIX stress days.
2. Shock days are followed by a marginal but correctly signed reversal interaction and a clearer rise in common-factor dominance.
3. This is consistent with the macro-efficiency-plus-fragility literature, but it is **not** direct causal evidence from ETF ownership, primary-market create/redeem flow, or underlying-stock arbitrage records.

## Caveats

- Macro-shock days are defined from same-day SPY/VIX returns, so the H1 result is partly mechanical co-movement with broad market stress, not an exogenous macro-announcement design.
- The ETF basket mixes country ETFs and US sector ETFs. It tests traded ETF-panel behavior, not stock-level ETF ownership exposure.
- PC1 share uses 21-day windows and a 43-trading-day event gap, which prevents overlapping event windows but still does not make this a causal design.
- Results should not be used as a trading strategy without a separate strictly lagged OOS rule. This experiment is descriptive/event-study evidence.

## Follow-up

- Re-run with actual announcement calendars (CPI/FOMC/NFP) to separate scheduled macro information from generic market stress.
- If primary-market ETF create/redeem data becomes available, replace the daily price proxy with a true fragility exposure measure.
- Test whether the post-shock reversal survives transaction costs and signal lag before considering any strategy work.

## Reproduce

```bash
uv run python experiments/k_etf_vs_etf_fragility_2026_06_14/k_etf_vs_etf_fragility_2026_06_14.py
```
