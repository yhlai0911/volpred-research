# Mutual-Fund-to-ETF Conversion and Wrapper Liquidity

## Question

Do mutual-fund-to-ETF conversion events change post-listing wrapper liquidity, converted ETF tracking noise, or underlying category realized variance?

Backlog item:

> Mutual-fund-to-ETF / active ETF conversion event 是否改變 wrapper liquidity 與 underlying RV.

## Data

- Event calendar: 10 U.S. mutual-fund-to-ETF conversion/listing rows from 2021-03-26 to 2022-06-13.
- Issuer batches:
  - Guinness Atkinson / SmartETFs: `DIVS`, `ADIV`, listed 2021-03-26.
  - Dimensional: `DFUS`, `DFAC`, `DFAS`, `DFAT`, conversion 2021-06-11 and listed 2021-06-14.
  - J.P. Morgan Asset Management: `JCPI`, `JMEE`, `JPRE`, `JIRE`, listed from 2022-04-11 to 2022-06-13.
- Category proxies:
  - `VIG`, `AAXJ`, `VTI`, `IWB`, `IWM`, `IWN`, `TIP`, `VNQ`, `EFA`.
- Price and volume data: yfinance daily `Adj Close` and `Volume`, downloaded with `auto_adjust=False`, sample start 2020-01-01.

Final panels:

- 10 wrapper-liquidity rows.
- 20 conversion-proxy underlying RV rows.
- 6 unique listing dates for underlying-RV inference.
- 25,029 same-proxy, same-year placebo anchor rows.

## Method

### Wrapper Liquidity

For each converted ETF:

1. Exclude the listing day itself.
2. Define early window as `T+1..T+21`.
3. Define later window as `T+43..T+63`.
4. Compute converted ETF dollar-volume ramp: `log(late dollar volume / early dollar volume)`.
5. Compute converted ETF Amihud-style improvement: `log(early abs-return-per-dollar-volume / late abs-return-per-dollar-volume)`.
6. Subtract the same metric for a category proxy over the same dates.
7. Compute tracking-noise improvement as `log(early mean abs(converted ETF return - proxy return) / late mean abs(diff))`.

Positive values mean liquidity or tracking quality improved after the first post-listing month.

### Underlying RV

For each conversion row's category proxy:

1. Baseline RV: `T-60..T-11`.
2. Post windows: `T+1..T+5` and `T+1..T+22`.
3. Outcome: `log(post RV / baseline RV)`.
4. Listing-day returns are excluded from primary windows.
5. Inference is aggregated to unique listing-date means, so the four Dimensional conversions on 2021-06-14 do not count as four independent market days.
6. Placebo uses same-proxy, same-year non-event anchors, excluding plus/minus 30 calendar days around true listing dates.

Random procedures use seed `42`. Bootstrap uses 10,000 draws; placebo uses 3,000 draws.

## Files

- `research_mutual_fund_to_etf_active_etf_conversion_event_w.py`: reproducible script.
- `research_mutual_fund_to_etf_active_etf_conversion_event_w_results.json`: machine-readable results.
- `data/raw/yfinance_ohlcv_*.csv`: raw OHLCV caches.
- `data/wrapper_liquidity_metrics.csv`: ETF-level wrapper diagnostics.
- `data/underlying_event_metrics.csv`: conversion-row proxy RV metrics.
- `data/underlying_date_level_metrics.csv`: unique listing-date RV metrics.
- `data/underlying_anchor_metrics.csv`: same-year placebo anchors.
- `data/summary.csv`: statistical summary table.
- `figures/wrapper_liquidity_diagnostics.png`: wrapper metrics.
- `figures/underlying_rv_event_heatmap.png`: underlying RV event heatmap.

## References

- Business Wire, Guinness Atkinson conversion date release: https://www.businesswire.com/news/home/20210302005875/en/Guinness-Atkinson-Asset-Management-Proceeds-to-Convert-Two-Mutual-Funds-into-ETFs
- Dimensional conversion/listing release: https://www.dimensional.com/us-en/newsroom/dimensional-lists-four-new-etfs-following-the-industrys-largest-mutual-fund-to-etf-conversion
- Dimensional SEC 497 information statement: https://www.sec.gov/Archives/edgar/data/1816125/000179420221000103/dimensionaletf497.htm
- Markets Media / J.P. Morgan conversion completion release: https://www.marketsmedia.com/j-p-morgan-am-converts-four-mutual-funds-to-etfs/
- Morningstar conversion-date list for J.P. Morgan funds: https://advisor.morningstar.com/ReleaseNewsLive/releasePopUp.aspx?Id=1665&name=Enterprise+Components&type=Product
- Federal Reserve FEDS Notes, "Implications of Growth in ETFs: Evidence from Mutual Fund to ETF Conversions": https://www.federalreserve.gov/econres/notes/feds-notes/implications-of-growth-in-etfs-evidence-from-mutual-fund-to-etf-conversions-20251119.html
- Baer, McCabe, and Smith, "Converting Mutual Funds into ETFs", The Investment Lawyer, 2021: https://www.ropesgray.com/-/media/files/articles/2021/july/il_0621_baer-mccabe-smith/il_0621_baer-mccabe-smith.pdf
- ICI, "Mutual Fund to ETF Conversion: Operational Considerations": https://www.ici.org/24-ppr-mf-to-etf-conversion

## Current Result

Run:

```bash
uv run python experiments/research_mutual_fund_to_etf_active_etf_conversion_event_w/research_mutual_fund_to_etf_active_etf_conversion_event_w.py
```

Verdict: `weak_raw_only`.

Key diagnostics:

- Wrapper adjusted volume ramp: mean `+0.0559`, one-sided p `0.390`, Holm p `1.000`, bootstrap 95% CI `[-0.313, +0.414]`.
- Wrapper adjusted Amihud improvement: mean `-0.0436`, one-sided p `0.624`, Holm p `1.000`, bootstrap 95% CI `[-0.294, +0.197]`.
- Wrapper tracking-noise improvement: mean `+0.2484`, one-sided p `0.014`, bootstrap 95% CI `[+0.0819, +0.4363]`, but Holm p `0.0716` and sign-test Holm p `0.859`.
- Underlying category proxy 5-day RV: date-level mean `-0.4021`, two-sided p `0.341`, placebo p `0.268`, Holm p `1.000`.
- Underlying category proxy 22-day RV: date-level mean `-0.1551`, two-sided p `0.578`, placebo p `0.554`, Holm p `1.000`.

Interpretation: converted ETF tracking noise tends to decline after the first post-listing month, but this is only raw directional evidence and does not clear the multiple-testing gate. The public proxy does not show robust evidence that conversion/listing dates create abnormal underlying category RV. The result should be treated as a bounded public-data diagnostic, not a causal statement about all mutual-fund-to-ETF conversions.

Limitations:

- The event calendar is hand-built from public issuer and industry sources, not a complete SEC N-14 universe.
- Converted ETF pre-listing exchange trading data does not exist, so wrapper liquidity is measured as post-listing maturation rather than true pre/post exchange liquidity.
- Underlying holdings are proxied by category ETFs; no fund-level holdings or CRSP mutual-fund holdings are used.
- Daily OHLCV data cannot measure bid-ask spreads, premium/discount, or primary-market creation/redemption mechanics directly.
