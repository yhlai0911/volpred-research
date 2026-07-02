# GLP-1 Adoption Shock and Sector Volatility

## Question

Do major GLP-1 adoption and repricing events create a tradable cross-sector volatility factor across healthcare, food and beverage, restaurants, and diabetes-device names?

Backlog item:

> GLP-1 adoption shock as a cross-sector consumption / healthcare repricing volatility factor.

## Data

- Event dates: 6 public GLP-1 adoption or repricing events from 2021-06-04 to 2024-08-20.
- Prices: yfinance daily adjusted close, downloaded with `auto_adjust=False` and the explicit `Adj Close` field.
- Sample start for prices: 2020-01-01.
- Target groups:
  - GLP-1 makers: `LLY`, `NVO`
  - Broad healthcare: `XLV`, `IYH`, `IHE`, `PPH`
  - Diabetes medtech: `DXCM`, `PODD`, `TNDM`, `ABT`, `MDT`
  - Food and beverage: `XLP`, `PBJ`, `PEP`, `KO`, `MDLZ`, `HSY`, `GIS`, `KHC`, `CPB`, `CAG`, `KDP`, `MNST`
  - Restaurants: `MCD`, `SBUX`, `YUM`, `DPZ`, `CMG`, `DRI`, `CAKE`, `WING`
- Market controls: equal-weight `SPY`, `QQQ`, and `IWM`.

The final panel has 372 ticker-event rows, 60 group-event rows, and 15,575 same-year placebo anchor group rows.

## Method

1. Map each event date to the first available trading date on or after the announcement date.
2. Compute baseline realized variance from daily squared log returns over `T-60..T-11`.
3. Record pre-event RV over `T-10..T-1` and same-day squared return as diagnostics.
4. Use only `T+1..T+5` and `T+1..T+22` as primary post-event windows.
5. For each ticker-event-window, compute `log(post RV / baseline RV)`.
6. For each event-window-group, average ticker ratios within group and subtract the same-window equal-weight market-control ratio.
7. Treat event-level group means as the unit of inference, not pooled ticker-event rows.
8. Report one-sided t-tests for positive adjusted RV, sign tests, event bootstrap confidence intervals, same-year non-event placebo p-values, and Holm-adjusted p-values across group x horizon cells.

Lookahead control: same-day announcement returns are not used in primary tests; the primary windows begin at `T+1`. This is an event-study diagnostic rather than a trading backtest.

Random procedures use seed `42`.

## Files

- `research_glp_1_adoption_shock_sector_consumption_healthca.py`: reproducible script.
- `research_glp_1_adoption_shock_sector_consumption_healthca_results.json`: machine-readable results.
- `data/raw/yfinance_adj_close_*.csv`: raw adjusted-close caches.
- `data/ticker_event_metrics.csv`: ticker-event-window metrics.
- `data/group_event_metrics.csv`: event-level group metrics.
- `data/anchor_group_metrics.csv`: matched same-year placebo anchor metrics.
- `data/group_summary.csv`: statistical summary table.
- `figures/group_adjusted_rv_ratio.png`: group-level adjusted RV ratio with bootstrap intervals.
- `figures/event_group_heatmap_5d.png`: event by group heatmap for the 5-day window.

## References

- Wilding et al. (2021), "Once-Weekly Semaglutide in Adults with Overweight or Obesity", NEJM, DOI: https://doi.org/10.1056/NEJMoa2032183
- Jastreboff et al. (2022), "Tirzepatide Once Weekly for the Treatment of Obesity", NEJM, DOI: https://doi.org/10.1056/NEJMoa2206038
- Lincoff et al. (2023), "Semaglutide and Cardiovascular Outcomes in Obesity without Diabetes", NEJM, DOI: https://doi.org/10.1056/NEJMoa2307563
- FDA (2023), "FDA Approves New Medication for Chronic Weight Management": https://www.fda.gov/news-events/press-announcements/fda-approves-new-medication-chronic-weight-management
- Novo Nordisk (2023), SELECT headline results press release: https://www.novonordisk.com/news-and-media/news-and-ir-materials/news-details.html?id=166301

## Current Result

Run:

```bash
uv run python experiments/research_glp_1_adoption_shock_sector_consumption_healthca/research_glp_1_adoption_shock_sector_consumption_healthca.py
```

Verdict: `null_or_inconclusive`.

Key diagnostics:

- Events: 6, from 2021-06-04 to 2024-08-20.
- Ticker-event rows: 372.
- Group-event rows: 60.
- Placebo anchor group rows: 15,575.
- GLP-1 makers, 5-day adjusted log-RV ratio: mean `+0.0137`, t `0.019`, one-sided p `0.493`, bootstrap 95% CI `[-1.318, +1.338]`, placebo p `0.320`, Holm p `1.000`.
- GLP-1 makers, 22-day adjusted log-RV ratio: mean `+0.0793`, t `0.378`, one-sided p `0.360`, bootstrap 95% CI `[-0.235, +0.501]`, placebo p `0.353`, Holm p `1.000`.
- Food and beverage, 5-day adjusted log-RV ratio: mean `-0.3992`, one-sided p `0.786`, placebo p `0.919`, Holm p `1.000`.
- Restaurants, 5-day adjusted log-RV ratio: mean `-0.1223`, one-sided p `0.615`, placebo p `0.589`, Holm p `1.000`.
- Diabetes medtech, 22-day adjusted log-RV ratio: mean `+0.0410`, one-sided p `0.436`, placebo p `0.242`, Holm p `1.000`.

Interpretation: this public-event pilot does not support a robust GLP-1 adoption-shock volatility factor across the tested sector baskets. Some cells are directionally positive, especially GLP-1 makers and 22-day diabetes medtech, but the event count is small, confidence intervals cross zero, and no t-test, sign test, or same-year placebo comparison survives Holm correction. The result should be treated as a bounded public-equity event-study null, not evidence that GLP-1 adoption has no real consumption or healthcare impact.

Main limitations:

- Only six major public events are used.
- Event timing may be partly anticipated by markets.
- Daily close-to-close data can miss intraday repricing.
- The experiment uses public equity proxies, not prescription, claims, grocery receipt, or patient-level adoption data.
