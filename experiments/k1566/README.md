# K1566: DEX blockspace pressure as ETH/BTC short-RV signal

**Verdict**: `WEAK_RAW_ONLY` / corrected-primary NULL. BTC 1-day RV has weak raw-significant positive coefficients, but no ETH/BTC primary signal survives the 12-test family correction, and tail AUC is effectively 0.50.

## Motivation

Recent DEX microstructure papers argue that gas fees, DEX volume share, and blockchain frictions affect market quality and liquidity. This experiment asks a narrower volatility question: do public Ethereum blockspace-pressure proxies predict next-day or next-5-day realized volatility / left-tail risk in ETH and BTC?

## Differentiation

Existing VolPred crypto work covers BTC VaR, crypto volatility networks, crypto vol-of-vol spillover, and stablecoin/Treasury channels. This K is different: it uses Ethereum gas-price and DEX-volume shocks as on-chain microstructure proxies, not price-only crypto RV features.

## Data

- Etherscan chart CSV: Ethereum daily average gas price and daily gas used.
- DefiLlama free API: Ethereum DEX daily volume via `/overview/dexs/Ethereum`.
- yfinance adjusted close: `ETH-USD`, `BTC-USD`, plus diagnostic crypto equity/ETF proxies `COIN`, `IBIT`, `ETHA` when available.

Important limitation: Etherscan chart CSV is **average gas price**, not a base-fee / priority-fee decomposition. K1566 therefore tests a **blockspace-pressure proxy**, not true address-level mempool priority-fee pressure.

## Method

- Construct `gas_price_shock` and `dex_volume_shock` as daily log innovations standardized by a 90-day rolling mean/std ending at `t-1`.
- Construct `blockspace_pressure` as the mean of the gas-price and DEX-volume shocks.
- Apply explicit `signal.shift(1)` to every tested predictor.
- Targets:
  - `fwd_log_rv_1d`, `fwd_log_rv_5d`: annualized close-to-close realized variance over strictly `[t+1, t+H]`.
  - left-tail diagnostics: forward cumulative return ≤ -3% for 1d, ≤ -5% for 5d.
- Inference:
  - HAC OLS with `maxlags=H`.
  - Spearman block bootstrap CI with block `H`, `B=1000`, seed `42`.
  - Hanley-McNeil AUC CI for left-tail diagnostics.
  - Multiple-testing disclosure over the primary family: ETH/BTC × 2 horizons × 3 signals = 12 HAC p-values.

## Success Gate

K1566 is a PASS only if at least one ETH/BTC primary coefficient is positive and survives family-level multiple-testing correction, with supporting AUC evidence. Raw-significant or ETF-only results are diagnostic, not publishable proof.

## Results

Sample: 2019-01-01 to 2026-06-28, 2,736 calendar rows. Primary ETH/BTC HAC tests use about 2,638-2,642 valid rows after the 90-day shock warmup, explicit signal lag, and forward-target availability.

| Primary cell | HAC coef | HAC t | p | Spearman rho / CI | Tail AUC / CI | Interpretation |
|---|---:|---:|---:|---:|---:|---|
| BTC 1d `gas_price_shock` | +0.0999 | +2.24 | 0.025 | +0.033 [-0.005, +0.071] | 0.492 [0.457, 0.527] | raw-only |
| BTC 1d `dex_volume_shock` | +0.0945 | +1.98 | 0.048 | +0.032 [-0.006, +0.068] | 0.512 [0.477, 0.548] | raw-only |
| BTC 1d `blockspace_pressure` | +0.1298 | +2.43 | 0.015 | +0.037 [-0.001, +0.076] | 0.502 [0.466, 0.537] | strongest raw cell |
| BTC 5d `blockspace_pressure` | -0.0410 | -2.09 | 0.036 | -0.037 [-0.066, -0.007] | 0.501 [0.471, 0.530] | wrong sign for vol-pressure story |
| ETH 1d `blockspace_pressure` | -0.0193 | -0.36 | 0.720 | -0.012 [-0.050, +0.027] | 0.484 [0.454, 0.514] | null |
| ETH 5d `blockspace_pressure` | -0.0340 | -1.79 | 0.074 | -0.030 [-0.061, +0.000] | 0.489 [0.462, 0.515] | null / weak wrong sign |

Multiple-testing correction: primary family is ETH/BTC × 2 horizons × 3 signals = 12 HAC p-values. Bonferroni alpha is 0.00417; Holm-Bonferroni also rejects none. Therefore the raw BTC 1d effect is not enough to claim that public DEX blockspace pressure predicts crypto RV.

CEX / ETF spillover diagnostics do not rescue the story. For 1d `blockspace_pressure`, COIN t=-0.35 (n=1,021), IBIT t=+0.09 (n=477), and ETHA t=+0.15 (n=375).

Bottom line: the public gas-price + DEX-volume proxy may contain a tiny BTC next-day volatility association, but the sign is not stable across horizon, AUC is indistinguishable from random, and multiple testing removes the signal. Treat this as a useful null/weak diagnostic, not as a deployable or publishable forecasting edge.

## Literature Context

1. Barbon and Ranaldo (2026), *Management Science*, "On the Quality of Cryptocurrency Markets: Centralized vs. Decentralized Exchanges" — gas fees affect DEX market quality and arbitrage deviations.
2. Zhu, Liu, Wan, Liao, Moallemi, and Bachu (2024), "What Drives Liquidity on Decentralized Exchanges? Evidence from the Uniswap Protocol" — gas prices, returns, volume share, and volatility forecast DEX liquidity and depth metrics.
3. Etherscan and DefiLlama public documentation — free chart/API sources for gas-price and DEX-volume proxy construction.

## Outputs

- `k1566.py` — reproducible script.
- `k1566_results.json` — all statistics and source hashes.
- `k1566_analysis_dataset.csv` — merged signal/target panel.
- `fig1_blockspace_inputs.png`
- `fig2_pressure_vs_crypto_rv.png`
- `fig3_hac_tstat_heatmap.png`
- `codex_review.md` — source-level review, verdict `CONDITIONAL_PASS` for artifact integrity with claim-strength caveat.

## Lookahead Policy

- Signal innovations compare date `t` observations to baselines ending at `t-1`.
- Tested predictors use `signal.shift(1)`.
- Forward RV and return targets use only `[t+1, t+H]`.
- ETF/equity spillover rows are diagnostics only due short sample and market-calendar mismatch.
