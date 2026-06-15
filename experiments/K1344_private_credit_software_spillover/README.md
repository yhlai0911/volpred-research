# K1344 - Private-Credit Software Stress Spillover to IGV/HYG Volatility

## Motivation

The 2026 private-credit discussion has shifted from broad "shadow credit" risk to a narrower software/SaaS concentration concern. K1344 tests whether listed BDC stress proxies leave an incremental volatility footprint in public software equities (`IGV`) versus high-yield credit (`HYG`).

This is not a loan-tape test. It is a transparent public-market proxy test using yfinance data.

## Relationship to Prior K-Series

- `K1332`: listed BDC/private-credit proxies improved BKLN/HYG RV forecasts, but not broader KRE/IWM.
- `K1499`: BDC RV stress largely collapsed after SPY-vol controls; only a NAV-discount-like BIZD-HYG proxy survived for HYG 5d. This is the key caveat carried into K1344.

K1344 differs by making `IGV` the primary software-sector target and `HYG` the credit benchmark, with SPY/QQQ controls in every forecast.

## Literature / Source Motivation

- Financial Stability Board (2026-05-06), private credit vulnerabilities: concentration, valuation opacity, leverage, liquidity, and data gaps. URL: https://www.fsb.org/2026/05/fsb-warns-on-private-credit-vulnerabilities/
- Morgan Stanley, "The Risks of Private Credit's Software Exposure" (2026): software is heavily represented in opaque credit channels and BDC portfolios. URL: https://www.morganstanley.com/insights/podcasts/thoughts-on-the-market/private-credit-software-ai-disruption-vishy-tirupattur-vishwas-patkar
- J.P. Morgan Asset Management (2026), "Tech, Software, and BDCs": BDC portfolios have material software exposure. URL: https://am.jpmorgan.com/us/en/asset-management/institutional/insights/portfolio-insights/fixed-income/fixed-income-perspectives/tech-software-and-bdcs-navigating-volatility-and-ai-disruption-in-investment-grade-credit/
- MSCI Private Capital in Focus (2026): early-2026 BDC repricing described as targeted software-exposure repricing, not broad private-credit stress. URL: https://www.msci.com/downloads/web/msci-com/discover-msci/events/event-assets/2026/may/Presentation_%20Private%20Capital%20in%20Focus_USEurope_May132026.pdf

## Data

- Source: yfinance daily adjusted close, 2013-01-01 to 2026-06-12.
- BDC proxy basket: `BIZD`, `ARCC`, `BXSL`, `OBDC`, `FSK`; equal-weight daily log return over available members, requiring at least 2 members.
- Targets: `IGV`, `HYG`.
- Controls: `SPY`, `QQQ`.
- OOS start: 2021-01-04, hard-coded.

## Method

For each target (`IGV`, `HYG`) and horizon (`5`, `21` trading days), compare:

- Baseline: own HAR-style lagged RV controls (`5/21/63d`) + lagged SPY/QQQ 21d RV.
- Augmented: baseline + lagged BDC RV z-score, BDC pressure, BDC 21d return, and BIZD-HYG 21d gap proxy.

Lookahead controls:

- Every predictive feature enters as explicit `.shift(1)`.
- Forward variance at row `t` uses returns `t..t+H-1`; features use information through `t-1`.
- Expanding OLS training uses only rows with `target_end_pos < forecast_pos`, avoiding the K1337 forward-label overlap leak.

Primary statistic:

- OOS QLIKE loss difference = baseline - augmented. Positive means BDC augmentation helps.
- DM/HAC test uses Newey-West maxlags `H+5`.
- Moving-block bootstrap: block size 21, reps 1000, seed 42.
- Multiple testing: 2 targets x 2 horizons = 4 tests, Bonferroni alpha = 0.0125.

## Results

Verdict: `NULL`.

Primary OOS forecast cells:

| Target | Horizon | OOS n | QLIKE improvement | DM t | p-value | Bonferroni pass |
|---|---:|---:|---:|---:|---:|---|
| IGV | 5 | 1367 | +1.91% | 0.47 | 0.635 | no |
| IGV | 21 | 1367 | +7.19% | 1.35 | 0.178 | no |
| HYG | 5 | 1367 | +2.98% | 0.74 | 0.462 | no |
| HYG | 21 | 1367 | +5.44% | 0.86 | 0.388 | no |

Event-study diagnostic:

- 13 OOS BDC-stress events after 21d cooldown.
- IGV 21d future variance is higher on stress events than non-events, bootstrap p_gt_0 = 0.005.
- This is descriptive only: sparse events, overlapping macro regimes, and the primary expanding forecast test does not validate a robust tradable/predictive edge.

## Interpretation

Listed BDC stress has a positive directional association with later IGV/HYG volatility, especially at 21d horizons, but the incremental OOS forecasting value is not statistically reliable after market/tech controls and multiple-testing discipline.

Conclusion strength: public BDC proxies do not currently support a publishable claim that software-heavy private-credit stress predicts public software-sector volatility. The result is consistent with K1499's caveat that BDC stress is partly broad beta/credit stress rather than clean private-credit transmission.

## Caveats

- Public BDC prices are noisy proxies, not loan-level private-credit exposure or NAV marks.
- BDC basket composition is dynamic because `BXSL` and `OBDC` histories start later.
- Survivorship and ticker-selection bias remain possible.
- `IGV` is public software equity, not private SaaS borrower collateral.
- Event-study positives should not be promoted without a stronger independent event design or loan-level software-exposure data.

## Artifacts

- `K1344.py`
- `K1344_results.json`
- `fig_qlike_improvement.png`
- `fig_cumulative_lossdiff.png`
