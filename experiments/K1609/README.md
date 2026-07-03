# K1609 - COMEX warehouse scarcity proxy and precious-metal volatility

## Question

Can public COMEX warehouse scarcity information predict precious-metal realized volatility, downside semivariance, or the gold/silver relationship with real yields?

The intended design was to use CME daily COMEX registered/eligible gold and silver warehouse stock reports, then map inventory depletion to GLD/SLV/GC/SI realized volatility. In this runtime, the CME XLS endpoints did not return bytes, so the binding result is a data limitation. A fallback yfinance/FRED proxy diagnostic is included, but it is not COMEX inventory evidence.

## Literature checked before design

- Barone-Adesi, Geman, and Theal (2010), "On the Lease Rate, Convenience Yield and Speculative Effects in the Gold Futures Market": motivates inventory and lease-rate tightness as gold-futures state variables.
- Le and Zhu (2013), "Risk Premia in Gold Lease Rates": links gold lease-rate behavior to Treasury yields, VIX, and COMEX inventory growth.
- Fama and French (1987), Journal of Business, "Commodity Futures Prices": storage theory motivation for inventory scarcity and convenience yield.
- CME Group warehouse and depository stock reports: intended public source for registered and eligible metal stocks.

## Data

Primary intended source:

- CME `Gold_Stocks.xls`: `https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls`
- CME `Silver_stocks.xls`: `https://www.cmegroup.com/delivery_reports/Silver_stocks.xls`

Observed in this runtime:

- Gold endpoint: `ReadTimeout`, 0 bytes.
- Silver endpoint: `ReadTimeout`, 0 bytes.

Fallback sources:

- yfinance adjusted OHLCV: GLD, SLV, GC=F, SI=F, `^VIX`.
- FRED DFII10: 10-year TIPS real yield from `fredgraph.csv`.

Sample in the fallback panel:

- 2,061 weekly Friday origins.
- Gold: 1,038 origins.
- Silver: 1,023 origins.
- Date range: 2006-01-06 to 2026-05-29.

## Fallback proxy

The fallback proxy is intentionally weak and is labelled as such:

```python
tracking_basis = log(futures_price / scaled_etf_price)
basis_z = rolling_zscore(tracking_basis, 252)
dollar_volume_z = rolling_zscore(log1p(etf_close * etf_volume), 252)
scarcity_proxy_raw = basis_z + 0.5 * dollar_volume_z
scarcity_proxy_lag1 = scarcity_proxy_raw.shift(1)
```

This is not registered inventory, eligible inventory, lease rate, or physical scarcity. It is only a public-market tightness proxy combining futures/ETF basis and ETF dollar-volume attention.

## Lookahead policy

- Signals use `.shift(1)`.
- Weekly origins use data available at Friday close.
- Targets are strictly the next five trading days for RV/downside semivariance, and the next 21 trading days for return-real-yield correlation.
- FRED real-yield controls are lagged.

## Inference

- OLS with HAC/Newey-West lag 4.
- Year-cluster bootstrap high-proxy-minus-low-proxy difference, 5,000 reps, seed 42.
- Strict signal gate: fallback cell needs `|t| >= 3`. Even if it passed, it would be labelled proxy-only unless CME inventory data were actually available.

## Results

Verdict: `DATA_LIMITATION_PROXY_NULL`.

Primary limitation:

- CME warehouse stock endpoints did not return data in this runtime; no COMEX registered/eligible inventory time-series inference is possible.

Fallback RV results:

- Gold next-week log RV ratio: coefficient `0.0165`, HAC `t=1.40`, bootstrap CI crosses zero.
- Silver next-week log RV ratio: coefficient `0.0147`, HAC `t=1.10`, bootstrap CI crosses zero.

Fallback real-yield correlation result:

- Gold future 21-day return-real-yield correlation: coefficient `-0.0157`, HAC `t=-2.05`, but the year-bootstrap CI crosses zero.
- Silver equivalent: `t=-1.63`, bootstrap CI crosses zero.

Interpretation:

The fallback proxy does not provide strict evidence that public-market tightness predicts next-week precious-metal RV. The experiment should not be used to make any claim about actual COMEX registered/eligible warehouse stocks.

## Files

- `K1609.py`: reproducible script.
- `K1609_results.json`: full metadata, CME fetch attempts, fallback tests.
- `data/yfinance_close.csv`, `data/yfinance_volume.csv`: yfinance inputs.
- `data/fred_dfii10.csv`: FRED real-yield input.
- `data/daily_proxy_panel.csv`: lagged proxy panel.
- `data/weekly_origin_panel.csv`: weekly test panel.
- `figures/fig1_fallback_proxy_timeseries.png`: lagged fallback proxy.
- `figures/fig2_proxy_coefficients.png`: HAC coefficients.
- `figures/fig3_proxy_vs_rv_scatter.png`: proxy/RV diagnostic scatter.

## Limitations

- No COMEX warehouse time series was obtained; this is decisive.
- CME access might work from another network or with a cached historical vendor, but it did not work here.
- The fallback proxy is a market-price/volume proxy, not physical inventory.
- GLD and SLV have ETF mechanics, fees, tracking error, and share-creation/redemption behavior that are not observed directly here.
- Weekly origins reduce target overlap but do not create causal identification.
