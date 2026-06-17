# K1528: Market Sentiment Beta Cross-Section

**Status:** Complete
**Verdict:** NULL
**Run date:** 2026-06-17
**Task:** `research_beta_beta`

## Motivation

Hasan, Kumar and Taffler (2025) propose an emotion-based market sentiment
indicator and report that stocks with high emotion beta outperform low emotion
beta stocks. K1528 asks whether a **free, reproducible proxy version** of that
idea survives on U.S. large-cap stocks:

> Do stocks with high sensitivity to public market-sentiment shocks earn
> higher next-month returns than stocks with low sentiment beta?

This is deliberately different from prior VolPred sentiment experiments, which
mostly asked whether sentiment improves **time-series volatility prediction**
after VIX. K1528 is a **cross-sectional return strategy** test.

## Literature

- Hasan, Kumar and Taffler (2025), "Investor Emotions and Asset Prices",
  *Financial Analysts Journal* 81(3), 122-149. The paper develops a
  market-level emotion indicator, estimates firm-level emotion betas, and
  reports a high-minus-low emotion beta premium with alpha above 6%.
  DOI: `10.1080/0015198X.2025.2509485`.
- Baker and Wurgler (2006), "Investor Sentiment and the Cross-Section of Stock
  Returns", *Journal of Finance* 61(4), 1645-1680. The canonical sentiment
  cross-section result: sentiment should matter more for hard-to-arbitrage,
  subjective-valuation stocks.
- Glushkov, "Sentiment Beta" (working paper). Defines stock-level sentiment
  beta as sensitivity of stock returns to sentiment changes.
- O'Sullivan, Zhu and Foran, "Sentiment Versus Liquidity Pricing Effects in the
  Cross-Section of UK Stock Returns", *Journal of Asset Management*. A related
  non-U.S. sentiment-risk pricing application.

## Data

- Stock data: yfinance adjusted close, `auto_adjust=False`, then use
  `Adj Close`.
- Period: 2004-01-01 to 2026-06-14.
- Universe: fixed current liquid U.S. large-cap list declared in
  `k1528.py` (AAPL, MSFT, AMZN, ...).
- Sentiment proxies:
  - `VIX_optimism = -diff(log(VIX))`, positive when fear falls.
  - `UMCSENT_change = diff(UMCSENT) / 100`, Michigan consumer sentiment monthly
    change from FRED.

## Major Limitation

This is **not** a clean replication of Hasan/Kumar/Taffler because their
emotion dictionary is not used. It is also not CRSP-grade because the fixed
large-cap universe has survivorship bias. A NULL result here means:

> Free VIX/UMCSENT proxies do not reproduce the reported emotion-beta premium
> in this implementable pilot.

It does **not** falsify the proprietary emotion-index paper.

## Method

For each sentiment proxy:

1. Convert daily adjusted prices to monthly returns.
2. For each stock and month `t`, estimate rolling 60-month regression using
   months `[t-60, t-1]` only:

   `r_i = a_i + beta_mkt_i * r_SPY + beta_sent_i * sentiment_proxy + e_i`

3. At month `t`, sort stocks by `beta_sent_i(t)` into quintiles.
4. Hold equal-weight top-quintile minus bottom-quintile portfolio for month `t`.
5. Report:
   - High, low, and high-minus-low annualized returns.
   - DM test via `volpred.stats.model_evaluation.strategy_dm_test`.
   - Fama-MacBeth monthly cross-sectional slope of next return on sentiment
     beta, with and without market-beta control.
   - 6-month moving-block bootstrap CI for long-short mean return.

## Lookahead Controls

- Rolling beta for month `t` uses only `[t-60, t-1]`.
- Month `t` return is never used to estimate month `t` beta.
- The stock universe is a fixed declared list. This avoids dynamic membership
  lookahead but creates survivorship bias, which is disclosed as a limitation.
- yfinance uses `auto_adjust=False`; the script explicitly selects `Adj Close`.
- Random bootstrap uses `seed=42`.

## Success Criteria

K1528 is `PASS` only if at least one proxy satisfies all of:

- High-minus-low annualized return is positive.
- High vs low DM test exceeds Harvey threshold `|t| > 3`.
- Fama-MacBeth sentiment-beta slope is positive and Newey-West `|t| > 3`.

If direction is positive but the Harvey/Fama-MacBeth gates fail, verdict is
`CONDITIONAL_DIRECTIONAL_ONLY`. If direction is negative or mixed, verdict is
`NULL`.

## Outputs

- `k1528.py`
- `k1528_results.json`
- `figures/k1528_cumulative_long_short.png`
- `figures/k1528_summary_bars.png`

## Results

| Proxy | Months | Median stocks | High ann. ret | Low ann. ret | High-Low ann. | DM t | Fama-MacBeth t | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| VIX optimism | 210 | 52 | 18.13% | 27.64% | -9.51% | 1.90 | -2.13 | NULL |
| UMCSENT change | 208 | 52 | 22.42% | 21.75% | 0.67% | -0.18 | -0.29 | NULL |

Interpretation:

- The VIX-based free proxy goes in the wrong direction: high sentiment-beta
  stocks underperform low sentiment-beta stocks by about 9.5% annualized.
- UMCSENT has the desired high-minus-low sign, but the magnitude is only 0.67%
  annualized and the DM/Fama-MacBeth statistics are near zero.
- No proxy passes the Harvey `|t| > 3` standard or the Fama-MacBeth gate.

Final conclusion: K1528 is a **NULL result for free sentiment proxies**. It
does not falsify Hasan/Kumar/Taffler's proprietary emotion-index result; it
only says the implementable VIX/UMCSENT proxy version is not robust in this
fixed large-cap universe.
