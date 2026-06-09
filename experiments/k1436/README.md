# K1436: BTC perpetual funding rate as RV covariate — Feasibility Audit

## 動機

任務原始方向是測試：`Binance perpetual funding rate` 能否作為 BTC realized volatility 的額外 covariate，加入 `HAR-RV` 後提升預測。

這個問題本身合理，因為 repo 既有知識已經多次指出：

- BTC 波動更像「crowding / derivatives-conditioned」而不是傳統 equity leverage effect
- 如果要真正改善 BTC volatility model，較可能需要 **funding / OI / liquidation** 類衍生品資料

但研究誠實原則要求，不能在沒有本地 canonical 資料源時假裝完成正式實驗。

## 這輪檢查的三件事

1. repo 內是否已有可重現的 funding-rate 資料檔
2. repo 內是否已有足夠的 BTC intraday 資料，可建立 HAR-RV target
3. 是否已有接近題目的既有實驗可直接重用

## 結果

- **沒有**找到 canonical 的 BTC funding-rate / Binance perpetual 資料檔
- **沒有**找到本地 BTC 5-min / 1h / intraday cache，可用來建 realized volatility target
- repo 裡確實有 BTC 日頻 OHLCV CSV
- repo 裡也有 `experiments/btc_derivatives_vol/`，但那條線測的是 volume / weekend / VIX proxy，不是 funding rate

## 為什麼這不能硬做

因為若只有日頻 OHLCV，最容易滑向兩個錯法：

1. 把 daily squared return 當成 `HAR-RV` target，違反 target-match 規則
2. 用一次性外網抓下來的 funding data 直接做結論，違反可重現性要求

兩者都不符合本專案的研究標準。

## 結論

本輪 K1436 的正確結論是：

**`BLOCKED_DATA_UNAVAILABLE`**

阻塞點不是模型，而是資料層：

- 缺 funding-rate canonical series
- 缺 BTC intraday RV target data

## 下一步

1. 建立本地 canonical funding-rate 歷史檔
2. 建立本地 BTC intraday bar cache
3. 補齊後再跑正式的 `HAR-RV` vs `HAR-RV+funding` OOS 實驗

## 檔案

- `k1436.py` — feasibility audit 腳本
- `k1436_results.json` — audit 結果

