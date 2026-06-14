# K1327-v2: Matched Adaptive Multi-Factor HAR Public-Proxy Test

## Motivation

K1327 tested a public daily-data proxy for Cinquetti et al.'s adaptive multi-factor HAR idea, but Codex review failed the methodology: the HAR baseline used a rolling 1000-day window with 21-day refits, while the best challenger used an expanding window and other challengers used 63-day refits. The reported QLIKE gap therefore mixed model class, training sample, and refit cadence.

K1327-v2 fixes that comparison.

## Literature Pre-Check

This is a methodology repair of K1327, so it inherits the same literature set:

- Cinquetti, Hong, Nolte & Nolte, *Volatility Forecasting Factors* (SSRN / FoFI 2026): motivates factor-specific volatility components and adaptive selection.
- Corsi (2009), *A Simple Approximate Long-Memory Model of Realized Volatility*: HAR-RV baseline.
- Patton (2011), volatility forecast comparison with imperfect proxies: QLIKE as primary loss.

Prior repo context:

- K986 found that daily-scale multi-factor HAR can improve MSE / OOS R2 while hurting QLIKE when variance forecasts become unstable.
- K1327 improved positivity by modeling log variance, but failed the matched-comparison gate.

## Data

Local files only:

- `experiments/k1206/data/{SPY,QQQ,GLD,TLT,IWM,EEM,BTC_USD}.csv`
- `storage/sentiment/vix_historical.csv`
- `storage/sentiment/vvix_historical.csv`
- `storage/sentiment/skew_index.csv`
- `storage/sentiment/credit_spread_proxy.csv`

Target:

- SPY daily squared log return, `rv_t = r_t^2`
- Forecast model space: `log(rv_t)`
- Evaluation: positive variance forecast `exp(pred_log)` against `rv_t`

## Lookahead Policy

Every feature is computed from information available through `t-1`:

- raw OHLC / sentiment / credit features are shifted with `shift(1)`
- rolling means are computed after that lag
- target is same-row `rv_t`

The script keeps `SEED = 42`.

## Method

Primary matched block:

- `HAR3`: rolling 1000-day train window, refit every 21 trading days
- `MF_Ridge_rolling_matched`: same window and cadence
- `MF_ElasticNet_rolling_matched`: same window and cadence

Sensitivity block:

- expanding-window HAR and multi-factor models, all refit every 21 trading days
- this block separates sample-window sensitivity from the primary rolling comparison

Primary metric:

- Patton-style QLIKE on positive variance forecasts
- DM-HLN pairwise tests versus the matched HAR baseline
- strong win requires lower QLIKE and Harvey `|t| > 3`

## Results

Final run:

- Sample after feature alignment: 2014-12-22 to 2026-04-16
- OOS: 2021-01-04 to 2026-04-16
- OOS observations: 1327
- Multifactor feature count: 156

Primary matched rolling block:

| Model | OOS QLIKE | MSE | DM t vs HAR3 | Harvey pass |
|---|---:|---:|---:|---|
| HAR3 | 3.5971 | 1.321e-07 | baseline | baseline |
| MF_Ridge_rolling_matched | 3.6218 | 1.214e-07 | -0.112 | no |
| MF_ElasticNet_rolling_matched | 3.1606 | 1.214e-07 | 2.516 | no |

Sensitivity expanding block:

| Model | OOS QLIKE | MSE | DM t vs HAR3 | Harvey pass |
|---|---:|---:|---:|---|
| HAR3 | 4.0342 | 1.324e-07 | baseline | baseline |
| MF_Ridge_expanding_matched | 3.4074 | 1.119e-07 | 2.767 | no |
| MF_ElasticNet_expanding_matched | 3.0714 | 1.208e-07 | 5.125 | yes |

Verdict: `CONDITIONAL_PASS`.

After matching train window and refit cadence in the primary rolling block, the multi-factor ElasticNet still lowers QLIKE versus HAR3, but the DM-HLN statistic remains below the Harvey `|t| > 3` threshold. The expanding sensitivity block is stronger, which means the sample-window choice matters and should not be mixed into the main model-class claim. This is a weak public-proxy signal, not a claim that the original high-frequency Cinquetti factor design beats HAR.
