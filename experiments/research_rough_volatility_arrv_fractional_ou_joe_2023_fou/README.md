# Rough Volatility ARRV/fOU Race on Local 5-Minute RV

Experiment id: `research_rough_volatility_arrv_fractional_ou_joe_2023_fou`

Task id: `research_rough_volatility_arrv_fractional_ou_joe_2023_fou`

## Motivation

The backlog hypothesis was that rough-volatility structure may matter once the
target is true high-frequency realized variance rather than daily squared
returns. Prior repo evidence on daily roughness/Hurst features was mostly NULL
(`K1423`, `K1424`, `K625`, `K806`, `K973`, `K1497`), but those tests either used
daily proxies or roughness as a covariate. This test moves to local 5-minute RV.

## Literature Anchors

- Wang, Xiao, and Yu (2023), Journal of Econometrics: fractional
  Ornstein-Uhlenbeck RV forecasting and change-of-frequency Hurst estimation.
- Bibinger, Yu, and Zhang (2025), arXiv:2504.15985: multivariate fractional
  Brownian/RV forecasting motivation.
- ARRV / regularity-modified volatility forecasting (2023), Finance Research
  Letters: roughness combined with autoregressive RV forecasting.
- Corsi (2009): HAR-RV benchmark.
- Patton (2011): QLIKE forecast comparison.

## Data

Primary formal test:

- Asset: TAIFEX TX futures day session.
- Source: `experiments/k1100h/data/_taifex_5min_2017-2021.parquet`.
- Period: 2017-05-16 to 2021-12-30.
- Sample: 1,138 trading days, median 59 intraday returns per day.
- Target: day-session 5-minute realized variance.
- OOS: 2020-01-01 to 2021-12-30, 488 forecast days.

Diagnostic only:

- Asset: SPY.
- Source: `data/intraday/SPY_5min_2026-*.csv`.
- Period: 2026-01-14 to 2026-06-29.
- Sample: 113 trading days, median 77 intraday returns per day.
- OOS diagnostic: 2026-05-01 to 2026-06-29, 40 forecast days.
- Status: not formal inference; below the 252-day OOS floor.

## Models

- `HAR`: log-HAR with daily, weekly, and monthly realized-variance lags.
- `HARQ`: HAR plus realized-quarticity interaction.
- `ARRV`: log-RV autoregression plus fractional-kernel RV state.
- `fOU_lite`: transparent fractional-OU-style log-RV mean-reversion proxy.

All forecasts for date `t` use only information through `t-1`. The script uses
repo QLIKE/DM helpers from `volpred.stats.model_evaluation`.

## Findings

TAIFEX roughness diagnostics:

- Frequency-ratio H = 0.0545.
- Variogram H = 0.1428, R2 = 0.9794.
- Both estimates are well below 0.5, so 5-minute RV roughness is visible.

TAIFEX OOS QLIKE:

| Model | QLIKE | DM vs HAR t | Harvey pass |
|---|---:|---:|---|
| HAR | 0.2444 | baseline | no |
| HARQ | 0.2269 | -1.8704 | no |
| ARRV | 0.2697 | +1.3474 | no |
| fOU_lite | 0.4980 | +2.1744 | no |

TAIFEX high-VIX regime (`VIX >= 20`, n=291):

- HARQ still has the lowest QLIKE (0.2365 vs HAR 0.2614), but DM t=-1.6495.
- ARRV and fOU-lite do not beat HAR.

SPY short diagnostic:

- Frequency-ratio H = 0.0916; variogram H = 0.0511.
- OOS diagnostic QLIKE: HAR 0.3901, HARQ 0.3722, ARRV 0.3938, fOU-lite 0.5243.
- No rough model beats HAR. This is not formal inference because n=40.

## Conclusion

Result: **NULL for rough-vol forecasting contribution**.

Local 5-minute RV makes low-H roughness visible in the daily sequence of
realized-variance estimates, but the roughness signal does not translate into a
Harvey-grade allocation/forecasting improvement. The finding is a
measurement-versus-allocation result, scoped to these proxy models and samples,
not a rejection of all structural rough-volatility models.

## Files

- Script: `research_rough_volatility_arrv_fractional_ou_joe_2023_fou.py`
- Results: `research_rough_volatility_arrv_fractional_ou_joe_2023_fou_results.json`
- Figure: `rough_vol_model_race.png`
