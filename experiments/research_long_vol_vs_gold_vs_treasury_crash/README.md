# research_long_vol_vs_gold_vs_treasury_crash

**Status**: NULL
**Date**: 2026-06-15
**Task source**: `research_long_vol_vs_gold_vs_treasury_crash`

## 動機

研究 backlog 問題：`long-vol`、黃金、長天期美債在不同股市 crash 類型中，誰的保護力最好？

本實驗用公開日頻資料做最小可驗證版本：`VXX`、`GLD`、`TLT` 對 `SPY` 的壓力日保護力。它不使用 options chain，也不把事後才知道的 crash 類型拿來做同日切換。

## 與既有知識的差異

- K549 類結果顯示多資產分散沒有免費 Sharpe，且 `TLT` 在 2022 升息期會變成風險源。
- 既有 GLD/TLT 知識多聚焦 regime correlation 或 vol forecasting；本題改成 `VXX × GLD × TLT` 的 crash-type 條件矩陣。
- 本題額外輸出同日非交易診斷，但策略判讀只看 `t-1` shock type 對 `t` 防禦資產報酬。

## 文獻 / 背景來源

1. Baur and Lucey (2010), *Is Gold a Hedge or a Safe Haven?* `Financial Review`, DOI: `10.1111/j.1540-6288.2010.00244.x`.
2. Longstaff (2004), *The Flight-to-Liquidity Premium in U.S. Treasury Bond Prices*, `Journal of Business`, DOI: `10.1086/386528`.
3. Whaley (2009), *Understanding the VIX*, `Journal of Portfolio Management`, DOI: `10.3905/JPM.2009.35.3.098`.
4. S&P Dow Jones Indices, *S&P VIX Futures Indices Methodology*; VIX futures index products are rolling futures exposure, not spot VIX.

## Data

- Source: `yfinance`, `auto_adjust=False`, adjusted close used for returns.
- Tickers: `SPY`, `VXX`, `GLD`, `TLT`, `^VIX`, `^TNX`.
- Common sample: `2018-01-26` to `2026-06-12`, `2,106` daily rows.
- Train: through `2021-12-31`, `991` rows.
- OOS: from `2022-01-01`, `1,115` rows.
- Limitation: Yahoo `VXX` starts on `2018-01-25` for the tradable Series B ticker, so this experiment does not cover the pre-2018 original VXX history.

CSV snapshots are pinned in `data/`.

## Design

Daily crash signal:

`SPY_ret <= -1.5% OR (SPY_drawdown <= -8% AND SPY_ret < 0)`

Shock type is classified at day `t` after close:

- `liquidity_shock`: `TLT_ret < 0`, `GLD_ret < 0`, and `VIX_chg > 5%`
- `rate_shock`: `TLT_ret < 0` and `TNX_chg > 0`
- `growth_shock`: `TLT_ret > 0` and `TNX_chg < 0`
- `mixed_shock`: remaining crash-signal days

Primary strategy uses only lagged information:

- signal available at `t-1`
- shock type observed at `t-1`
- defensive return evaluated at `t`

For each shock type, the training sample selects the asset with highest mean next-day return. OOS positions are held only on lagged-signal days; otherwise the strategy is in cash. Transaction cost is `10 bps × abs(change in traded asset weights)`, so entering costs 10 bps, exiting costs 10 bps, and switching one defensive asset to another costs 20 bps.

## Results

OOS lagged-signal event counts:

- growth shock: `89`
- rate shock: `76`
- liquidity shock: `39`
- mixed shock: `25`
- total: `229`

Training-selected crash-type rule:

- growth shock -> `GLD`
- rate shock -> `TLT`
- liquidity shock -> `VXX`
- mixed shock -> `GLD`

OOS net strategy results:

| Strategy | Total return | Ann. return | Sharpe | Max DD | Switches | Total cost |
|---|---:|---:|---:|---:|---:|---:|
| crash-type rule | `-34.09%` | `-8.99%` | `-0.577` | `-49.75%` | `319` | `38.20%` |
| static VXX | `-80.19%` | `-30.64%` | `-0.781` | `-84.98%` | `256` | `25.60%` |
| static GLD | `-9.30%` | `-2.18%` | `-0.223` | `-26.31%` | `256` | `25.60%` |
| static TLT | `-40.56%` | `-11.09%` | `-1.284` | `-41.81%` | `256` | `25.60%` |
| equal-weight defense | `-48.85%` | `-14.06%` | `-1.083` | `-52.92%` | `256` | `25.60%` |

Bootstrap on OOS event-day gross returns:

- Rule vs equal-weight: mean diff `+0.169%`, 95% CI `[-0.112%, +0.440%]`, p=`0.250`.
- Rule vs best static OOS hedge (`GLD`): mean diff `-0.071%`, 95% CI `[-0.314%, +0.181%]`, p=`0.563`.

Non-tradable same-day diagnostic:

- On the crash day itself, `VXX` has large same-day protection: mean same-day VXX return is `+4.28%` on growth shocks and `+6.02%` on liquidity shocks.
- This same-day pattern is not a tradable timing result under the project lag rule.

## Conclusion

The ex-post crash-day matrix says long-vol reacts strongly on the crash day, but the tradable `t-1 -> t` rule does not convert that into robust OOS performance. After signal lag and 10 bps turnover cost, the crash-type rotation underperforms static GLD and has no significant event-level bootstrap edge.

The honest conclusion is **NULL**: this public daily-data setup does not support a crash-type-aware defensive rotation rule. It supports only the weaker descriptive statement that same-day crash classification makes VXX look useful, which is not a deployable signal without earlier warning information.

## Files

- `research_long_vol_vs_gold_vs_treasury_crash.py`
- `research_long_vol_vs_gold_vs_treasury_crash_results.json`
- `fig_oos_protection_matrix.png`
- `fig_oos_strategy_cumulative.png`
- `data/*.csv`

## Reproduce

```bash
uv run python experiments/research_long_vol_vs_gold_vs_treasury_crash/research_long_vol_vs_gold_vs_treasury_crash.py
```

To refresh Yahoo snapshots:

```bash
uv run python experiments/research_long_vol_vs_gold_vs_treasury_crash/research_long_vol_vs_gold_vs_treasury_crash.py --refresh-data
```
