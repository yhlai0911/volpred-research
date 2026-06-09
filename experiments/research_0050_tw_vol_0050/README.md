# research_0050_tw_vol_0050

## 任務

關閉 pending backlog：

`除息日對 0050.TW 的 vol 影響（0050 成分股集中除息期間）`

## 為什麼這次不重跑

因為 repo 內已有兩個直接相關、而且口徑互補的實驗：

1. `K512`：0050.TW 除息事件窗研究
2. `K917`：0050.TW / 0056.TW 除息季節性（聚集月份）vol 研究

這個 backlog 其實是在問：

- 除息事件本身有沒有短窗波動效果？
- 除息「集中期間」有沒有系統性季節性 vol regime？

這兩件事已分別被 K512 與 K917 覆蓋。

## 既有答案

### K512

- `0050.TW` 的除息事件窗之後短期波動率有溫和抬升
- `post_near vs control`：t = 2.278, p = 0.032
- 這代表「局部 event-window effect」存在

### K917

- 若把問題擴大成「除息季 / 集中除息月份是否整體更高波動」
- 結論是 **NULL**
- 夏季 RV = 0.169 vs 其他月份 0.185
- Welch t = -1.033, p = 0.303
- VIX 控制後也不顯著

## 綜合判定

這個 backlog 不需要再開一個全新 0050.TW 除息 vol 實驗。

比較準確的總結是：

- **短窗事件效應**：有一點
- **整體季節 / 聚集期 regime effect**：沒有穩健證據

## 若未來要延伸

只有在以下情況才值得重開：

1. 改問「0050 成分股除息 cluster」而不是 ETF 本身 ex-date
2. 做 constituent-level → ETF aggregation decomposition
3. 納入 2026 之後新樣本再驗證

## 檔案

- `research_0050_tw_vol_0050.py`
- `research_0050_tw_vol_0050_results.json`

