# K1460 — 股債相關係數 regime 化下的 60/40 適應性配置

## 動機

2022 之後，最常見的 60/40 質疑是：當股債相關係數轉正，債券就失去避險功能，
因此應該做動態調整。問題是，**「相關性變了」不等於「用相關性做交易有用」**。

專案裡已有一個相近先例：

- `K104`：SPY-GLD correlation regime 動態配置為 **NULL**

但 `K104` 研究的是股金配置，不是傳統股債。K1460 重新把問題縮到最實務的版本：

1. 只看美股 + 美國公債 ETF
2. 只用可交易的 lagged rolling correlation 信號
3. 比較 static 60/40 與幾個簡單、可執行的 regime-aware 規則

## 文獻定位

本題不是從零開始。至少有三條相關文獻/實務脈絡：

1. Frazzini and Pedersen (2014), *Betting Against Beta*：低 beta / 槓桿受限框架，
   說明債券在資產配置中的風險角色不是單看預期報酬。
2. Shu, Yu, and Mulvey (2024), *Dynamic Asset Allocation with Asset-Specific
   Regime Forecasts*：regime-aware allocation 可能有價值，但需要比「單一簡單閾值」
   更強的 regime forecast framework。
3. 2024-2026 的 60/40 討論普遍把焦點放在 stock-bond correlation 上升，
   但這種結構變化是否足以支持簡單 tactical rule，仍需回到數據驗證。

K1460 的角色就是：用最小可執行規則先做第一層 falsification。

## 研究問題

在 `SPY + TLT/IEF` 的美股股債組合中，若用 **前月可觀測** 的 60 日 rolling
股債相關係數作為 regime 信號，能否改善 60/40 的 OOS Sharpe 或 MDD？

## 資料

- `SPY.csv`、`TLT.csv`、`IEF.csv`
  - 路徑：`experiments/k1090/data/`
  - 日資料期間：2018-01-02 至 2024-12-30
- FRED `DGS10`、`DGS2`
  - 路徑：`storage/macro/fred_DGS10.csv`, `storage/macro/fred_DGS2.csv`
  - 用途：term spread 背景診斷，不直接作交易信號

## 方法

### 信號

- 用日報酬計算：
  - `corr_tlt_60d = rolling_corr(SPY, TLT, 60d)`
  - `corr_ief_60d = rolling_corr(SPY, IEF, 60d)`
- 取每個月月底的最後一個 60d corr
- **shift(1)** 後才用於下一個月配置，避免 lookahead

### 再平衡與樣本切分

- 月度再平衡
- IS: 2018-01 至 2021-12
- OOS: 2022-01 至 2024-12（36 個月）

### 比較策略

1. `static_60_40_tlt`
   - 60% SPY + 40% TLT
2. `static_60_40_ief`
   - 60% SPY + 40% IEF
3. `dynamic_weight_tlt`
   - 若 lagged `corr_tlt_60d > 0`：80% SPY + 20% TLT
   - 否則：60% SPY + 40% TLT
4. `dynamic_duration`
   - 若 lagged `corr_tlt_60d > 0`：60% SPY + 40% IEF
   - 否則：60% SPY + 40% TLT
5. `dynamic_defensive`
   - 若 lagged `corr_tlt_60d > 0`：40% SPY + 60% IEF
   - 否則：60% SPY + 40% TLT
6. `spy_bh`
   - 100% SPY benchmark

### 統計檢定

- OOS 以 3-month moving block bootstrap、`seed=42`、`B=1000`
- 比較三個 dynamic rule 對 **最佳 static 60/40** 的 Sharpe diff 95% CI

## 主要結果

### OOS (2022-01 至 2024-12)

| Strategy | CumRet | AnnRet | AnnVol | Sharpe | MaxDD |
|---|---:|---:|---:|---:|---:|
| static_60_40_tlt | -0.7% | 1.0% | 15.9% | 0.062 | -22.5% |
| **static_60_40_ief** | **11.4%** | **4.5%** | **13.2%** | **0.345** | **-17.2%** |
| dynamic_weight_tlt | 6.5% | 3.4% | 16.1% | 0.213 | -21.7% |
| dynamic_duration | 2.3% | 1.7% | 14.0% | 0.124 | -21.2% |
| dynamic_defensive | -3.3% | -0.3% | 12.9% | -0.023 | -21.4% |
| spy_bh | 29.4% | 10.6% | 17.4% | 0.608 | -20.2% |

### Bootstrap 對最佳 static benchmark (`static_60_40_ief`)

| Comparison | Observed Sharpe Diff | 95% CI | 結論 |
|---|---:|---:|---|
| dynamic_weight_tlt − static_60_40_ief | -0.132 | [-0.303, +0.010] | 劣勢，邊界接近 0 |
| dynamic_duration − static_60_40_ief | -0.221 | [-0.371, -0.056] | 顯著更差 |
| dynamic_defensive − static_60_40_ief | -0.369 | [-0.539, -0.176] | 顯著更差 |

### Regime 診斷

- OOS 正相關月份占比：`58.3%`
- OOS `SPY-TLT` 平均 60d corr：`+0.075`
- OOS `SPY-IEF` 平均 60d corr：`+0.093`
- 正相關 regime 的平均 term spread：`-0.42`
- 負相關 regime 的平均 term spread：`-0.09`

解讀：2022-2024 確實存在一段偏正的股債相關 regime，而且與更深的 yield-curve
倒掛同時出現。但**可觀測的 regime 存在，不代表簡單的規則就能賺到**。

## Verdict

**NULL / FAIL for simple regime-aware adaptation**

在這個樣本與這組規則下：

1. 最好的 60/40 不是動態規則，而是 **靜態 60/40 SPY/IEF**
2. 用 lagged rolling correlation 做簡單 weight switch / duration switch，
   沒有帶來更好的 OOS Sharpe
3. 最差的不是 static TLT，而是過度防禦的 `dynamic_defensive`

所以較嚴格的說法應該是：

> 股債相關 regime 作為**描述性 state variable**是成立的；
> 但把它直接轉成簡單的 60/40 tactical rule，在 2022-2024 OOS 樣本中沒有
> 產生穩健增量。

## 與既有知識的關係

- 與 `K104` 一致：**相關性動態存在，但可交易規則未必有穩健增量**
- 與很多 2025-2026「60/40 必須重做」的市場敘事不同：至少在這個最小規則集，
  **靜態 short-duration bond sleeve** 比 correlation-aware switching 更有效

## Caveats

1. 樣本只有 2018-2024，OOS 只有 36 個月，屬中小樣本
2. 規則刻意做得很簡單，目的是先 falsify 最常見的 heuristic，不代表所有
   regime model 都無效
3. 這裡比較的是 ETF 可交易配置，不是總報酬指數或 futures overlay
4. FRED term spread 只做背景診斷，未進策略本身

## 檔案

- `k1460_regime_60_40.py`
- `k1460_results.json`
- `k1460_corr_and_nav.png`

## Run

```bash
uv run python experiments/k1460_regime_60_40/k1460_regime_60_40.py
```
