# K1514 — Liberation Day 2025 Cross-Asset Correlation Event Study

## Motivation

The 2025-04-02 U.S. reciprocal tariff announcement was a large policy shock.
The research question is whether the shock visibly changed cross-asset
diversification relationships for a simple ETF universe:

- Stocks: SPY
- Bonds: TLT
- Gold: GLD
- Commodities: PDBC
- Bitcoin: BTC-USD
- Volatility proxy: ^VIX

This differs from prior cross-asset hedge experiments such as K923/K377/K983
because it is an event-study of correlation structure, not a hedge-ratio or
forecasting model.

## Literature / Context

- White House Executive Order 14257 documents the 2025-04-02 reciprocal tariff
  action and its policy rationale:
  https://www.whitehouse.gov/presidential-actions/2025/04/regulating-imports-with-a-reciprocal-tariff-to-rectify-trade-practices-that-contribute-to-large-and-persistent-annual-united-states-goods-trade-deficits/
- Garimella, Kwan, and Mertens (FRBSF Economic Letter 2025-23) use event-study
  evidence and report broad repricing across U.S. stocks, Treasury yields, and
  exchange rates after the April 2 announcement:
  https://www.frbsf.org/research-and-insights/publications/economic-letter/2025/10/market-reactions-to-tariff-announcements/
- Hartley and Rebucci (VoxEU/CEPR, 2025-04-15) document high-frequency evidence
  that the dollar depreciated on impact, consistent with portfolio reallocation
  away from U.S. equities:
  https://cepr.org/voxeu/columns/tariffs-dollar-and-equities-high-frequency-evidence-liberation-day-announcement
- Tang (SSRN, 2025) explicitly studies how major events, including Liberation Day,
  alternate cross-asset correlations across 30-day and 7-day windows:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5960345

## Method

### Data

- Source: yfinance adjusted close, explicitly `auto_adjust=True`
- Period: 2019-01-01 to 2025-07-31
- Return: daily close-to-close percentage return
- Assets: SPY, TLT, GLD, PDBC, BTC-USD, ^VIX

### Event Timing

- Event date: 2025-04-02.
- Because the script uses close-to-close daily returns, post-event windows start
  on the first trading day strictly after 2025-04-02.
- Pre-event windows end on or before 2025-04-02.
- This is an ex-post event study, not a trading signal; no same-day signal is
  multiplied by same-day returns.

### Tests

For each 30/60/90-trading-day window, the script computes:

- Pearson correlation pre vs post for each pair.
- Fisher z test for pre/post correlation difference.
- Stationary block bootstrap CI for post-minus-pre correlation shift.
- Calendar-placebo DiD: 2025 event delta minus the mean same-date delta for
  2021-2024.

Primary pairs:

- SPY-TLT (`stock_bond`)
- SPY-GLD (`stock_gold`)
- SPY-BTC (`stock_btc`)
- SPY-VIX (`stock_vol`)

Secondary pairs:

- SPY-PDBC (`stock_commodity`)
- TLT-GLD (`bond_gold`)

## Success Criteria

- **PASS**: at least 3 primary pair shifts are significant by Fisher z and
  bootstrap CI in at least 2 of 3 windows.
- **CONDITIONAL_PASS**: 1-2 primary pair shifts satisfy that standard.
- **NULL**: no primary pair shift satisfies that standard.

The conclusion must be phrased as event-study evidence only. It cannot be used
as a live predictive trading rule.

## Result

Verdict: **NULL**.

No primary cross-asset correlation shift passed the rule of being Fisher-z
significant and bootstrap-confirmed in at least 2 of 3 windows.

Key event-window observations:

- SPY-TLT (`stock_bond`) correlation rose visibly in the short window
  (`30d`: -0.205 to +0.208, delta +0.413), but Fisher p=0.123 and the
  bootstrap CI includes zero.
- SPY-PDBC (`stock_commodity`) rose in all windows (average delta +0.270), with
  borderline Fisher p-values around 0.054/0.053 in 30d/90d, but bootstrap CIs
  include zero and it is a secondary pair.
- SPY-GLD (`stock_gold`) average delta was -0.064; the 90d placebo-DiD p-value
  was borderline (0.060), not enough for a robust claim.
- SPY-BTC (`stock_btc`) was essentially unchanged (average delta +0.009).
- SPY-VIX (`stock_vol`) became slightly more negative on average (-0.029); the
  90d Fisher p=0.049, but the bootstrap CI crosses zero.

Interpretation: Liberation Day produced economically visible short-window
correlation movements, especially stock-bond and stock-commodity, but this
implementation does **not** support a statistically robust claim that
diversification regimes structurally broke across the ETF universe.

## Files

- `k1514.py` — reproducible script
- `k1514_results.json` — metrics, tests, placebo DiD, review
- `k1514_fig.png` — heatmap and rolling-correlation chart
- `prices.csv` — cached yfinance adjusted-close data
