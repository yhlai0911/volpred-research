# K1610 - Frontier markets correlation convergence and diversification value

## Question

Do frontier-market ETF proxies still diversify emerging-market exposure, or have their correlations converged enough to erode the benefit?

Task brief:

- `K1610`: Frontier markets (`FM` ETF) and EM crisis-correlation convergence.
- Public source: yfinance `FM` plus `EEM` / `VWO` / `VNM` and country ETF diagnostics.

## Motivation and prior evidence

The experiment starts from two competing priors.

First, the frontier-market literature argues that frontier equities historically had low world-market integration and could add diversification. Second, VolPred memory already shows that broad EM exposure can be highly equity-like: knowledge item `09402d93` records `SPY-EEM=0.757` over 2020-2025 and says EEM is too homogeneous with SPY for risk parity. Knowledge item `1e58a27f` records that diversification weakens during volatility spikes.

K1610 asks whether a frontier ETF proxy escapes that EM homogeneity, or whether stress-period comovement erodes the benefit.

## Literature checked before design

- Berger, Pukthuanthong, and Yang (2011), Journal of Financial Economics, "International diversification with frontier markets": frontier markets historically had low world-market integration and diversification value.
- Bekaert and Harvey (2017), "Emerging equity markets in a globalizing world": motivates time-varying EM integration and declining diversification benefits as markets globalize.
- Converse, Levy-Yeyati, and Williams (2020), Federal Reserve IFDP 1268, "How ETFs Amplify the Global Financial Cycle in Emerging Markets": motivates ETF-flow/global-financial-cycle comovement.
- Baur (2012), "Financial contagion and the real economy": motivates separating ordinary interdependence from crisis-period correlation diagnostics.

## Data

Source: yfinance adjusted close via `yf.download(auto_adjust=True)`.

Primary tickers:

- Frontier proxy: `FM`
- EM benchmarks: `EEM`, `VWO`
- Global risk benchmark: `SPY`
- Frontier / component diagnostic: `VNM`

Country diagnostics:

- `KSA`, `UAE`, `QAT`, `ARGT`, `GREK`, `EGPT`, `PAK`, `NGE`

Important data limitation:

- `FM` has 3,100 adjusted-close observations from 2012-09-12 to 2025-01-08 in this runtime.
- Therefore the primary common sample is 3,099 daily returns from 2012-09-13 to 2025-01-08.
- There is no current 2025-2026 `FM` inference. The results are explicitly about the available investable ETF sample, not a live frontier-market index.

## Method

The main inference avoids treating overlapping rolling windows as independent evidence.

- Quarterly daily-return correlations: non-overlapping calendar-quarter correlations for `FM vs EEM`, `FM vs VWO`, `FM vs SPY`, and `VNM vs EEM`.
- Secular convergence test: OLS trend on quarterly Fisher-z correlations with HAC maxlags 4.
- Early/late comparison: first 24 quarters vs last 25 quarters; bootstrap difference in mean Fisher-z correlation, 3,000 reps, seed 42.
- Stress/calm comparison: stress quarters are the bottom quintile of `SPY` quarterly returns within the usable sample. This is a descriptive stress-conditioning test, not a tradable signal.
- Diversification test: compare `EEM` to monthly-rebalanced `80% EEM / 20% FM` and `50% EEM / 50% FM`. Bootstrap uses 21-day moving blocks, 3,000 reps, seed 42.

Lookahead policy:

- This is a descriptive correlation / portfolio experiment, not a trading signal.
- Portfolio weights are constant and monthly rebalanced.
- Stress classification is descriptive within-sample conditioning. It is not used to form a signal.
- Rolling 252-day correlations are diagnostic only and are not the source of formal inference.

## Results

Verdict: `MIXED_DIVERSIFICATION_RETAINS_WITH_STRESS_EROSION`.

Main result:

- Full-sample `80% EEM / 20% FM` lowers annualized volatility by `0.0204` versus `EEM` alone.
- 21-day block-bootstrap 95% CI for that annualized vol reduction: `[0.0183, 0.0225]`.
- Bootstrap p-value is below simulation resolution (`p <= 0.0007`, 3,000 reps).
- Sharpe proxy improves by `+0.0396`, but CI crosses zero: `[-0.0372, 0.1266]`.

Correlation convergence:

- `FM vs EEM` quarterly Fisher-z trend is not significant: HAC `t=0.23`, `p=0.819`.
- Early mean correlation: `0.514`.
- Late mean correlation: `0.569`.
- Late-minus-early Fisher-z bootstrap CI: `[-0.0598, 0.2133]`.
- Interpretation: point estimate is higher late in the sample, but secular convergence is not statistically supported.

Stress erosion:

- Stress-quarter `FM vs EEM` mean correlation: `0.675`.
- Calm-quarter `FM vs EEM` mean correlation: `0.504`.
- Stress-minus-calm Fisher-z difference: `0.265`.
- Bootstrap 95% CI: `[0.0758, 0.4454]`, `p=0.008`.
- Interpretation: diversification is materially weaker in broad equity stress quarters.

Country diagnostics:

- `QAT` has the lowest correlation among diagnostics (`corr_with_eem=0.384`, `corr_with_spy=0.358`), but it is a narrow country ETF and cannot replace a broad frontier index.
- `ARGT`, `GREK`, and `VNM` are much more equity-like (`corr_with_eem` around `0.53` to `0.61`).

## Interpretation

The evidence does not support the strong claim that frontier-market diversification has fully disappeared. In the available `FM` ETF sample, adding `FM` still robustly lowers EM portfolio volatility.

But the benefit is conditional: during the worst `SPY` quarters, `FM` comoves much more with `EEM` and `SPY`. The honest conclusion is "diversification retains support in normal/full-sample volatility, but stress-period erosion is real."

## Files

- `K1610.py`: reproducible script.
- `K1610_results.json`: full results and metadata.
- `data/yfinance_adjusted_close.csv`: adjusted close panel.
- `data/daily_log_returns.csv`: daily log-return panel.
- `data/primary_common_daily_returns.csv`: primary common sample.
- `data/quarterly_pair_correlations.csv`: non-overlapping quarterly correlation panel.
- `data/portfolio_daily_returns.csv`: portfolio-return panel.
- `data/proxy_country_diagnostics.csv`: country proxy diagnostics.
- `figures/fig1_quarterly_correlations.png`: quarterly correlation diagnostics.
- `figures/fig2_early_late_corr.png`: early vs late correlation comparison.
- `figures/fig3_portfolio_diversification.png`: diversification portfolio stats.

## Limitations

- `FM` no longer has current yfinance observations after 2025-01-08 in this runtime.
- Country ETF proxies mix frontier, emerging, and recently reclassified markets.
- ETF data include liquidity, closure, fees, and replication frictions.
- Stress/calm comparison is within-sample descriptive conditioning.
- Quarterly correlations reduce overlap but leave only 49 quarters; power is modest.
- The experiment does not measure local-market investability or capital-control frictions directly.
