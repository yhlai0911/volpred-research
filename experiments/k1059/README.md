# K1059: TSMC Earnings Announcement x 0050.TW Volatility Event Study

**[提出: 賴奕豪, 執行: Claude]**

## 動機

TSMC 佔 0050.TW 約 50% 權重，其財報公告可能是 0050.TW 波動率的重要事件驅動因子。K1050 發現 SPY 在盈餘季的波動率改善是均勻的（非集中於盈餘季），本實驗針對台股市場用**精確公告日**（而非日曆定義的盈餘季）進行事件研究。

## 研究問題

1. TSMC 財報公告日前後 [-5, +5] 天，0050.TW 的波動率是否異常升高？
2. 公告日效應是「事前不確定性」（公告前）還是「事後衝擊」（公告後）？
3. 台股多家公司同日公告時，aggregate volatility 是否更高？
4. A4f（with VIX^2）在公告日附近是否比 GJR 表現更好？

## 數據

| 來源 | 說明 | 期間 |
|------|------|------|
| 財報公告日.txt | Big5 編碼，153,875 筆有日期的記錄，2,409 家公司 | 1987-2026 |
| yfinance 0050.TW | 日頻收盤價（clean_tw50_data 處理 split） | 2009-2025 |
| yfinance ^VIX | 日頻，forward-fill 對齊台股交易日 | 2009-2025 |

- 樣本：4,161 交易日
- TSMC 事件：64 次公告落在樣本期間

## 方法

### Part A: TSMC 事件研究
- 將 TSMC 公告日對齊到最近交易日
- 計算 [-5, +5] 窗口的 abnormal volatility = r^2 / rolling_20d_var
- T-test + Bootstrap 10,000 reps 檢定

### Part B: 聚集效應
- 計算每日公告數量，定義 dense day (>= 90th percentile = 106 家)
- 分組比較波動率
- OLS 回歸：r^2(bp) = a + b1*n_announce + b2*VIX

### Part C: A4f vs GJR 條件分析
- 使用 K1058 的自訂 MLE 實現（multiplicative GARCH-X with VIX^2）
- Rolling window 2000, quarterly refit (63 days)
- OOS: 2010-2025 (3,913 days, 63 refits)
- QLIKE 按事件窗口分組比較

## 核心發現

### Q1: TSMC 公告日波動率 -- NULL RESULT

| 指標 | 數值 |
|------|------|
| 公告日 mean r^2 | 1.80 bp |
| 非公告日 mean r^2 | 1.79 bp |
| 比率 | 1.01x |
| t-stat | 0.018 |
| p-value | 0.986 |
| Bootstrap p | 0.346 |

**結論：TSMC 公告日波動率完全不顯著。** 台積電的財報公告日對 0050.TW 整體波動率沒有統計上可偵測的影響。

### Q2: Pre vs Post -- 無顯著方向性

| 窗口 | Mean r^2 (bp) |
|------|--------------|
| Pre [-5,-1] | 1.53 |
| Day-0 | 1.80 |
| Post [+1,+5] | 1.36 |
| Pre vs Post t-stat | 0.55 (p=0.586) |

兩個 spikes 出現在 day -5 和 day +1，但整體 pre/post 差異不顯著。

### Q3: 聚集效應 -- 反直覺結果

| 類別 | Mean r^2 (bp) | N |
|------|--------------|---|
| 無公告 | 2.06 | 1,367 |
| 有公告 | 1.65 | 2,794 |
| 密集日 (>=106) | 1.54 | 318 |
| TSMC 公告日 | 1.80 | 64 |

**Dense vs No announce: t=-1.39, p=0.165**
**OLS: beta_n_announce = -0.0006 (t=-0.46), beta_VIX = 0.349 (t=22.5)**

**反直覺發現：公告日的波動率反而更低。** 這是因為台灣財報公告密集期（3/5/8/11月）與 VIX regime 不相關，而 VIX 是波動率的主要驅動因子（R^2 = 10.8%，幾乎全由 VIX 解釋）。

### Q4: A4f vs GJR 條件分析 -- 關鍵發現

| 條件 | GJR QLIKE | A4f QLIKE | DM t-stat | A4f Win Rate |
|------|-----------|-----------|-----------|-------------|
| **Overall** (3,913 days) | 2.107 | 2.080 | **2.24** (p=0.025) | 56.1% |
| **Event window** (660 days) | 1.954 | 1.872 | **2.50** | 54.2% |
| **Non-event** (3,253 days) | 2.138 | 2.123 | 1.22 | 56.7% |
| **Day-0 only** (60 days) | 1.618 | 1.500 | 1.77 | 51.7% |

**核心發現：A4f 在 TSMC 事件窗口的 DM t=2.50 顯著優於非事件期 t=1.22。** 這暗示 VIX^2 的外生資訊在公告日附近特別有價值——VIX 可能捕捉到台股財報公告相關的 global uncertainty 信號。

注意：整體 DM t=2.24 低於 Harvey (2016) |t|>3.0 門檻。這與 K1058 的 DM t=-1.26 方向一致（A4f 略優但不到統計顯著），但事件窗口子樣本的 DM t=2.50 值得進一步研究。

## 局限性

1. **樣本量小**：僅 64 次 TSMC 公告事件，統計檢力有限
2. **0050.TW 起始較晚**：yfinance 數據從 2009 開始，錯失 2003-2008 的高波動期
3. **財報公告日精確度**：部分早期數據可能有延遲登錄問題
4. **整體 DM t < 3.0**：不滿足 Harvey (2016) 多重檢定校正門檻
5. **A4f 在事件窗口的優勢**：可能受小樣本偏差，需要更長數據確認
6. **聚集效應的因果推斷**：公告日低波動可能是因為密集期市場較平靜（非因果）

## 文件

| 檔案 | 說明 |
|------|------|
| `k1059.py` | 完整實驗腳本 |
| `k1059_results.json` | 結果 JSON |
| `k1059_event_study.png` | TSMC 事件研究（Panel A: 異常波動, Panel B: CAV） |
| `k1059_clustering.png` | 聚集效應（4 panel: 分布, 類別, 分箱, 月度） |
| `k1059_a4f_earnings.png` | A4f vs GJR 條件分析（4 panel） |

## 參考文獻

- K1050: SPY earnings season vol (A4f uniform, bootstrap p=0.471)
- K1058: A4f on 0050.TW (DM NS t=-1.26, VaR Trinity A4f PASS / GJR FAIL)
- K176: TSMC DeltaCoVaR = -1.599 (4.6x SPY)
- Patton (2011): QLIKE, J Econometrics 160:246-256
- Andersen & Bollerslev (1998): DM$ volatility event study

## Random Seed
42
