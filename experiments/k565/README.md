# K565：BTC 配置加入 12/VIX 投組

## Data & Methodology

- 類型：empirical strategy comparison
- 資料：yfinance `SPY`、`GLD`、`BTC-USD`、`^VIX`，2015-01-02 至 2026-03-26，2,823 日
- 基準：50/50 SPY/GLD，SPY 部位用前一日 12/VIX；BTC 為 5% / 10% / 20% 與條件式版本
- 防前瞻：VIX 與 BTC momentum 訊號均 `.shift(1)`
- 統計：canonical `strategy_dm_test(..., loss_fn="negative_return")`；展示符號維持正值代表 BTC challenger 較佳
- 門檻：Harvey `|t|>3`，且正 t 才算 challenger 正向 PASS

## 2026-07-11 canonical HAC 重跑

原 local DM 在 `h=1` 沒有 HAC，p 值又是單尾。改成 canonical HAC 雙尾檢定後：

| 策略 | 舊 t | canonical HAC t | ACF(1) | Harvey 正向 PASS |
|---|---:|---:|---:|---|
| BTC 5% | 3.074 | 2.862 | -0.015 | FAIL |
| BTC 10% | 3.074 | 2.862 | -0.015 | FAIL |
| BTC 20% | 3.074 | 2.862 | -0.015 | FAIL |
| BTC 5%，VIX<20 | 2.294 | 2.043 | +0.029 | FAIL |
| BTC 5%，60d momentum | 3.372 | 2.989 | -0.008 | FAIL |

Headline 因此由 4 個 Harvey PASS 翻成 **0 個**。5/10/20% 的 t 完全相同仍是比例縮放的
數學結果，不代表三個配置同樣好。post-ETF 的 5% BTC 仍只有 t=0.386，Sharpe 1.8762
對基準 1.8660，沒有正式增益。

ACF(1) 本身均未越過 ±0.0369，但 momentum 的 ACF(3)=0.076，說明只看第一階自相關會漏掉
canonical bandwidth 內的高階依賴。兩次 live-yfinance 重跑 DM t 最大漂移低於 1.4e-8，
gate 完全一致。

限制：README 舊稱 monthly rebalancing，但固定權重乘每日報酬的實作等價於每日維持目標權重；
這是獨立於 HAC 的既有建模限制，不能把本次翻轉歸因到換手頻率。
