# K1480: 0050 成分調整 fragility 題目的 feasibility audit

## 研究問題

原 queue 題目是：

> 被動化與個股 fragility：0050 成分調整 vol event study  
> 用 TWSE / FTSE 公告，把納入 / 剔除事件前後的 RV 與 idiosyncratic vol 做 DiD。

這是合理題目，但前提是要先有**可信的歷史事件表**：

1. 哪一天公告納入 / 剔除
2. 哪一天正式生效
3. 哪些股票被納入
4. 哪些股票被剔除

沒有這個 event table，任何 event study 都是偽研究。

## 本次 hourly tick 的目標

依研究誠實原則，本輪先回答一個更基礎的問題：

> 用目前 repo 內資料 + 可即時公開取得資料，能不能誠實完成 0050 成分調整 event study？

## 檢查結果

### 1. repo 內已有 0050 價格資料，但沒有成分調整事件表

本地可找到：

- `storage/macro/yf_0050.TW.csv`
- 多份 `experiments/*/data/0050.TW.csv` / parquet

但找不到任何 canonical historical event table，例如：

- `0050 constituent changes`
- `FTSE TWSE Taiwan 50 review dates`
- `added / deleted names by review`

### 2. repo 內也沒有可直接 reuse 的 TWSE / FTSE 公告鏡像

沒有發現：

- 歷史 review 公告 PDF archive
- `納入 / 剔除` 結構化 csv/json
- 0050 成分調整對照表

### 3. 公網快速搜尋不足以在本輪建立可信事件表

本輪嘗試的公開來源方向包含：

- `TWSE`
- `FTSE Russell`
- `Yuanta 0050`

但沒有在短時間內得到足夠穩定、可程式化、可批量回溯的歷史事件資料。

因此若硬做 event study，只會落到：

- 手抄幾個新聞事件
- 或從二手網站拼湊名單
- 或自己猜測 review 日期

這都不符合研究誠實。

## Verdict

**BLOCKED_ON_DATA**

不是因為題目不好，而是因為：

1. event study 的最小可行輸入是歷史成分調整事件表
2. 目前 repo 內沒有
3. 本輪也沒有找到可立即自動化抓取的官方歷史來源

所以誠實完成方式不是硬跑回測，而是先把資料缺口記清楚。

## 若要真的做，所需 canonical input

至少需要一個 `csv/json`，欄位像：

- `announcement_date`
- `effective_date`
- `ticker`
- `event_type` (`add` / `delete`)
- `source_url`
- `source_title`

有了這張表，下一步才是：

1. 抓事件股與對照股價格
2. 定義 event window（例如 `[-20,+20]`, `[-60,+60]`）
3. 算 `abs_ret`, `park_var`, `idio_vol`
4. 做 add / delete 分組 event study 與 DiD

## 建議下一步

把這題拆成兩階段：

1. **資料建設任務**
   - 建 `0050_constituent_change_events.csv`
   - 來源需是 official FTSE/TWSE/Yuanta archive
2. **實證任務**
   - 事件表 ready 後再跑真正的 K-experiment

## 檔案

- `k1480.py`
- `k1480_results.json`

