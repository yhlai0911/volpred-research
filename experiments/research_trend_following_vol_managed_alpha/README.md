# research_trend_following_vol_managed_alpha

## Objective

測試一個很具體的歸因問題：SPY 的 vol-managed 策略如果看起來有 alpha，這個 alpha 有多少其實只是內嵌的 trend-following 曝險？

這題直接對應 `research_trend_following_vol_managed_alpha` 任務，並承接：

- `k1265`：SPY 上 Moreira-Muir / VIX-managed 的 Sharpe 改善本來就不穩健
- `k1191`：TSMOM hedge 在 VT 題目中有可測的機制意義
- `research_program.md`：2026-06-14 backlog「Trend-following 是否『解釋』vol-managed 策略的全部 alpha」

## Data

- `SPY` adjusted close，yfinance
- `^VIX` close，yfinance
- full download window: 1993-01-01 to 2026-05-01
- in-sample calibration: 1993-01-01 to 2003-12-31
- out-of-sample evaluation: 2004-01-01 to 2026-04-30

快取位置：

- `data/SPY.csv`
- `data/VIX.csv`

## Method

### Vol-managed strategies

兩個主要策略都用 **monthly rebalance + lagged signal**：

1. `mm_rv`
   - `w_t = clip(c_rv / RV_{t-1}^2, 0, 5)`
   - `RV` = 22 日 rolling std × `sqrt(252)`
2. `mm_vix`
   - `w_t = clip(c_vix / VIX_{t-1}^2, 0, 5)`

其中 `c_rv` / `c_vix` 都只用 **in-sample 1993-2003** 校準，讓平均權重約等於 1，避免用全樣本偷看未來。

### Trend factor

月頻 time-series momentum：

- `TSMOM_k(t) = sign(sum_{i=1..k} log(1+r_{t-i})) * r_t`
- primary lookback: `k=12`
- robustness: `k=6`

### Statistical test

月頻 spanning regression，Newey-West HAC 標準誤：

1. market-only
   - `r_vm,t = alpha + beta_mkt * r_mkt,t + e_t`
2. market + trend
   - `r_vm,t = alpha + beta_mkt * r_mkt,t + beta_trend * TSMOM_t + e_t`

重點不是只看 `beta_trend` 是否顯著，而是看：

- `alpha` 在加入 trend 前後縮多少
- residual `alpha` 是否仍顯著
- 這個結果在 `mm_rv` 與 `mm_vix` 是否一致

## Main Result

主結論不是文獻版的「trend 解釋掉全部 alpha」，而是更保守、也更符合本地樣本：

- vol-managed 策略確實帶有明顯 trend loading
- 但本地樣本裡，alpha **在 market-only regression 下就已經不強**
- 加入 12M trend factor 後：
  - `mm_rv` annual alpha 約縮 **45.6%**
  - `mm_vix` annual alpha 約縮 **41.9%**
- 兩者的 residual alpha 都 **沒有達到顯著**

換句話說，這份實驗支持：

1. `trend exposure` 是 vol-managed equity 策略的重要機械成分
2. 但在這個 OOS 設定下，不能誠實地說「原本有一個 robust alpha，然後被 trend 完全吃掉」
3. 更準確的說法是：**本地資料看到的是「內嵌 trend loading + 原始 alpha 本來就弱」**

## Files

- `research_trend_following_vol_managed_alpha.py`
- `research_trend_following_vol_managed_alpha_results.json`
- `cumulative_returns.png`
- `rolling_trend_beta_12m.png`

## Reproducibility

```bash
uv run python experiments/research_trend_following_vol_managed_alpha/research_trend_following_vol_managed_alpha.py
```

## Guardrails

- 嚴格 lag：`signal from t-1, return at t`
- calibration 僅用 in-sample
- 不手改 JSON 補結果
- 若結果與文獻敘事不同，如實報告

## References

1. Moreira, A., & Muir, T. (2017). *Volatility-Managed Portfolios*. Journal of Finance.
2. Cederburg, S., O'Doherty, M. S., Wang, F., & Yan, X. S. (2020). *On the Performance of Volatility-Managed Portfolios*. Journal of Financial Economics.
3. Hood, B., & Raughtigan, C. (2024; rev. 2025). *Volatility Targeting Is Trendy: How Trend Following Explains Alpha in Volatility-Managed Strategies*. SSRN 4773781.
4. Schwarz, P. (2025). *On the performance of volatility-managed equity factors*. Journal of Empirical Finance.
