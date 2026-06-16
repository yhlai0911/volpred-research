# K1518 - TWSE Foreign Flow as Taiwan Sector-Vol Leading Indicator

**Verdict**: `NULL`

Lagged foreign institutional net-selling shocks from the official TWSE T86
report do **not** provide robust out-of-sample predictive power for next-week
Taiwan sector realized variance. The pooled model has a small positive QLIKE
improvement, but the Diebold-Mariano test is far from significant and sector
results are directionally mixed.

## Research Question

Can foreign institutional selling pressure predict higher realized volatility
in Taiwan equity sectors after controlling for simple HAR-style realized
variance lags?

This tests a plausible institutional-flow-to-volatility channel using only
public data: TWSE three-institution flow reports plus yfinance Taiwan equity
prices.

## Data

- Flow: TWSE official T86 three-institution daily report, sampled at each
  week's actual last trading day
- Prices: yfinance adjusted close for selected Taiwan stocks
- Period: 2018-01-01 to 2026-06-17
- Usable panel after rolling z-score warmup, lags, and targets: **1,221**
  sector-week rows
- Train: rows before **2022-01-01**, **543** pooled rows
- OOS: rows from **2022-01-01** onward, **678** pooled rows
- Target: next 5 trading days equal-weight sector realized variance

Sector baskets:

- Semiconductor: `2330`, `2454`, `2303`
- Financial: `2881`, `2882`, `2891`
- Traditional: `1301`, `1303`, `2002`, `2603`

## Methodology

Baseline:

```text
log RV_{t+1:t+5} ~ log RV5_t + log RV20_t
```

Augmented model:

```text
log RV_{t+1:t+5} ~ log RV5_t + log RV20_t + foreign_sell_z_lag1
```

The foreign-flow signal is sector-level foreign net value in TWD, converted to
a trailing 52-week z-score and multiplied by `-1` so larger values mean larger
foreign net-selling shocks.

Models are fixed-window OLS estimated on the training sample only. The pooled
model includes sector fixed effects.

## Lookahead Defenses

1. Target at week-ending date `t` uses only returns from `t+1` through `t+5`.
2. Foreign net-selling z-scores use trailing rolling windows only.
3. The primary flow signal is explicitly shifted one additional week via
   `foreign_sell_z.shift(1)`.
4. Train/OOS split is strictly temporal: train rows before 2022-01-01, OOS rows
   from 2022-01-01 onward.
5. OOS predictions use coefficients fit only on the training sample.

## Results

| Model | n_train | n_oos | QLIKE base | QLIKE aug | Improvement | DM t | DM p |
|---|---:|---:|---:|---:|---:|---:|---:|
| Financial | 181 | 226 | 0.9498 | 0.9664 | -1.74% | +0.472 | 0.637 |
| Semiconductor | 181 | 226 | 0.5819 | 0.5716 | +1.78% | -0.645 | 0.520 |
| Traditional | 181 | 226 | 0.6427 | 0.6452 | -0.39% | +0.695 | 0.488 |
| Pooled | 543 | 678 | 0.7085 | 0.7059 | +0.36% | -0.477 | 0.633 |

DM sign convention: negative `DM t` favors the augmented flow model because the
test is run on `loss_aug - loss_base`.

The pooled improvement is economically tiny and statistically insignificant.
Only the semiconductor basket improves, and that improvement is not
statistically reliable. Financials and traditional sectors get worse.

## Interpretation

The experiment does not reject the null that TWSE foreign-flow shocks add no
forecasting power beyond recent realized variance. The in-sample coefficient is
positive in pooled and semiconductor/financial specifications, but OOS loss
does not improve consistently enough to support a publishable leading-indicator
claim.

The strongest statement supported here is narrow:

> In this weekly public-data specification, lagged foreign net-selling pressure
> is not a robust Taiwan sector-volatility leading indicator after controlling
> for HAR-style realized variance lags.

## Caveats

1. This is a weekly PoC. It samples the official daily T86 report only at each
   week's actual last trading day, so it does not test the full daily signal.
2. Baskets are small liquid proxies for broad sectors, not complete TWSE sector
   universes.
3. yfinance adjusted close is convenient but not an official Taiwan price feed.
4. OOS size is moderate at 226 weeks per sector; overlapping horizon and weekly
   aggregation reduce effective independent information.
5. The TWSE endpoint can return temporary non-JSON security pages under heavy
   automated access, so the script uses a local cache and slow retries.
6. Flow is measured in net traded value, not signed order imbalance,
   intraday pressure, or investor-level holdings.

## References

1. TWSE T86 三大法人買賣超日報 official data page.
   https://www.twse.com.tw/zh/trading/foreign/t86.html
2. Wei (2009), "Taiwan institutional trading volume volatility spillover on
   stock market index return."
   https://ideas.repec.org/a/ebl/ecbull/eb-08c30093.html
3. Lin, Lee, and Chiu (2009), foreign investors' trading behavior and Taiwan
   stock market impact.
   https://ideas.repec.org/a/eee/riibaf/v23y2009i1p78-89.html
4. "Structural changes in foreign investors' trading behavior and impact on
   Taiwan stock market" (PMC full text).
   https://pmc.ncbi.nlm.nih.gov/articles/PMC7148904/

## Reproducibility

```bash
uv run python experiments/k1518_twse_foreign_flow_sector_vol/k1518.py
```

Outputs:

- `k1518_results.json`
- `k1518_plots.png`
- `k1518_weekly_t86_flows.csv`
