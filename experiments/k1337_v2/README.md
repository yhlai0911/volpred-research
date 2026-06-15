# K1337-v2: Yield Curve dV/dt -> SPY Forward RV

**Verdict: NULL**
**Run date:** 2026-06-15
**Parent:** `experiments/k1337/` is preserved as a flawed-design preliminary.

## Motivation

K1337 v1 tested whether the rate of yield-curve steepening or flattening
(`dV/dt`) predicts SPY forward realized volatility. Codex review failed v1
because expanding OLS used `df.iloc[:i]` while each training target
`fwd_var_H(j)` needed future returns through `j+H`. For horizons above one
day, the last `H` training labels overlapped the forecast date.

K1337-v2 reruns the same 18-cell grid with a strict forward-label cutoff and a
symmetric model baseline.

## Data

- Source: yfinance daily Close, `auto_adjust=False`
- Tickers: `^TNX`, `^IRX`, `^FVX`, `^VIX`, `SPY`, `XLF`, `XLU`
- Sample after SPY returns: 2014-01-03 to 2026-06-12, 3,129 rows
- Cached reproducibility file: `data/close.csv`

## Corrected Design

- Target: `fwd_var_H(t) = 252 * mean(r^2)` over returns `t+1 ... t+H`.
- Training cutoff: for forecast row `i`, a training row `j` is admissible only
  when `target_end_pos(j) < forecast_pos(i)`, equivalent to `j + H < i` on the
  original trading-day index.
- Signals: `slope.diff(N)` for `TNX-IRX` and `TNX-FVX`, with
  `dslope.shift(1)` used in both the forecasting model and regime labels.
- Baseline: expanding log-HAR variance model,
  `log(fwd_var) ~ log_rv_d + log_rv_w + log_rv_m`.
- Augmented: same model class plus `dslope_lag1`.
- Both baseline and augmented use the same warmup (`504` rows), refit cadence
  (`21` trading days), annualized-variance clipping (`[1e-8, 4.0]`), QLIKE
  loss, DM-HAC, and stationary block bootstrap.
- Regime labels use lagged dV/dt; rolling quantile thresholds exclude the
  current row before classifying `FAST_STEEPEN`, `FAST_FLATTEN`, or `MID`.

## Main Results

The corrected 18-cell grid has 2,564 to 2,594 OOS observations per spec.

| Signal | N | H | QLIKE improvement | DM t | DM p | Bootstrap 95% CI |
|---|---:|---:|---:|---:|---:|---|
| TNX-IRX | 5 | 5 | -1.667% | +1.415 | 0.157 | [-0.0026, +0.1321] |
| TNX-IRX | 5 | 10 | -1.705% | +1.137 | 0.255 | [-0.0056, +0.1377] |
| TNX-IRX | 5 | 20 | -0.646% | +0.904 | 0.366 | [-0.0060, +0.0527] |
| TNX-IRX | 10 | 5 | -1.679% | +1.378 | 0.168 | [-0.0064, +0.1307] |
| TNX-IRX | 10 | 10 | -1.329% | +1.152 | 0.249 | [-0.0107, +0.1064] |
| TNX-IRX | 10 | 20 | -0.633% | +1.006 | 0.314 | [-0.0049, +0.0471] |
| TNX-IRX | 20 | 5 | -0.428% | +1.154 | 0.249 | [-0.0067, +0.0360] |
| TNX-IRX | 20 | 10 | -0.266% | +1.096 | 0.273 | [-0.0036, +0.0205] |
| TNX-IRX | 20 | 20 | -0.329% | +1.240 | 0.215 | [-0.0019, +0.0219] |
| TNX-FVX | 5 | 5 | +0.052% | -0.218 | 0.827 | [-0.0124, +0.0105] |
| TNX-FVX | 5 | 10 | -0.060% | +0.916 | 0.360 | [-0.0011, +0.0046] |
| TNX-FVX | 5 | 20 | -0.071% | +0.964 | 0.335 | [-0.0011, +0.0050] |
| TNX-FVX | 10 | 5 | -0.013% | +0.154 | 0.877 | [-0.0043, +0.0048] |
| TNX-FVX | 10 | 10 | -0.269% | +1.710 | 0.087 | [-0.0002, +0.0157] |
| TNX-FVX | 10 | 20 | -0.320% | +1.583 | 0.113 | [-0.0002, +0.0181] |
| TNX-FVX | 20 | 5 | -0.262% | +2.326 | 0.020 | [+0.0012, +0.0130] |
| TNX-FVX | 20 | 10 | -0.483% | +2.640 | 0.008 | [+0.0039, +0.0217] |
| TNX-FVX | 20 | 20 | -0.530% | +1.751 | 0.080 | [+0.0014, +0.0265] |

Positive DM t means augmented is worse. Only one cell has positive QLIKE
improvement, `TNX-FVX N=5 H=5`, and it is economically tiny (+0.052%) with
DM t=-0.218 and bootstrap CI crossing zero.

## Interpretation

The corrected result is **NULL**. Yield-curve dV/dt does not improve a
symmetric log-HAR baseline for SPY forward variance under the pre-set 18-spec
grid. Several specs are directionally worse, and none approaches the Harvey
multi-test threshold.

Regime tables still show that high absolute curve moves often coincide with
high VIX / higher forward volatility, but this does not translate into
incremental out-of-sample forecast accuracy after HAR information is included.

## Limitations

- Daily close-to-close squared returns are a variance proxy, not intraday RV.
- Yahoo yield indexes can have transient download failures; `data/close.csv`
  is cached for exact reruns.
- Treasury curve proxies are simple `^TNX-^IRX` and `^TNX-^FVX`, not SOFR/OIS
  curves or macro release-aware term structure data.
- The augmented model is linear in lagged dV/dt; nonlinear interactions with
  VIX or inflation news are not tested here.

## Reproduce

```bash
uv run python experiments/k1337_v2/K1337_v2.py
```

Outputs:

- `K1337_v2_results.json`
- `K1337_v2_overview.png`
- `K1337_v2_grid.png`
- `data/close.csv`

## References

- Corsi (2009), "A Simple Approximate Long-Memory Model of Realized Volatility": https://papers.ssrn.com/sol3/papers.cfm?abstract_id=626064
- Patton (2011), "Volatility forecast comparison using imperfect volatility proxies": https://public.econ.duke.edu/~ap172/Patton_vol_proxies_JoE_2011.pdf
- Diebold and Mariano (1995), "Comparing Predictive Accuracy": https://www.jstor.org/stable/1392155
- Newey and West (1987), HAC covariance matrix: https://www.jstor.org/stable/1913610
- Harvey, Liu, and Zhu (2016), multiple-testing discipline: https://academic.oup.com/rfs/article/29/1/5/1843824
