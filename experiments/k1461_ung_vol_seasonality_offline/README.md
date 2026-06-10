# K1461 — UNG realized volatility seasonality under offline DBA constraint

## 問題

原 task 想檢驗：

1. `UNG`（天然氣）與 `DBA`（農產品）realized volatility 是否有顯著季節性
2. 這種季節 pattern 是否與能源 / 通膨 proxy 有關

但這個 sandbox 無法連網，且 repo 內找不到 `DBA` 的本地 OHLC。`yfinance` 實測也因 DNS 失敗而無法補抓。因此這個實驗採 **誠實降級**：

- `UNG` leg：完整完成
- `DBA` leg：明確標記為 blocked，不虛構雙資產結果

## 資料

- `UNG`：`experiments/k1422/data/UNG.csv`
- `USO`（能源 proxy）：`experiments/k1422/data/USO.csv`
- `CPIAUCSL`：`storage/macro/fred_CPIAUCSL.csv`
- `T10YIE`（10y breakeven inflation）：`storage/macro/fred_T10YIE.csv`

樣本：

- `UNG` 日資料：2012-01-03 到 2026-06-05，`n=3627`
- 月頻 proxy frame：`n=158`

## 方法

### 1. 季節性檢定

對 `UNG` 計算兩種 21 日 annualized realized vol：

- close-to-close rolling std
- Parkinson range-based vol

再用：

- one-way ANOVA 檢定 12 個 calendar months 的均值是否相同
- 2000 次 permutation test 驗證 month label 的非參數顯著性

### 2. 與能源 / 通膨 proxy 的關聯

月頻聚合後檢查：

- `UNG RV` vs `USO RV`
- `UNG RV` vs `T10YIE`
- `UNG RV` vs `CPI YoY`

另外跑一個 lagged monthly HAC regression：

`UNG_RV_t ~ UNG_RV_{t-1} + USO_RV_{t-1} + T10YIE_{t-1}`

全部 signal 都用 `t-1`，避免 lookahead。

## 主要結果

### A. UNG 的 month-of-year seasonality 很明顯

close-to-close 與 Parkinson 兩種 proxy 都顯著：

- close-to-close: `F=61.01`, `p=5.2e-125`, permutation `p=0.000`
- Parkinson: `F=25.06`, `p=1.3e-50`, permutation `p=0.000`

最高波動月份都在 `2 月`，最低在 `9 月`：

- Parkinson `Feb = 0.380`
- Parkinson `Sep = 0.280`
- 差距約 `+35.7%`

這不是單一 proxy 假象，兩種 vol 定義方向一致。

### B. 能源 / 通膨 proxy 有關聯，但強度中等

同月相關：

- `corr(UNG RV, USO RV) = 0.249`, `p=0.0016`
- `corr(UNG RV, T10YIE) = 0.252`, `p=0.0014`
- `corr(UNG RV, CPI YoY) = 0.442`, `p<1e-8`

lag-1 相關仍為正，但更弱：

- `corr(UNG RV_t, USO RV_{t-1}) = 0.235`
- `corr(UNG RV_t, T10YIE_{t-1}) = 0.234`

HAC regression 顯示：

- `UNG_RV_{t-1}` 最強，`t=9.33`
- `USO_RV_{t-1}` 僅邊界，`t=1.79`, `p=0.074`
- `T10YIE_{t-1}` 也僅邊界，`t=1.73`, `p=0.084`

所以更合理的解讀是：

- `UNG` 波動有穩定季節性
- 能源 / 通膨 proxy 與它同向，但 **不是很強的獨立預測器**

## 結論

`PARTIAL_SIGNAL`

能成立的結論只有兩個：

1. `UNG` 的 realized vol 有非常強的 calendar-month seasonality
2. 與能源 / 通膨 proxy 的關聯存在，但目前看起來比較像中等共變，不足以說成強預測機制

不能成立的結論：

1. 不能把這個結果外推成 `UNG/DBA` 的共同 commodity pattern
2. 不能說 `USO` 或 `T10YIE` 已經解釋了 UNG seasonality 的主要來源

## 限制

- `DBA` 本地 OHLC 不存在；本 sandbox 也無法連 `yfinance`
- 沒有 `XLE` 本地價格，因此能源側用 `USO` 當 proxy，不是原 task 最理想版本
- `CPI YoY` 是低頻慢變數，和 commodity vol 的同月高相關可能含共同趨勢，不能直接當 causal 證據

## 產出

- `k1461_ung_vol_seasonality_offline.py`
- `k1461_results.json`
- `k1461_ung_vol_seasonality.png`
