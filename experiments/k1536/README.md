# K1536 — Biodiversity Transition-Risk Commodity Proxy RV and Tail Repricing

## Motivation

This experiment tests whether high biodiversity-footprint commodity proxies show higher realized volatility, downside semivariance, or negative repricing around natural-capital policy and disclosure events.

The task is motivated by the emerging commodity biodiversity-risk literature, especially the Review of Finance result that biodiversity-related transition risk is priced in commodity markets. This experiment is intentionally narrower: it uses public ETF/ETN proxies available through yfinance, not the paper's commodity futures excess returns or measured biodiversity-footprint scores.

## Differentiation

This is a proxy diagnostic for VolPred article/research triage. It is not a replication.

- High biodiversity proxy basket: `CORN`, `SOYB`, `WEAT`, `CANE`, `JO`, `WOOD`, `DBA`.
- Control commodity basket: `GLD`, `SLV`, `CPER`, `USO`, `UNG`, `PDBC`.
- Events: Kunming Declaration, Kunming-Montreal GBF adoption, EU Deforestation Regulation signing and entry into force, TNFD final recommendations, EU Nature Restoration Regulation adoption.
- Metrics: close-to-close realized variance, downside semivariance, and post-minus-pre cumulative log return.

## Related Knowledge Search

`storage/memory/knowledge.json` and `research_program.md` searches found related commodity-volatility and climate-risk entries, including commodity leverage/taxonomy, commodity volatility spillover, and K1367 climate-news duration null results. I found no prior completed K specifically testing biodiversity transition-risk commodity proxies.

## Data

- Source: yfinance daily adjusted close (`auto_adjust=True`).
- Requested period: 2018-01-01 to 2026-06-24.
- Effective sample: 2018-01-03 to 2026-06-22.
- Union trading days: 2,128.
- Available tickers: all 13 requested tickers.
- Short-history note: `JO` has 1,386 return observations; all other tickers have 2,127.

## Methodology

1. Compute daily log returns from adjusted closes.
2. Full-sample basket test: compare daily average annualized RV and downside semivariance of high-biodiversity proxies minus controls; estimate the mean difference with HAC(21) standard errors.
3. Event-window test: for each event and ticker, compute pre-window metrics over trading days `[-20, -1]` and post-window metrics over `[0, +20]`, mapping non-trading event dates to the next trading day.
4. Event inference: estimate high-minus-control post/pre diff-in-diff and bootstrap by resampling event IDs 5,000 times with fixed seed 42.
5. Multiple testing: Welch event-level diagnostics include BH q-values and Bonferroni p-values.

Lookahead guard: this is a descriptive event study, not a trading strategy. Pre windows end before the event trading date; post windows start at the event trading date. No same-day signal is multiplied by same-day return.

## Success Criteria

Evidence would require at least one of:

- positive high-minus-control RV or downside semivariance with Harvey-style `t >= 3`, or
- event-block bootstrap 95% CI excluding zero in the predicted positive direction.

## Results

Verdict: **NULL_HIGHER_RV_REJECTED**.

Full-sample RV/downside results reject the "higher RV" hypothesis in this public proxy set:

| metric | n | mean high-control | HAC t | p | 95% CI |
|---|---:|---:|---:|---:|---:|
| RV | 2,127 | -0.0754 | -7.51 | 5.78e-14 | [-0.0950, -0.0557] |
| Downside semivariance | 2,127 | -0.0449 | -6.32 | 2.57e-10 | [-0.0588, -0.0310] |

Event windows point in the expected direction for RV/downside but remain statistically weak:

| event metric | estimate | bootstrap 95% CI | p |
|---|---:|---:|---:|
| log RV ratio | +0.2426 | [-0.1769, +0.6539] | 0.283 |
| log downside ratio | +0.3834 | [-0.1786, +0.9323] | 0.177 |
| abnormal post-minus-pre cumulative return | +0.0029 | [-0.0144, +0.0232] | 0.821 |

Interpretation: the ETF proxy basket does not support a general claim that biodiversity-footprint commodity exposure has higher realized volatility. Around selected natural-capital events, the RV/downside reaction is positive but low-power and not robust enough for a reader-facing positive article.

## Outputs

- Script: `k1536.py`
- Results: `k1536_results.json`
- Figures:
  - `figures/basket_rv_event_windows.png`
  - `figures/event_diff_in_diff.png`
- Review: `codex_review.md`

## References

- Guidolin, M. and Pedio, M. (2026), "The pricing of biodiversity risk in commodity markets", Review of Finance. https://academic.oup.com/rof/article/30/1/351/8316107
- Commodity Footprints / GEIC dashboard, developed by SEI York and JNCC. https://commodityfootprints.earth/
- Convention on Biological Diversity, Kunming-Montreal Global Biodiversity Framework. https://www.cbd.int/gbf
- Taskforce on Nature-related Financial Disclosures, final recommendations release. https://tnfd.global/final-tnfd-recommendations-on-nature-related-issues-published-andcorporates-and-financial-institutions-begin-adopting/
- European Commission, Regulation on Deforestation-free Products. https://environment.ec.europa.eu/topics/forests/deforestation/regulation-deforestation-free-products_en
- European Commission, Nature Restoration Regulation timeline. https://environment.ec.europa.eu/topics/nature-and-biodiversity/nature-restoration-regulation_en

## Limitations

- ETF/ETN proxies are not commodity futures excess returns and do not reproduce biodiversity-footprint scores.
- Group membership is an economic proxy, not a measured JNCC/SEI biodiversity-intensity sort.
- Only six events are tested; event-block inference has low power.
- `WOOD` is an equity ETF proxy for forestry/timber exposure, not a physical commodity future.
- Daily close data cannot observe intraday repricing at announcement timestamps.
