# 稽核：2026-05-20~07-17 期間讀到「重複 snapshot」的實驗結果

**Task id**: `assign_7f508612`（P2, experiment, starved 70h）
**Model**: opus / xhigh (per model_router)
**Worktree（你的 cwd）**: `.claude/worktrees/dispatch-slot-2-dcc222db-snapaudit`（branch `snapaudit-dcc222db`）

## 背景（已確立的事實，不需要你重新推導）

`assign_09984c91` 修好 `refresh_paper_snapshots.py` 的並行 double-append 之後，發現污染範圍不只
K1685 指出的 1 檔：**6 篇 paper 共 9 個 live snapshot 全數在 2026-05-04..05-15 被重複 append 10 天**
（byte-identical，同一次事故）。

污染窗：git history 顯示 `3ea7dbb9d` (2026-05-04) 乾淨、`f1bdea2d1` (2026-05-20) 已有 dup，
到修復為止約 2 個月。期間任何讀這些 CSV 的 consumer 都會拿到序列中間多 10 天重複列 ——
對 rolling estimation / OOS split 而言**不只是多 10 筆，是 05-04 之後的整條時間軸位移**。

受影響檔（**現已修復**，surviving rows byte-identical）：

```
paper/garch-x-vix/data/{spy_vix_qqq_eem_fez_2000-2026,gld_vix_gvz_2000-2026,uso_vix_ovx_2005-2026}.csv
paper/leverage-direction/data/{spy_vix_2004-2026,spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026,vix_daily}.csv
paper/crypto-fear-channel/data/spy_btc_usd_vix_2015-2026.csv
paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv
paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv
```

## 要做的事

1. **盤點**：2026-05-20 後跑過、OOS 期間涵蓋 2026-05-04 之後、且**直接讀上列 CSV**
   （非自帶 pinned snapshot）的實驗 / paper results。
   已知讀檔者：`paper/garch-x-vix/reproduce.py`、`paper/garch-x-vix/scripts/summary_stats.py`、
   `experiments/{k1392,K1380_v4,k1393,K1394,k1489,k1662,k1585}`。
   **這份名單是起點不是終點** —— 自己 grep 這 9 個檔名，可能還有別的 consumer。

2. **逐一判定是否受影響**：多數 consumer 沒有 `drop_duplicates`，必須逐個確認讀取路徑與日期範圍，
   不能憑「應該有處理吧」推定。K1685 用自己的 pinned `data/k1685_spy_vix_snapshot.csv`，
   初判不受影響 —— **仍請覆核**。

3. **受影響者在修好的 snapshot 上重跑**，比對數字是否改變。有變動且已發表 / 在審 →
   在報告中明確標出，並說明該改哪些數字 / 哪一節。

4. **誠實記錄**：沒受影響的**也要寫明判定依據**（讀哪個檔、什麼日期範圍、為什麼不受影響），
   不要只列受影響的。null / 「全部不受影響」也是完整結果。

**禁止**：假設「反正只有 10 天、影響很小」就跳過重跑 —— 那是猜測不是驗證。
**禁止**：假數字。任何回報的數字都要能指回它的產出檔。

## 產出（success criterion）

寫出 `experiments/snapshot_dup_audit_20260720/audit_results.json`（相對 worktree root），結構：

```json
{
  "audited_at": "<ISO>",
  "contaminated_files": ["..."],
  "consumers": [
    {"path": "...", "reads": ["..."], "oos_covers_post_20260504": true,
     "dedups": false, "affected": true,
     "evidence": "<為什麼這樣判 —— 指到具體行號 / 日期範圍>",
     "rerun": {"done": true, "numbers_changed": true, "before": {...}, "after": {...}},
     "downstream": "<已發表 / 在審 / 內部；要改哪一節>"}
  ],
  "summary": {"n_consumers": 0, "n_affected": 0, "n_rerun": 0, "n_numbers_changed": 0}
}
```

同目錄另寫 `README.md` 用中文交代方法與結論（含「沒受影響者的判定依據」那一節）。

## 收尾規範

- **不要自己寫 `storage/memory/knowledge.json`**（K1259 gate）—— 交由收件的 followup task 處理。
- 重跑用的任何 heavy compute 若單段 >20 分鐘，拆段跑並在 README 記錄分段。
- 工作全部留在你的 worktree 內；不要 push、不要碰 canonical `storage/next_tasks.json`。
- 完成後最後一行輸出 `audit_results.json` 的絕對路徑與 summary 三個數字。
