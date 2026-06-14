# K1327: Adaptive Multi-Factor HAR Public-Proxy Stress Test

## Motivation

This task was generated from the research backlog item:

> Adaptive Multi-Factor HAR -- FoFI 2026, Cinquetti et al. (287 high-frequency factors)

The exact paper design uses a large high-frequency factor-volatility panel. This repository does not currently pin that 287-factor intraday dataset, so this experiment is an honest public-data proxy:

- keep the core idea: a large factor bank feeding a HAR-style volatility forecast
- keep strict no-lookahead timing
- use local daily snapshots and local sentiment/risk proxies only
- fix the old K986 weakness by forecasting log variance, so all forecasts are positive before QLIKE evaluation

## Literature pre-check

Before implementation, I checked:

- Cinquetti, Hong, Nolte & Nolte, *Volatility Forecasting Factors* (SSRN / FoFI 2026). The paper motivates factor-specific volatility components and adaptive selection.
- Corsi (2009), *A Simple Approximate Long-Memory Model of Realized Volatility*. Baseline HAR structure.
- Patton (2011), volatility forecast comparison with imperfect proxies. QLIKE remains the primary loss.

## Relation to prior repo work

K986 already tested a smaller daily-factor version of this idea. It found:

- multi-factor HAR improved MSE / OOS R2
- but linear daily-scale predictions damaged QLIKE
- rolling LASSO did not beat static LASSO
- all 10 factors were selected, so the static LASSO was not sparse

K1327 differs by:

- modeling `log(rv_t)` instead of variance level
- expanding the public factor bank to cross-asset OHLC volatility proxies
- comparing adaptive rolling regularization to a fixed HAR-3 log baseline
- reporting factor-family selection frequencies

## Data

Local files only:

- `experiments/k1206/data/{SPY,QQQ,GLD,TLT,IWM,EEM,BTC_USD}.csv`
- `storage/sentiment/vix_historical.csv`
- `storage/sentiment/vvix_historical.csv`
- `storage/sentiment/skew_index.csv`
- `storage/sentiment/credit_spread_proxy.csv`

Target:

- SPY daily squared log return, `rv_t = r_t^2`
- Forecast target in model space: `log(rv_t)`
- Evaluation target: positive variance forecast `exp(pred_log)` against `rv_t`

## Factor bank

For each ETF/asset proxy, build shifted rolling features from:

- squared return
- absolute return
- Parkinson range variance
- Garman-Klass range variance
- Rogers-Satchell range variance

For each raw series, include shifted rolling means over:

- 1 day
- 5 days
- 22 days
- 66 days

Also include shifted VIX / VVIX / SKEW / credit-spread proxy level features.

Every feature is based on information through `t-1`; target is `t`.

## Models

- `HAR3`: fixed SPY log-HAR with 1/5/22 day SPY RV features
- `MF_Ridge_static`: full factor bank, alpha selected on pre-OOS validation
- `MF_ElasticNet_static`: full factor bank, alpha/l1 selected on pre-OOS validation
- `MF_Ridge_rolling`: rolling 1000-day adaptive refit every 63 trading days
- `MF_ElasticNet_rolling`: rolling 1000-day adaptive refit every 63 trading days

## Evaluation

- OOS starts at `2021-01-04`
- Primary metric: Patton-style QLIKE on variance
- Pairwise DM-HLN via `volpred.stats.model_evaluation.dm_test`
- Strong win requires lower QLIKE and Harvey `|t| > 3`

## Success Criteria

- Complete experiment three-piece:
  - `README.md`
  - `k1327.py`
  - `k1327_results.json`
- Explicit lookahead-safe feature construction
- Report null results honestly
- Make clear that this is a daily public proxy, not the original 287 high-frequency factor dataset

## Results

Final run:

- Sample after feature alignment: 2014-12-22 to 2026-04-16
- OOS: 2021-01-04 to 2026-04-16
- OOS observations: 1327
- Multifactor feature count: 156

| Model | OOS QLIKE | MSE | DM t vs HAR3 | Harvey pass |
|---|---:|---:|---:|---|
| HAR3 | 3.5971 | 1.321e-07 | baseline | baseline |
| MF_Ridge_static | 3.4074 | 1.119e-07 | 0.871 | no |
| MF_ElasticNet_static | 3.0714 | 1.208e-07 | 2.954 | no |
| MF_Ridge_rolling | 3.6554 | 1.213e-07 | -0.253 | no |
| MF_ElasticNet_rolling | 3.1340 | 1.210e-07 | 2.705 | no |

Verdict: `CONDITIONAL_PASS`.

The public-proxy factor bank lowers QLIKE versus HAR3, especially with static ElasticNet, but the best improvement stops just short of the Harvey `|t| > 3` threshold. Rolling adaptation does not dominate static estimation in this daily proxy, which is consistent with the prior K986 warning that adaptive selection can add noise when the factor structure is stable.
