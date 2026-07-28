# snapaudit_unmeasured_20260728 — 關閉 audit C 的兩類未測項目

**任務**：`snapaudit_quantify_unmeasured_exposure`（P3，餓死 159h）
**上游**：`experiments/audit_snapshot_dup_20260721/`（audit C，權威裁決集）與
`storage/ops/snapaudit_reconciliation_20260722.md` §4
**執行**：2026-07-28 hourly dispatch slot-1（job `4e1ceb1f`）

## 事件回顧

`scripts/refresh_paper_snapshots.py` 併發重複 append，使 9 個 canonical CSV 各含 **10 個重複交易日**
（2026-05-04 ~ 2026-05-15）。污染窗口 **2026-05-15 → 2026-07-17**；
last polluted = `d36a418cb`、fix = `00b07f07f`。

Audit C 關掉 9 個 consumer，但自陳兩類未關閉：

- **A/B 類**（`k1497 / k1498 / k1585 / k1380`）：讀 canonical CSV、無 dedup、窗口開放，
  但沒有 stored row count 可釘 vintage → 「暴露已確立、量級未測」。
- **C 類**（`k1308`）：判 `UNVERIFIABLE_MISSING_INPUT`，理由是它的 VIXTWN 比較檔路徑不存在。

## 方法

`quantify_unmeasured_exposure.py` **不重估任何模型**。它只做兩件可完全決定的事：

1. 把兩個 vintage 的 CSV 直接從 git 取出（`git show <rev>:<path>`，不動工作區），
   套上每個 consumer 的取樣窗口（窗口逐字取自 audit C 的 per-consumer evidence，
   本腳本不自行從原始碼重推），數出多少重複列進了樣本。
2. 對 k1308，重放它的 merge 算術並**釘住 vintage**。

> 這裡沒有預測、沒有訊號、沒有 lag —— 是對兩個 git vintage 的列數比對，不涉及 lookahead。
> 反過來說：**列級暴露只界定爆炸半徑，不等於統計量的變化**。後者仍需逐實驗重跑（見 §未竟）。

## 結果 1：A/B 類的量級（全部測到了）

每一個都是**恰好 10 筆重複列**進入樣本 —— 重複日期落在各自窗口內，且無一有 dedup：

| K-id | 樣本窗口 | polluted n | clean n | 多出 | 佔乾淨樣本 |
|---|---|---|---|---|---|
| k1497 | 2022-01-03 起，開放 | 1146 | 1136 | +10 | **0.88%** |
| k1498 | 無上界，至檔尾 | 6682 | 6672 | +10 | 0.15% |
| k1585 | 無日期過濾，至 2026-06-26 | 6672 | 6662 | +10 | 0.15% |
| k1380 | 日頻面板（17 specs + SPA） | 6682 | 6672 | +10 | 0.15% |
| k1391 | 至 2026-05-20 | 6645 | 6635 | +10 | 0.15% |

交叉驗證：clean vintage 下那 10 個日期各出現 **1** 次，polluted 下各 **2** 次（`n_dup_dated_rows_*`）——
與事件描述的「10 個重複交易日」逐一吻合。

k1391 另有 audit C 的 stored-count 主證（`n_full_oos` 1866 polluted / 1856 clean，同樣 +10）；
本表算的是 CSV 窗口列數而非 OOS 子集，兩者對「多出 10 列」的結論一致。

## 結果 2：k1308 —— 推翻 `UNVERIFIABLE_MISSING_INPUT`，改判 `CONTAMINATED_VERIFIED`

**輸入從來不缺**：

- `k1308.py:13-14` 是 **repo-relative** 解析（`ROOT = Path(__file__).parent.parent.parent`），
  不是硬寫的 `~/Desktop` 路徑。
- `data/vixtwn/vixtwn_daily.csv` 自 **2026-03-22（`b9c673cba`）** 起就在 git 裡，
  audit C 於 2026-07-21 執行時它就在 repo 內。檔案本身 156 列、**0 個重複日期**。

Audit C 讀的是 `k1308_results.json.data_sources` 記下的**絕對路徑**
（`/Users/yhlai0911/Desktop/volpred-research/...` —— 2026-05 執行當下 repo 的位置，之後 repo 搬了家），
發現該路徑不存在就結案。**這是判讀錯誤，不只是「後來才恢復」**：它信了一個 stale provenance 字串，
而不是原始碼實際解析的路徑；被引用的檔案在它告警的當下確實在 repo 內。

**釘 vintage**（k1308 stored：`run_date=2026-05-22`、`period=2025-12-01–2026-05-20`、`n=119`）：

| 取樣端點 2026-05-20 | n |
|---|---|
| polluted vintage | **119** ← 與 stored 完全相符 |
| clean vintage | 109 |

`run_date` 2026-05-22 落在污染窗口內（2026-05-15 → 2026-07-17），它打開的就是被污染的檔。
→ **10 筆重複列進了 119 列的樣本 = 佔乾淨樣本 9.17%**，是本次事件中**相對暴露最大**的一個
（其餘為 0.15%–0.88%），因為 k1308 的窗口最短。

其 `overall_stats`（mean 1.5737 / cv 0.204 / ci_95 [1.5154, 1.632]）與對 K1181 baseline 的比較
都建立在這 119 列上，需重算。

## 未竟（明確界線，非「做一半」）

**統計量本身的變化未測**。本單測到的是列級暴露；DM / SPA / GARCH 等報告數字要變多少，
必須逐實驗重跑。k1380 的 SPA bootstrap 昂貴、k1591 需連網抓 macro series ——
依任務指示「重跑走 compute_queue」，已另行入列，不在本 fire 內跑。

k1591 未列入上表：它讀的是 `leverage-direction` 那支 CSV 且 audit C 已有 stored-count 主證
（4091 polluted / 4081 clean，+10），本單不重複測。

## 檔案

- `quantify_unmeasured_exposure.py` — 量測腳本（seed 42；純列數比對）
- `quantify_unmeasured_exposure_results.json` — 結果
