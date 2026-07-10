# daily_credit_silence_20260710 — 股票波動率抬升時，信用市場在做什麼？

**類型**：reader-facing daily_article 的 evidence package（非 K 編號實驗；描述性 + 歷史條件對照，無模型估計、無策略回測）
**產出文章**：`mile_66c3fc3b`（audience=general，2026-07-10 published）
**資料截至**：2026-07-09 美股收盤

## 動機

2026 年 7 月上旬，QQQ 的 20 日已實現波動率明顯高於自身 60 日均值，但高收益債
ETF（HYG）的波動率反而下降、高收益利差（OAS）還收窄。直覺想喊「信用市場睡著了」，
但這句話要成立，必須先知道**過去股票波動率同樣偏熱時，信用市場「本來」都怎麼反應**。

## 方法

1. `yfinance` 抓 QQQ / HYG / LQD / ^VIX 日收盤（`auto_adjust=True`）；FRED 抓
   `BAMLH0A0HYM2`（HY OAS）與 `BAMLC0A0CM`（IG OAS）。
2. 已實現波動率 = 20 日對數報酬標準差 × √252，以百分比表示。
3. **主要比較（條件樣本）**：取所有「QQQ 20d RV ≥ 自身前 60 日均值 + 8.7pp」的交易日
   （8.7pp = 當前讀數），看這些日子裡 HY OAS 與 HYG RV 相對各自 60 日均值的變化分佈，
   再把當前值放進去看百分位。基準線用 `.shift(1)` 避免把當日納入自身基準。
4. **輔助對照（回檔事件）**：QQQ 自 252 日高點回檔 ≥10% 的每一段，取谷底日。

## 主要結果（`credit_silence_results.json`）

| 指標（2026-07-09） | 現值 | 相對 60 日均值 | 條件樣本（n=59）中位數 | 百分位 |
|---|---|---|---|---|
| QQQ 20d RV | 30.95% | +8.70 pp | —（條件本身） | — |
| HYG 20d RV | 3.31% | −1.38 pp | +0.47 pp | **0**（最低） |
| HY OAS | 2.70% | −7.5 bp | +26.9 bp | 15 |

- 利差收窄**不是異象**：條件樣本裡有 30.5% 的日子利差同樣收窄，當前落在第 15 百分位。
- 罕見的是 **HYG 自身波動率的降幅是 59 天裡最低**。
- 全樣本 QQQ RV 與 HYG RV 相關係數 0.672 → 兩者長期同向，當前是偏離而非新常態。
- QQQ 距 252 日高點僅 −2.96%，指數層面沒有回檔；高波動來自指數內部換手。

## 誠實邊界

- 條件樣本的 59 天使用**重疊的 20 日視窗**，彼此高度自相關。文中百分位是**描述性位置，
  不是顯著性檢定**，不可當 p 值讀。
- 回檔事件樣本 n=6，太小，不足以支撐任何通則。
- 全文只做同期比較，**不宣稱因果**，不構成投資建議。
- 事件日以回檔谷底定義，屬 ex-post 標註，僅用於歷史分佈對照；**不構成可交易訊號**，
  因此不涉及 lookahead 的策略回測。無隨機程序，故無 seed。

## 檔案

- `credit_silence.py` — 抓數 + 計算，寫出 `credit_silence_results.json` 與 `panel.csv`
- `render_charts.py` — 文章兩張主圖
- `render_lazypack.py` — 懶人包三圖 + 複製主圖到 `storage/reports/assets/credit_silence_20260710/`

## 重跑

```bash
uv run python experiments/daily_credit_silence_20260710/credit_silence.py
uv run python experiments/daily_credit_silence_20260710/render_charts.py
uv run python experiments/daily_credit_silence_20260710/render_lazypack.py
```

數字會隨最新交易日更新；文章內數字對應 `as_of = 2026-07-09`。
