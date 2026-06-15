# K1343 - BDC Pressure as a Private-Credit Shadow Volatility Signal

## Motivation

Private credit risk became a 2026 market theme, with listed BDCs often used as the only liquid public proxy for otherwise opaque direct-lending stress. K1343 tests whether BDC price pressure leads future volatility in public credit, regional banks, and small caps:

- `HYG`: high-yield credit
- `KRE`: regional banks
- `IWM`: small caps

This is a public-proxy experiment, not a claim about loan-level private-credit marks.

## Relationship to Prior K-Series

- `K1332`: BDC/private-credit proxies improved BKLN/HYG RV forecasts, but not KRE/IWM.
- `K1499`: broad BDC RV stress mostly collapsed after SPY-vol controls; only a BIZD-HYG NAV-discount-like proxy survived for HYG 5d.
- `K1344`: software-specific extension found directional but non-significant IGV/HYG forecast improvements.

K1343 is stricter than a raw event study because every target forecast includes own-HAR, SPY RV, and VIX controls.

## Literature / Source Motivation

- Financial Stability Board (2026-05-06), private credit vulnerabilities: transparency, valuation, leverage, and liquidity risk. URL: https://www.fsb.org/2026/05/fsb-warns-on-private-credit-vulnerabilities/
- J.P. Morgan Private Bank (2026), "Private Credit Under the Microscope": publicly traded BDCs sold off with wide dispersion. URL: https://privatebank.jpmorgan.com/nam/en/insights/markets-and-investing/private-credit-under-the-microscope-separating-headlines-from-fundamentals
- European Parliament briefing (2026), private-credit market structure and risks, including rising default-rate discussion. URL: https://www.europarl.europa.eu/RegData/etudes/BRIE/2026/784039/ECTI_BRI%282026%29784039_EN.pdf
- Boston Fed (2025), private credit and financial-stability risk through BDC stress-test framing. URL: https://www.bostonfed.org/publications/current-policy-perspectives/2025/could-the-growth-of-private-credit-pose-a-risk-to-financial-system-stability.aspx

## Data

- Source: yfinance daily adjusted close.
- Sample request: 2013-01-01 to 2026-06-15; actual last date 2026-06-12.
- BDC proxy basket: `BIZD`, `ARCC`, `BXSL`, `OBDC`, `FSK`.
- Basket rule: equal-weight daily log return over available BDC proxy tickers, requiring at least 2 members.
- Targets: `HYG`, `KRE`, `IWM`.
- Controls: `SPY`, `^VIX`.
- OOS start: 2021-01-04.

## Method

For each target and horizon (`5`, `10`, `21` trading days), compare:

- Baseline: own HAR-style lagged RV (`5/21/63d`) + lagged SPY RV (`21/63d`) + lagged VIX level/change.
- Augmented: baseline + lagged BDC RV z-score, BDC pressure, BDC 21d return, and BIZD-HYG gap proxy.

Lookahead controls:

- Every predictive feature enters as explicit `.shift(1)`.
- Forward variance at row `t` uses returns `t..t+H-1`; features use information through `t-1`.
- Expanding OLS training uses only rows with `target_end_pos < forecast_pos`, avoiding forward-label overlap.

Statistical discipline:

- Primary family: 3 targets x 3 horizons = 9 tests.
- Bonferroni alpha = 0.05 / 9 = 0.00556.
- OOS loss: QLIKE.
- DM/HAC test: Newey-West maxlags `H+5`.
- Moving-block bootstrap: block size 21, reps 1000, seed 42.

## Results

Verdict: `NULL`.

The augmented BDC model worsened OOS QLIKE in all 9 primary cells.

| Target | Horizon | OOS n | QLIKE improvement | DM t | p-value | Bonferroni pass |
|---|---:|---:|---:|---:|---:|---|
| HYG | 5 | 1354 | -2.79% | -0.92 | 0.360 | no |
| HYG | 10 | 1354 | -2.03% | -0.53 | 0.598 | no |
| HYG | 21 | 1354 | -0.76% | -0.14 | 0.888 | no |
| KRE | 5 | 1354 | -2.25% | -1.13 | 0.258 | no |
| KRE | 10 | 1354 | -4.00% | -1.39 | 0.164 | no |
| KRE | 21 | 1354 | -3.39% | -1.82 | 0.069 | no |
| IWM | 5 | 1354 | -0.46% | -0.25 | 0.799 | no |
| IWM | 10 | 1354 | -0.74% | -0.31 | 0.753 | no |
| IWM | 21 | 1354 | -2.11% | -0.80 | 0.426 | no |

Event-study diagnostic:

- 13 OOS BDC-pressure events after a 21d cooldown.
- HYG and IWM 21d future variance are higher after stress events in the descriptive bootstrap (`p_gt_0` about 0.032 and 0.020).
- KRE shows no event lift.
- This event result is descriptive only; it does not overturn the primary forecast result because the controlled expanding model worsens all targets.

## Interpretation

Listed BDC stress is visible around high-volatility regimes, but it does not add reliable incremental forecasting power once own volatility, SPY volatility, and VIX controls are included. The clean conclusion is that BDC price pressure should not be promoted as a standalone private-credit early-warning vol signal for HYG/KRE/IWM using free daily public data.

This is consistent with the K1499 caution: BDC stress is partly broad beta and public-credit sentiment, not a clean private-credit transmission channel.

## Caveats

- Listed BDC prices are liquid public proxies, not private loan marks or non-traded BDC redemption flow.
- BDC basket composition is dynamic because `BXSL` and `OBDC` histories start later.
- Survivorship and ticker-selection bias remain possible.
- SPY/VIX controls reduce but do not eliminate common-beta confounding.
- Event-study positives need a stronger independent event definition before publication.

## Artifacts

- `K1343.py`
- `K1343_results.json`
- `fig_qlike_improvement.png`
- `fig_cumulative_lossdiff.png`
