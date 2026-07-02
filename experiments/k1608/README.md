# K1608 - Blockbuster movie attention shocks and next-week market RV

## Question

Does a large U.S. movie-going attention shock leave a detectable next-week footprint in broad-market returns, realized volatility, or consumer-discretionary / entertainment-exposed assets?

This is a public-data proxy diagnostic. It is not a replication of Hong and Wei (2025), because it does not use their full Box Office Mojo release-level data, movie sentiment measures, or Google Trends panel.

## Literature checked before design

- Hong and Wei (2025), Review of Finance, "Blockbuster or Bust? Silver Screen Effect and Stock Returns": motivates blockbuster releases as scheduled entertainment mood shocks.
- Liu et al. (2024), Journal of Behavioral and Experimental Finance, "When Hollywood movies steal the show...": motivates a film-release investor-inattention channel.
- Da, Engelberg, and Gao (2011), Journal of Finance, "In Search of Attention": supports search volume as investor attention data, but this experiment does not rely on pytrends.
- Edmans, Garcia, and Norli (2007), Journal of Finance, "Sports Sentiment and Stock Returns": event-mood precedent.
- Hirshleifer and Shumway (2003), Journal of Finance, "Good Day Sunshine": classic mood-market precedent.

## Data

- Box office proxy: Wikipedia annual `List of YYYY box office number-one films in the United States` tables, 2005-2026.
- Market prices: yfinance daily adjusted close, downloaded by `yf.download(auto_adjust=True)`.
- Assets:
  - Broad: SPY, QQQ, IWM, XLY.
  - Entertainment: DIS, NFLX, AMC, plus equal-weight available-member basket from DIS/NFLX/AMC/CMCSA/EA/TTWO/RBLX.
  - Control: `^VIX`, lagged to the last available close before the weekend end date.

Final usable sample in `k1608_results.json`: 1,098 weekend observations from 2005-01-09 to 2026-06-21; 1,072 have trailing signal history; 96 are blockbuster shocks.

## Design

Shock definition:

```python
gross_z = (log(current_weekend_gross) - trailing_52_week_mean.shifted) / trailing_52_week_sd.shifted
blockbuster_shock = gross_z >= 1.5
```

Lookahead controls:

- The trailing distribution uses `.shift(1)` before scoring the current weekend.
- Outcomes are the next five trading days strictly after the weekend end date.
- Financial controls are lagged: SPY prior five-day return, SPY prior 20-day RV, and lagged VIX.
- Calendar controls include holiday/closure week, first-Friday NFP proxy week, mid-month CPI proxy week, FOMC-month Wednesday proxy week, and month fixed effects.

Outcomes:

- `fwd5_return`: next-five-trading-day log return.
- `log_fwd5_rv_ratio`: log of next-five-day annualized RV divided by prior-20-day annualized RV.
- `downside_semivar_5d_ann`: next-five-day annualized downside semivariance.

Inference:

- OLS with Newey-West / HAC lag 4 on weekly rows.
- Year-cluster bootstrap difference in means, 5,000 reps, seed 42.
- Primary gate: SPY shock coefficient must have the predicted sign and HAC `|t| >= 3`.

## Results

Verdict: `NULL`.

Primary SPY results:

- Next-week return: shock coefficient `-0.0020`, HAC `t=-0.90`, bootstrap CI crosses zero.
- Next-week RV ratio: shock coefficient `+0.0017`, HAC `t=0.03`, bootstrap CI crosses zero.

Secondary diagnostics:

- XLY return and RV do not clear any meaningful threshold.
- Entertainment basket return is directionally positive but weak (`t=0.54`); RV is also weak and positive (`t=0.70`).
- No tested asset/outcome supports a strong "blockbuster shock lowers volatility" claim in this public proxy panel.

## Interpretation

This experiment does not reject the published movie-mood literature. It says the free Wikipedia weekend-number-one gross proxy, mapped to yfinance daily returns with conservative lagging and controls, does not by itself produce a robust next-week SPY return or RV signal.

The result should be reported as a null public-proxy diagnostic, not as evidence that the true release-level blockbuster channel is false.

## Files

- `k1608.py`: reproducible script.
- `k1608_results.json`: full results and metadata.
- `data/box_office_weekends.csv`: parsed Wikipedia panel.
- `data/yfinance_close.csv`: downloaded close prices.
- `data/asset_event_panel.csv`: event-window analysis panel.
- `figures/fig1_box_office_shocks.png`: shock score timeline.
- `figures/fig2_shock_coefficients.png`: HAC shock coefficients.
- `figures/fig3_spy_raw_means.png`: SPY raw means by shock flag.

## Limitations

- Wikipedia weekend-number-one gross is not release-level Box Office Mojo microdata.
- The shock uses reported weekend gross, so it is a Monday-after-weekend proxy rather than a purely ex-ante release-calendar signal.
- Google Trends is not used because unofficial pytrends access is rate-limit fragile in this runtime.
- Entertainment stock basket is current-listed/surviving and availability-weighted, not a point-in-time industry portfolio.
- Macro controls are deterministic calendar proxies, not exact historical announcement timestamps.
- This is an event-window diagnostic, not an OOS trading strategy or causal claim.
