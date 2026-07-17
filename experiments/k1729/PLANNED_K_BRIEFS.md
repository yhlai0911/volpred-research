# TAIFEX intraday RV 題組 — 後續 K 的 brief

前置：`research_taifex_intraday_rv_line`（2026-07-17）。本檔記錄本班設計的題組，
K1729 已執行（見同目錄 README），另兩個 K 為可執行 brief。

## 為什麼題組與 dispatch brief 原案不同

Dispatch brief 給的三個候選是 (a) HAR-intraday vs daily HAR、(b) 夜盤/日盤 RV 分解、
(c) 選擇權 tick IV surface。**查重與資料查證後，(b) 與 (c) 都必須改**：

| 原案 | 查證結果 | 處置 |
|------|----------|------|
| (a) HAR-intraday vs daily HAR | 庫內無直接對照。K1704 用 daily proxies 當 **target**，非 regressor；K853 是 proxy ceiling；K1661 是 daily-OHLC HARQ。regressor 側的 intraday-vs-daily 增益是真 gap | **執行 → K1729** |
| (b) 夜盤/日盤 RV 分解 | **已被 K868 與 K884 各做過一次，兩次都 NULL**。K1301（semivariance）、K1303（jump CJ）、K1309（BMA）在 TX1 上同為 NULL，形成 "NULL quartet"，K1303 summary 明寫「Standard HAR-RV is near-sufficient」 | **不重做**。先驗太低且已有兩次 NULL；改為下方 K-B（換問法，非重測） |
| (c) 選擇權 tick IV surface | `OPTIONDATA` 只同步 1,024 / 13,093 檔（partial，README 實測） | **blocked on data**；改為下方 K-C（先解 blocker 才談研究） |

原案 (b) 的 dispatch 描述要求「處理 2017-05-16 夜盤斷點」。實測 `rv_5min == rv_day`
恆真（canonical 5-min RV 層只存日盤口徑），故 K1729 天然不含夜盤，斷點不進樣本 —— 這不是
迴避，是設計上讓 regime change 無從污染。

---

## K-B（brief）：夜盤資訊在 **限跌停鎖死日** 的條件價值

- **k_id**: 待配 — **執行前必須跑 `uv run python scripts/kid_reserve.py reserve --owner <你的 owner> --topic "<題目>"` 取號，不要自己掃 `experiments/` 挑號**（k1720 已被 LETF 尾盤題預留；本實驗原誤標的 K1719 也已屬 ASIA-5 spillover）
- **Research question**：K868/K884 測的是「無條件」加夜盤 regressor，兩次都 NULL。
  但無條件 NULL 不排除**條件**有用。K1729 的排除審計發現 2025-04-07 / 04-10 兩天日盤
  RV = 0（漲跌停鎖死，open == close，292–481 ticks vs 常態 ~30k），隔日跳空 >2%。
  日盤 RV 在這些日子**結構性失去資訊**（價格被行政上下限凍結），而夜盤此時仍在交易 →
  夜盤 RV 應該是唯一還在動的訊號。問題：在日盤 RV 退化的子集合上，夜盤 RV 是否恢復預測力？
- **H0**：在 limit-lock / near-limit 子樣本上，`E[QLIKE(HAR-RV5 + night)] - E[QLIKE(HAR-RV5)] = 0`
  （夜盤 regressor 即使在日盤資訊退化時也無增量）。
- **與 K868/K884 的差異化**：那兩個 K 測無條件平均效果；本 K 測**條件效果**，
  且條件是由 K1729 的資料審計發現的、有明確經濟機制（漲跌停 = 日盤訊號被截斷）的子集合。
  這是換問題，不是重測同一問題。**若無法先證明子樣本夠大，本 K 不該啟動**（見成本）。
- **資料切法**：`data/intraday/taifex_5min_rv.csv` 的 `rv_night` / `has_night`。
  夜盤僅 2017-05-16 起存在（2,228 / 3,550 天），故樣本硬性限縮
  2017-05-16 → 2026-07-16，**不可與 2012–2017 pool**。
  子樣本定義須**事前**寫死（如 `rv_5min` 落在全樣本最低 1 個百分位，或 `day_return == 0`），
  不得事後挑期間。
- **Baseline**：HAR-RV5（K1729 的同一支，同 window / 同 filter / 同 ledger）。
- **指標**：QLIKE + canonical `dm_test`（HAC）；Harvey |t| > 3。
- **預期成本**：~30 min compute（同 pipeline）。
- **⚠ 先驗警告與 kill criterion**：全樣本只有 2 天 `day_return == 0` 且在 2017 之後。
  即使放寬到「最低 1 百分位 RV」也僅 ~22 天可用 → **n 太小，幾乎注定
  UNTRUSTWORTHY_SMALL_SAMPLE**（K1301 的 SPY leg 就因 n_test=3 被判不可信）。
  **啟動前必須先跑一支純計數的 power check**：若事前定義的子樣本 n < 100，
  直接記為 infeasible-on-current-sample 並關閉，不要跑完再用 n 小當結論。
  誠實地說，這個 K 最可能的結局是「資料不足以檢定」，而非 PASS/NULL。

## K-C（brief）：選擇權 tick 的資料 blocker 解除（**前置工程，非研究**）

- **k_id**: 不配 K（這是資料工程任務，不是實驗）
- **問題**：dispatch 原案 (c) 要做 IV surface 微結構訊號，但 `OPTIONDATA` 只同步
  1,024 / 13,093 檔（~41 GB 已下載，其餘為 Dropbox cloud-only placeholder）。
  **在資料補齊前，任何 IV surface 實驗都會落在不具代表性的片段上** → 不該啟動。
- **H0**：不適用（無假說；這是 blocker 解除）。
- **交付**：(1) 清點 `OPTIONDATA` 實際可用日期集合與 strike/maturity 覆蓋；
  (2) 判定缺口是 cloud placeholder（可拉）還是根本沒有（不可補）；
  (3) 若可拉，走 compute_queue enqueue 下載 + 轉 canonical，**不在互動 turn 硬幹**；
  (4) 產出 coverage manifest，供後續 IV 實驗判斷樣本是否足夠。
- **預期成本**：清點 ~20 min；若要全量拉取 ~41 GB+ → 必須走 compute queue，數小時。
- **理由**：與其設計一個資料不足的實驗，不如誠實把它標成 blocked 並先解 blocker。
  這條線的價值取決於 K1729 的結果 —— **若 K1729 顯示 intraday 對日頻預測無增益，
  投資選擇權 tick 這條更貴的線之前應先要求更強的事前理由**（見 K1729 README §7）。
