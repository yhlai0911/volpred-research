# Knowledge Handoff - K1597

Do not write this directly into `storage/memory/knowledge.json` without the main-thread K1259 writer gate.

## Proposed Entry

- id: `K1597`
- title: `Non-Gaussian rough volatility proxies on TAIFEX 5-minute RV`
- status: `null_forecast_edge`
- source_experiment: `experiments/k1597`
- data: TAIFEX TX day-session 5-minute bars, 2017-05-16 to 2021-12-30, 1,138 daily RV observations
- primary_result: TAIFEX log RV is rough and Delta log RV is non-Gaussian, but stable-tail, codifference-proxy, and LFSM-lite signals do not pass DM/Holm gates against HAR/HARQ.

## Evidence

- Roughness: frequency-ratio H = 0.0545; variogram H = 0.1428.
- Non-Gaussianity: Jarque-Bera p = 6.82e-17; Student-t improves AIC over Gaussian by 25.29.
- Stable-tail diagnostic: Hill/log-log tail alpha estimates are about 3.58 to 4.21, above the alpha < 2 stable-law region.
- OOS: 488 days from 2020-01-02 to 2021-12-30.
- Mean QLIKE: CodiffAR 0.2203, HARQ 0.2245, LFSM_lite 0.2321, StableTailHAR 0.2402, HAR 0.2444.
- Strict non-Gaussian wins: 0 after Harvey |t| > 3 plus Holm 5pct.

## Safe Claim

TAIFEX day-session 5-minute RV is rough and non-Gaussian, but this bounded K1597 test does not support an alpha-stable or codifference-based one-day forecasting contribution beyond HAR/HARQ.

## Follow-Up

Only revisit as paper material after either a faithful LFSM estimator or a longer cross-asset intraday dataset is available.
