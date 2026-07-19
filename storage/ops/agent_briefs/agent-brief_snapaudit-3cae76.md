# Task: 稽核 2026-05-20~07-17 期間讀到重複 snapshot 的實驗結果（assign_7f508612, P2, experiment）

**Model**: opus / xhigh (per model_router)
**Worktree (你唯一可寫的地方)**: `.claude/worktrees/dispatch-slot-1-858545f9-snapaudit`
**禁止**: 寫 main checkout、force push、`--no-verify`、假數字。

## 背景

`refresh_paper_snapshots.py` 的並行 double-append bug（已由 assign_09984c91 修好）造成 **6 篇 paper 共 9 個 live snapshot 在 2026-05-04..05-15 被重複 append 10 天**（byte-identical 重複列，同一次事故）。

污染窗：`3ea7dbb9d` (2026-05-04) 乾淨 → `f1bdea2d1` (2026-05-20) 已有 dup，直到修復為止約 2 個月。

**關鍵**：對 rolling estimation / OOS split 而言，這不只是「多 10 筆」，而是 **2026-05-04 之後整條時間軸位移**。

受影響檔（現已修復，surviving rows byte-identical）：
```
paper/garch-x-vix/data/{spy_vix_qqq_eem_fez_2000-2026,gld_vix_gvz_2000-2026,uso_vix_ovx_2005-2026}.csv
paper/leverage-direction/data/{spy_vix_2004-2026,spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026,vix_daily}.csv
paper/crypto-fear-channel/data/spy_btc_usd_vix_2015-2026.csv
paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv
paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv
```

## 要做的事

1. **盤點**：找出 2026-05-20 之後跑過、OOS 期間涵蓋 2026-05-04 之後、且**直接讀上列 CSV**（而非自帶 pinned snapshot）的實驗 / paper results。
   已知讀檔者（起點，不是全集 —— 請自己 grep 確認有無遺漏）：
   `paper/garch-x-vix/reproduce.py`、`paper/garch-x-vix/scripts/summary_stats.py`、
   `experiments/{k1392,K1380_v4,k1393,K1394,k1489,k1662,k1585}`
2. **逐一判定是否受影響**：多數 consumer **沒有 drop_duplicates**，不能假設。要看實際讀取路徑與時間窗。
   `K1685` 用自己 pinned 的 `data/k1685_spy_vix_snapshot.csv`，初判不受影響 —— **仍請覆核**（確認它真的沒 fallback 到 live snapshot）。
3. **受影響者在修好的 snapshot 上重跑**，比對數字是否改變。有變動且已發表 / 在審 → 明確回報並列出需修正處。
4. **誠實記錄**：沒受影響的也要寫明判定依據（讀哪個檔、哪個時間窗、為何不受影響），不要只列受影響的。

## 硬性禁止

**不得**以「反正只有 10 天、影響很小」跳過重跑 —— 那是猜測不是驗證。若某個重跑成本過高（例如需 heavy MLE），**不要硬跑也不要跳過**：在產出 JSON 標 `status: "needs_compute_queue"` 並附精確重跑指令，由後續 fire 進 compute_queue。

## 產出（成功後置條件）

寫 `experiments/audit_dup_snapshot_20260719/audit_results.json`：
```json
{"task_id":"assign_7f508612",
 "consumers_scanned":[{"path":"...","reads":["<csv>"],"oos_covers_post_0504":true,
   "has_drop_duplicates":false,"verdict":"affected|unaffected|needs_compute_queue",
   "evidence":"為何這樣判定"}],
 "reruns":[{"consumer":"...","metric":"QLIKE|...","before":0.0,"after":0.0,"changed":true,
   "published_or_under_review":"...","action_required":"..."}],
 "needs_compute_queue":[{"consumer":"...","exact_command":"..."}],
 "honest_notes":"..."}
```
同目錄寫一份 `README.md` 敘述稽核方法與結論。

## 收尾

- worktree 內 commit（訊息 what|why）。**不要自己 merge 回 main**。
- **不要寫 `storage/knowledge.json`**（K1259）。
