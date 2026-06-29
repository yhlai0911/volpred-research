# K1291: DEX Priority-Fee Pressure as a Crypto RV Covariate

Status: **scaffold only, not run**.

## Motivation

K1291 is a planned follow-up to the on-chain microstructure line. The question is
whether Ethereum DEX priority-fee pressure adds incremental information for
short-horizon BTC / ETH realized volatility after controlling for standard
price-only RV predictors.

The key distinction from K1566 is proxy quality. K1566 used Etherscan average
gas price plus DefiLlama DEX volume and concluded `WEAK_RAW_ONLY` / corrected
primary NULL. K1291 should only proceed if the data pipeline can obtain a better
priority-fee or mempool-pressure proxy, preferably one that separates priority
fees from base fees.

## Literature Context

- Barbon and Ranaldo, "On the Quality of Cryptocurrency Markets: Centralized vs.
  Decentralized Exchanges" -- DEX frictions and gas fees affect crypto market
  quality and arbitrage.
- Zhu, Liu, Wan, Liao, Moallemi, and Bachu, "What Drives Liquidity on
  Decentralized Exchanges? Evidence from the Uniswap Protocol" -- gas prices,
  returns, volume share, and volatility forecast DEX liquidity/depth metrics.
- Du et al., "Pricing Cryptocurrency Options With Volatility of Volatility" --
  related crypto vol-of-vol pricing literature, but orthogonal to this
  chain-side microstructure proxy.

## Planned Data

Primary market targets:

- `ETH-USD` and `BTC-USD` daily OHLCV from yfinance.
- Optional diagnostics: `COIN`, `IBIT`, `ETHA` as crypto-equity / spot-ETF
  spillover proxies, sample length permitting.

Candidate chain-side inputs:

- Ethereum priority-fee percentile or average priority fee, ideally direct from
  a reproducible public API or cached snapshot.
- Base fee and gas-used controls, so priority-fee pressure is not just the EIP-
  1559 base-fee trend.
- DEX volume share or Uniswap / aggregate DEX volume as secondary liquidity
  pressure proxy.

Do not proceed to formal results if the only available series is aggregate
average gas price. That would duplicate K1566's proxy limitation.

## Planned Method

1. Build daily close-to-close log returns for BTC and ETH.
2. Build daily realized variance targets:
   - `fwd_log_rv_1d`: squared return over `[t+1]`.
   - `fwd_log_rv_5d`: annualized sum of squared returns over `[t+1, t+5]`.
3. Build lagged baseline covariates:
   - `rv_1d_lag1`
   - `rv_5d_lag1`
   - `rv_22d_lag1`
   - `ret_1d_lag1`
   - optional `BTC` control for `ETH` and vice versa.
4. Build chain-side signals with rolling baselines ending at `t-1`, then apply
   explicit `signal.shift(1)`.
5. Compare baseline HAR-style regression against chain-augmented regression
   using Patton QLIKE / log-RV MSE diagnostics and DM-HLN tests where the loss
   series is well-defined.
6. Report HAC coefficient tests as diagnostic only; primary claim should be OOS
   forecast improvement versus a fair baseline.

## Lookahead Policy

Hard rule: `signal from t-1, return/RV at t`.

Implementation requirements:

- Every on-chain signal must be created from a rolling baseline that excludes
  the current target window.
- The tested signal column must be shifted with `.shift(1)`.
- Forward RV labels must use strictly future returns `[t+1, t+H]`.
- For expanding / rolling OOS model training, a training row is allowed only if
  its `target_end < forecast_origin`.

The scaffold script contains `apply_signal_lag()` with the explicit line:

```python
lagged[name] = signal.shift(1)
```

## Expected Outputs

When implemented and run, this experiment should produce:

- `k1291.py`
- `k1291_results.json`
- `README.md`
- `codex_review.md`
- optional figures:
  - `fig_priority_fee_pressure.png`
  - `fig_oos_loss_diff.png`
  - `fig_signal_tstats.png`

## Success Gate

K1291 should be considered SUPPORT only if all are true:

- data source is a genuine priority-fee / mempool-pressure proxy, not just
  average gas price;
- ETH or BTC chain-augmented model improves OOS QLIKE or log-RV loss versus a
  same-information HAR baseline;
- DM-HLN passes the project Harvey gate (`|t| > 3`) after horizon-correct
  inference;
- no overclaim from HAC raw significance alone.

Otherwise the correct outcome is NULL, WEAK_RAW_ONLY, or DATA_BLOCKED.
