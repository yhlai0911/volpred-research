# K1548 — Taiwan Investor USD/TWD Equity Hedge Ratios

## Research Question

For a Taiwan-based investor holding liquid USD equity ETFs, does a dynamic currency hedge ratio reduce realized TWD volatility more than simple full or static minimum-variance hedging?

The tested policies are:

- `unhedged`: full USD/TWD exposure (`h=0`)
- `full_hedge`: remove USD/TWD return (`h=1`)
- `static_mv`: training-period minimum-variance ratio, `h = 1 + cov(asset, fx) / var(fx)`
- `ewma_dcc_lite`: EWMA covariance proxy with `lambda=0.94`; this is not a full DCC-GARCH MLE
- `hmm_regime`: 2-state Gaussian HMM fit only on training returns; OOS hedge ratio uses the previous-day inferred state

## Literature Basis

- Engle (2002), Dynamic Conditional Correlation: motivates time-varying covariance hedge ratios. Source: https://www.tandfonline.com/doi/abs/10.1198/073500102288618487
- Kroner and Sultan (1993), dynamic foreign-currency futures hedging: canonical dynamic FX hedging benchmark. Source: https://ideas.repec.org/a/cup/jfinqa/v28y1993i04p535-551_00.html
- Optimal currency hedging for international equity portfolios: frames strategic currency hedging for international equity portfolios. Source: https://www.tandfonline.com/doi/full/10.1080/0015198X.2019.1628556

Related prior memory: R14 / K1006-family work found that unhedged USD exposure can cushion Taiwan-investor global portfolios during some local drawdowns. K1548 tests a narrower objective: ex-post realized-volatility minimization for USD equity ETF overlays.

## Data

- Source: `yfinance`
- Download window: 2015-01-01 to 2026-06-24
- USD/TWD ticker used: `TWD=X`
- USD assets: `SPY`, `EFA`, `EEM`, `QQQ`
- Local TWD context benchmarks: `0050.TW`, `^TWII`
- Training sample: 2015-01-05 to 2019-12-31, 1206 asset/FX intersection observations per USD ETF
- OOS sample: 2020-01-03 to 2026-06-23, 1564 asset/FX intersection observations per USD ETF
- Stored daily return panel: `data/k1548_daily_returns.csv`

The script intentionally does not forward-fill across market calendars. Each USD ETF test uses days where both the asset and USD/TWD close returns are observed.

## Method

TWD return with hedge ratio `h_t` is:

```text
(1 + r_asset_usd_t) * (1 + (1 - h_t) * r_usdtwd_t) - 1
```

Hedge ratios are clipped to `[0, 1.5]`. There is no carry, forward-point, transaction-cost, tax, or hedge-instrument roll model.

Lookahead controls:

- Static hedge ratios use only the 2015-2019 training sample.
- EWMA `h_t` is computed before return `t` updates covariance, so return `t` only affects `h_{t+1}`.
- HMM parameters and state-specific hedge ratios are train-only.
- OOS HMM `h_t` uses the state inferred through `t-1`; day-`t` returns are not used to set day-`t` hedge ratios.

Statistical gate: for each policy vs `unhedged`, the paired daily squared-return reduction must have HAC `t > 3` and a 3000-rep circular block-bootstrap 95% CI above zero.

## Results

Verdict: `STATIC_OR_FULL_HEDGE_DOMINATES_DYNAMIC_IN_FREE_DATA_OOS`.

Average OOS results across `SPY`, `EFA`, `EEM`, and `QQQ`:

| Policy | Avg vol reduction vs unhedged | Avg downside semivol reduction | Avg Sharpe | Avg hedge ratio |
|---|---:|---:|---:|---:|
| `full_hedge` | 5.01% | 4.62% | 0.742 | 1.000 |
| `static_mv` | 4.91% | 4.58% | 0.748 | 0.907 |
| `hmm_regime` | 4.94% | 4.59% | 0.748 | 0.956 |
| `ewma_dcc_lite` | 3.97% | 3.62% | 0.757 | 0.990 |

All four non-baseline policies pass the squared-return reduction gate for all four USD ETF proxies. However, the dynamic overlays do not beat the simple full/static hedge on realized-volatility reduction:

- `full_hedge` has the highest average vol reduction at 5.01%.
- `static_mv` is nearly tied with full hedge and uses training-sample ratios from 0.892 to 0.917.
- `hmm_regime` is close to static, but its regime-state hedge ratios mostly approximate a near-full hedge.
- `ewma_dcc_lite` improves Sharpe in this sample but gives weaker vol and downside reduction than static/full hedge.

Interpretation: the result supports currency hedging as a vol-reduction overlay for Taiwan investors holding USD equity ETFs, but does not support paying model complexity for this DCC-lite/HMM dynamic specification. This is not evidence against all dynamic currency hedging; it is a free-data, no-cost, close-to-close proxy result.

## Figures

- `figures/k1548_spy_cumulative_returns.png`
- `figures/k1548_vol_reduction.png`
- `figures/k1548_downside_reduction.png`
- `figures/k1548_average_hedge_ratios.png`
- `figures/k1548_ewma_hedge_paths.png`

## Reproduction

```bash
uv run python experiments/k1548/k1548.py
```

Main artifacts:

- `k1548.py`
- `k1548_results.json`
- `data/k1548_daily_returns.csv`
- `figures/*.png`
- `codex_review.md`

## Limitations

- No forward points, carry, hedge costs, taxes, or rolling futures/forward mechanics.
- `ewma_dcc_lite` is an EWMA covariance proxy, not a full DCC-GARCH implementation.
- HMM is fit only on the pre-2020 training sample to prevent lookahead, so regime adaptation may be too static.
- USD ETFs proxy globally diversified exposure; Taiwan-listed wrappers and actual investor execution may differ.
- Knowledge promotion is deferred to the main K1259 writer gate; this Codex experiment does not write `storage/memory/knowledge.json`.
