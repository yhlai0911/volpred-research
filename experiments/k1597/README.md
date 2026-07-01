# K1597 - Non-Gaussian Rough Volatility Stable-Increment Proxies

## Verdict

`NON_GAUSSIAN_BUT_NOT_STABLELIKE_NO_EDGE`

TAIFEX 5-minute day-session log-RV increments are rough and non-Gaussian, but the evidence does not support an alpha-stable-increment forecasting claim in this local test. Tail diagnostics prefer Student-t over Gaussian errors, yet Hill/log-log tail indices are about 3.6 to 4.2, not the alpha < 2 region implied by stable laws. The best mean-QLIKE model is `CodiffAR`, but it does not pass Harvey |t| > 3 or Holm 5pct gates against HAR or HARQ.

## Motivation

Garcin, Sawaya, and Valade (2026) propose prediction for linear fractional stable motions using codifference rather than covariance, with application to non-Gaussian rough volatility. The local question is narrower:

Can transparent stable-tail, codifference-proxy, or LFSM-lite signals improve one-day-ahead realized-variance forecasts beyond HAR/HARQ on local 5-minute TAIFEX realized volatility?

This is a bounded falsification exercise, not a full LFSM estimator.

## Literature Checked

- Garcin, Sawaya, and Valade (2026), "Prediction of linear fractional stable motions using codifference, with application to non-Gaussian rough volatility." https://arxiv.org/abs/2507.15437
- Gatheral, Jaisson, and Rosenbaum (2018), "Volatility is rough." https://doi.org/10.1080/14697688.2017.1393551
- Cont and Das (2024), "Rough Volatility: Fact or Artefact?" https://ideas.repec.org/a/spr/sankhb/v86y2024i1d10.1007_s13571-024-00322-2.html
- Corsi (2009), "A Simple Approximate Long-Memory Model of Realized Volatility." https://academic.oup.com/jfec/article-abstract/7/2/174/787440
- Patton (2011), "Volatility forecast comparison using imperfect volatility proxies." https://doi.org/10.1016/j.jeconom.2010.03.034

## Data

- Source: `experiments/k1100h/data/_taifex_5min_2017-2021.parquet`
- Market: TAIFEX TX futures, day session only
- Sample: 2017-05-16 to 2021-12-30
- Daily observations: 1,138
- Median intraday returns per day: 59
- Target: daily realized variance from 5-minute bar-close log returns

## Diagnostics

Roughness on log RV:

- Frequency-ratio H: 0.0545
- Variogram H: 0.1428, R2 = 0.9794

Non-Gaussianity on daily Delta log RV:

- Observations: 1,137
- Excess kurtosis: 1.1259
- Jarque-Bera p-value: 6.82e-17
- Student-t df: 8.94
- AIC normal minus Student-t: 25.29

Stable-tail check:

- Hill absolute-tail alpha, top 10pct: 3.6256
- Hill absolute-tail alpha, top 5pct: 4.2105
- Log-log survival alpha, top 20pct: 3.5781

Interpretation: increments are non-Gaussian, but the estimated tail indices are materially above 2, so this sample does not support an alpha-stable infinite-variance reading.

## Models

- `HAR`: log-RV HAR with 1-day, 5-day, and 22-day lagged components
- `HARQ`: HAR plus lagged realized-quarticity information
- `StableTailHAR`: HAR plus lagged MAD-scaled tail shock and signed-power shock features
- `CodiffAR`: autoregression on lagged Delta log RV, signed-power lags, and an empirical characteristic-function codifference proxy
- `LFSM_lite`: Delta log RV model using fractional-stable kernel weights based on rolling H and Hill alpha diagnostics

Every forecast for date `t` uses realized-volatility information through date `t-1`. Training rows target day `j` and use features dated `j-1` or earlier.

## Formal OOS Test

- OOS window: 2020-01-02 to 2021-12-30
- OOS observations: 488
- Refit frequency: 21 trading days
- Loss: QLIKE, `actual / forecast - log(actual / forecast) - 1`
- Inference: repo DM/HAC test, horizon `h=1`; strict gate requires lower loss, Harvey |t| > 3, and Holm 5pct across reported pair tests

Mean QLIKE, lower is better:

| Model | QLIKE |
|---|---:|
| CodiffAR | 0.2203 |
| HARQ | 0.2245 |
| LFSM_lite | 0.2321 |
| StableTailHAR | 0.2402 |
| HAR | 0.2444 |

Key DM tests:

| Test | t-stat | p-value | Holm p | Strict win |
|---|---:|---:|---:|---|
| CodiffAR vs HAR | -1.319 | 0.188 | 0.939 | no |
| CodiffAR vs HARQ | -0.576 | 0.565 | 0.939 | no |
| LFSM_lite vs HAR | -1.461 | 0.145 | 0.876 | no |
| StableTailHAR vs HAR | -1.028 | 0.304 | 0.939 | no |

`CodiffAR` has the lowest mean QLIKE, but the improvement is not statistically robust. There are zero non-Gaussian strict wins.

## Interpretation

Safe claim:

> TAIFEX day-session 5-minute RV is rough and non-Gaussian, but K1597 does not find an alpha-stable or codifference-based one-day forecasting contribution beyond HAR/HARQ.

Unsafe claim:

> Non-Gaussian rough volatility or the Garcin-Sawaya-Valade LFSM method is disproven.

That would overstate the evidence. K1597 uses a single local market and transparent lite proxies rather than a full LFSM conditional-expectation estimator.

## Artifacts

- `k1597.py`
- `k1597_results.json`
- `k1597_oos_forecasts.csv`
- `k1597_tail_and_oos.png`
- `codex_review.md`
- `knowledge_handoff.md`
