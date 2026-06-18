# K1349: 0050.TW 5-Minute HAR-RV Pilot

## Research Question

本實驗驗證 `0050.TW` 5-minute 資料是否已足以支撐 HAR-RV pilot：

1. 本地 5-min 資料品質是否可用？
2. 由 5-min returns 建出的 realized variance 是否比日頻 proxy 更有持續性？
3. 簡單 log-HAR-RV 是否能在 pseudo-OOS 中打敗 naive `RV_{t-1}`？

這是資料解鎖後的第一輪台灣 intraday HAR-RV pilot，不是 paper-grade 結論。

## Prior Work Check

- `K196`：SPY 5-min pilot，指出 RV target 比 daily `r²` 更有 persistence。
- `K744`：SPY 5-min data validation，建立 bar count / gap / proxy quality 檢查流程。
- `research_program.md` line 357：原 backlog 寫「0050.TW 47 天，ETA 2026 Q2」；本次實際可用資料已累積到 94 天。

## Literature

1. Corsi (2009), *Journal of Financial Econometrics*: HAR-RV 的 daily / weekly / monthly realized-volatility cascade。
   https://papers.ssrn.com/sol3/papers.cfm?abstract_id=626064
2. Andersen, Bollerslev, Diebold, and Labys (2003), *Econometrica*: high-frequency returns 用於 realized volatility measurement / forecasting。
   https://econ.duke.edu/~boller/Published_Papers/ecta_03.pdf
3. Hansen and Lunde (2005), *Journal of Financial Econometrics*: intermittent high-frequency data 下 whole-day realized variance 與 overnight component。
   https://ideas.repec.org/a/oup/jfinec/v3y2005i4p525-554.html
4. Barndorff-Nielsen and Shephard (2002), *JRSS-B*: realized volatility / power variation 理論基礎。
   https://ideas.repec.org/a/bla/jorssb/v64y2002i2p253-280.html

## Data

- Source: local `data/intraday/0050_TW_5min_*.csv`
- Ticker: `0050.TW`
- Sample: `2026-01-20` to `2026-06-17`
- Files / trading days used: `94`
- Bars per day: min `53`, median `53`, max `54`
- Large intraday gap days: `0`
- Zero-volume bar days: `90`, usually the opening yfinance bar
- `clean_tw50_data` sanity check on daily close path: `0` adjusted closes, max adjustment `0`

The raw data are 5-minute yfinance bars in UTC. No bars are imputed. RV is computed from observed
5-minute close-to-close log returns.

## Measures

Daily intraday realized variance:

`RV_t = sum_i r_{t,i}^2`

Additional diagnostics:

- `BPV_t = (pi/2) sum_i |r_i| |r_{i-1}|`
- jump variation `max(RV - BPV, 0)`
- realized semivariance `RS+`, `RS-`
- overnight squared return from previous close to today's open
- total RV = intraday RV + overnight squared return

Key descriptive numbers:

- Mean intraday RV: `0.0001001`
- Mean annualized intraday vol: `15.9%`
- Intraday RV lag-1 autocorrelation: `0.265`
- Daily intraday return squared lag-1 autocorrelation: `-0.011`
- Overnight share of total RV: `75.2%`

The persistence gap supports the data-quality premise: 5-minute RV is much less noisy than daily
intraday return squared. The overnight share also warns that an intraday-only HAR-RV target does not
cover whole-day Taiwan ETF variance.

## Forecast Design

Targets:

- `intraday_rv`
- `total_rv = intraday_rv + overnight_sq`

Models:

- `expanding_mean`
- `rv_lag1`
- `ar1_logrv`
- `har_logrv`
- `har_bpv`

Pseudo-OOS:

- First OOS observation index: `60`
- Minimum train observations: `35`
- Intraday RV OOS dates: `2026-04-30` to `2026-06-17`, `34` observations
- Total RV OOS dates: `2026-05-04` to `2026-06-17`, `33` observations

Loss:

`QLIKE = y / h - log(y / h) - 1`

DM test uses `volpred.stats.model_evaluation.dm_test` on pointwise QLIKE losses. Negative t means
the named model is better than `rv_lag1`.

## Lookahead Policy

- HAR target features use `shift(1)`, `rolling(5).mean().shift(1)`, and `rolling(22).mean().shift(1)`.
- BPV features use the same lag convention.
- For forecast date `t`, OLS training rows are `df.iloc[:pos]`, strictly earlier than `t`.
- Seed fixed at `42`.

## Results

Verdict: **PILOT_ONLY_INSUFFICIENT_OOS**

The data pipeline is usable, but the forecast result is not paper-grade because OOS is only `34`
and `33` observations, far below the project minimum of `252`.

### Intraday RV target

| Model | QLIKE | Spearman rho |
|---|---:|---:|
| `expanding_mean` | `0.208` | `-0.026` |
| `rv_lag1` | `0.412` | `0.096` |
| `ar1_logrv` | `0.252` | `0.078` |
| `har_logrv` | `0.287` | `0.043` |
| `har_bpv` | `0.315` | `-0.056` |

`har_logrv` improves QLIKE vs `rv_lag1` by `30.3%`, but DM t is only `-1.15`.
`expanding_mean` is the best QLIKE model, so there is no credible HAR-RV edge yet.

### Total RV target

| Model | QLIKE | Spearman rho |
|---|---:|---:|
| `expanding_mean` | `0.540` | `-0.244` |
| `rv_lag1` | `1.257` | `-0.030` |
| `ar1_logrv` | `0.712` | `-0.095` |
| `har_logrv` | `0.729` | `-0.247` |
| `har_bpv` | `0.554` | `0.212` |

`har_logrv` improves QLIKE vs `rv_lag1` by `42.0%`, but DM t is only `-1.78`, and
`expanding_mean` remains best.

## Interpretation

What holds:

- The 0050.TW 5-minute files are now usable for an intraday RV pipeline.
- Intraday RV persistence (`AC1=0.265`) is much stronger than daily intraday `r²` (`AC1=-0.011`).
- Overnight variance dominates whole-day variance in this short sample, so intraday-only RV must
  be labeled carefully.

What does not hold:

- No HAR-RV model has a Harvey-strength OOS win.
- The pseudo-OOS sample is too short for publication, knowledge entry, or strategy registry use.

## Files

- `K1349.py`
- `K1349_results.json`
- `K1349_daily_realized_measures.csv`
- `K1349_oos_forecasts_intraday_rv.csv`
- `K1349_oos_forecasts_total_rv.csv`
- `fig_k1349_rv_timeseries.png`
- `fig_k1349_oos_qlike.png`
- `fig_k1349_intraday_pattern.png`
- `codex_review.md`

## Reproduce

```bash
uv run python experiments/k1349/K1349.py
```
