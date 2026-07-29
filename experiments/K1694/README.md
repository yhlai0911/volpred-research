# K1694 — FCM 清算集中度與商品流動性風險（**未完成，禁止引用結果**）

## 狀態：INCOMPLETE / SALVAGED

本目錄是從 stale worktree `dispatch-slot-1-f53bca44-k1694` 搶救回來的**半成品**。
**沒有任何結果產出**：無 `K1694_results.json`、無圖、無 Codex review、無 verdict。

任何人不得把本目錄的內容當作已完成實驗引用，也不得據此寫 feed 文章或論文段落。

## 搶救經過（2026-07-19）

- 2026-07-15 09:22 台北：`K1692_K1694_starvation_dispatch` 走 compute_queue 派出 K1692/K1694
  兩個 starved 實驗（各建 registered worktree）。
- K1692 的 agent job timeout，但結果後來被 salvage 進 canonical（commit `86255ebdc`）。
- **K1694 的 agent 沒有跑完**，只留下腳本與已抓好的資料，在 worktree 裡閒置 99 小時。
- task pool 中 `K1694` 的 status 是 `succeeded`，但 `result` 是 `null` —— 那個 succeeded
  指的是「**派工**成功」而非實驗成功。這是狀態語意陷阱，不是實驗已完成的證據。
- `storage/knowledge.json` 沒有 K1694 條目（未污染知識庫）。

## 已保住的東西

| 檔案 | 說明 |
|---|---|
| `K1694.py` | 完整分析腳本（32KB），未驗證是否可跑通 |
| `data/fcm_monthly.csv` | CFTC FCM customer-segregated assets 月頻（151 列） |
| `data/dcot_weekly.csv` | DCOT 週頻部位（23,057 列） |
| `data/rv_monthly.csv` | 已實現波動率月頻（5,644 列） |

資料是外部可重抓的，但重抓成本不低，故一併收進版控。

## 要完成它還缺什麼

1. 跑通 `K1694.py`，產出 `K1694_results.json` + 圖
2. 檢查 CFTC 發布日 lag 是否真的按**實際發布日**對齊（原始 brief 的核心設計，未驗證）
3. Codex primary-path review → `review_verdict.json`
4. 通過後才寫 knowledge entry

追蹤任務見 task pool（`worktree_harvest_wave2_dirty_stale_20260719` 的衍生任務）。
