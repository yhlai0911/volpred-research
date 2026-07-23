# 任務：稽核 2026-05-20~07-17 期間讀到重複 snapshot 的實驗結果（task `assign_7f508612`）

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Worktree**: `.claude/worktrees/dispatch-slot-1-20b291d5-snapdup`（branch `wt/dispatch-slot-1-20b291d5-snapdup`）
**Parent task**: `assign_09984c91`

## 開工前必讀

1. `AGENTS.md`（研究誠實原則 13 條、worktree 規則、實驗 artifact gate）
2. `docs/error_log.md` 中 2026-07-17 前後關於 `refresh_paper_snapshots.py` double-append 的條目
3. `.claude/skills/autonomous-research/references/experiment-preamble.md`

## 背景（事故本體）

`assign_09984c91` 修好 `refresh_paper_snapshots.py` 的並行 double-append 之後，發現污染範圍不只 K1685
指出的 1 檔 —— **6 篇 paper 共 9 個 live snapshot 全數在 2026-05-04..05-15 被重複 append 10 天**
（byte-identical，同一次事故）。

污染窗：git history 顯示 `3ea7dbb9d` (2026-05-04) 乾淨、`f1bdea2d1` (2026-05-20) 已有 dup，
到修復為止約 2 個月。期間任何讀這些 CSV 的 consumer 都會拿到序列中間多 10 天重複列 ——
**對 rolling estimation / OOS split 而言不只是多 10 筆，是 2026-05-04 之後的整條時間軸位移**。

受影響檔（現已修復；surviving rows byte-identical）：

```
paper/garch-x-vix/data/{spy_vix_qqq_eem_fez_2000-2026,gld_vix_gvz_2000-2026,uso_vix_ovx_2005-2026}.csv
paper/leverage-direction/data/{spy_vix_2004-2026,spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026,vix_daily}.csv
paper/crypto-fear-channel/data/spy_btc_usd_vix_2015-2026.csv
paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv
paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv
```

## 要做的事

1. **盤點 consumer**：找出 2026-05-20 後跑過、OOS 期間涵蓋 2026-05-04 之後、且**直接讀上列 CSV**
   （非自帶 pinned snapshot）的實驗 / paper results。已知讀檔者：
   `paper/garch-x-vix/reproduce.py`、`paper/garch-x-vix/scripts/summary_stats.py`、
   `experiments/{k1392,K1380_v4,k1393,K1394,k1489,k1662,k1585}`。
   **這是已知清單不是完整清單** —— 自行 grep 上列檔名找出所有 reader，補進盤點表。
2. **逐一判定是否受影響**：多數 consumer 沒有 `drop_duplicates`，需要真的看程式碼確認，不可推測。
   K1685 用自己的 pinned `data/k1685_spy_vix_snapshot.csv`，初判不受影響 —— **仍請覆核**。
3. **受影響者在修好的 snapshot 上重跑**，比對數字是否改變。有變動且已發表 / 在審 → 明確回報並列出
   需要修正的 artifact（文章 mile_id / paper section / knowledge K-id）。
4. **誠實記錄**：沒受影響的也要寫明**判定依據**（哪一行程式碼、哪個日期切點），不要只列受影響的。

## 硬性禁止

- ❌ 假設「反正只有 10 天、影響很小」就跳過重跑 —— 那是猜測不是驗證（原 task description 明列）。
- ❌ 修改共享狀態：`storage/reports/feed.json`、`storage/memory/knowledge.json` /
  `thinking_journal.json` / `experiment_experiences.json`、Supabase / Mirror sync。
  knowledge 條目**只能主線程寫**（K1259）。
- ❌ `git worktree remove --force`。
- ❌ 為了讓結論好看而挑資料期間。Null result（「全部都沒受影響」）如果是真的，就如實寫。

## 產出（success criterion）

在 worktree 內產生 **`experiments/audit_snapshot_dup_20260721/`**：

- `README.md` — 事故摘要、盤點方法、逐 consumer 判定表（consumer / 讀哪個 CSV / 有無 drop_duplicates /
  OOS 期間 / 判定 / 依據）、重跑結果對照、需修正 artifact 清單、局限。
- `audit_snapshot_dup_20260721.py` — 可重跑的盤點 + 重跑腳本（固定 seed）。
- `audit_snapshot_dup_20260721_results.json` — **這是 result artifact**，必須含：
  `consumers[]`（每筆有 `path`、`reads`、`has_dedup`、`oos_covers_may2026`、`verdict`、`evidence`）、
  `reran[]`（每筆有 `before`、`after`、`delta`、`materially_changed`）、
  `artifacts_needing_correction[]`、`summary`。
- `reproduce_spec.json`（artifact gate 要求）。

開工前自查：`python3 scripts/check_experiment_artifacts.py check --path experiments/audit_snapshot_dup_20260721`

## 收尾

- 在 worktree 內 commit（**不要 merge，主線程負責**）。
- 最終回覆用純資料摘要：受影響 consumer 數 / 重跑後數字有變的數 / 需修正 artifact 清單。
  不要寫給人看的客套話。
