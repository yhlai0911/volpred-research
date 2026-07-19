# Task: 修正 CPI T+0 內部事件研究的官方日期污染（assign_a31a311d, P2, experiment）

**Model**: opus / xhigh (per model_router)
**Worktree (你唯一可寫的地方)**: `.claude/worktrees/dispatch-slot-1-858545f9-cpidates`
**禁止**: 寫 main checkout、force push、`--no-verify`、假數字、發布重複文章。

## 背景（K1442 related_event_date_audit）

`storage/event_articles/us_cpi_2026_06_11_t0/` 的**當次 2026-06-10 窗口是正確的**，但其歷史比較段落**硬編了 7 個錯誤日期與 1 個 phantom event**（根本沒發生的發布）。此文**從未發布**，所以沒有線上更正問題，但成果檔內的數字是錯的。

## 要做的事

1. 讀 `storage/event_articles/us_cpi_2026_06_11_t0/` 全部產出（analysis / evidence / article / details 各檔），定位硬編日期清單。
2. 改用 canonical 來源 `volpred.data.event_dates.cpi_release_dates`（不要自己再列日期；若該 API 缺欄位就補在 canonical module，不要 in-script hardcode）。
3. 輸出路徑改為 `Path(__file__).resolve().parent`（目前應為相對 cwd，會依執行位置漂移）。
4. **先封存舊證據**（例如 `_archive_20260719/`，保留可稽核），再重跑 analysis → evidence → article → details。
5. 重算後預期：**2026-06-10 的 VIX +11.827% 應是 13 場官方發布中的最大值**，不是舊文寫的第 4。這是 sanity check，不是要湊的目標 —— 若重算不是最大值，**據實記錄並說明為什麼**，不得反推調參。
6. 確認 `*.png` 兩張只含當次窗口的圖是否仍有效（只含當次窗口 → 不受歷史日期錯誤影響 → 可保留；請逐張驗證後說明判定依據）。
7. **補 regression tests**：至少一個測試，在「日期改回硬編清單」時會 FAIL（非空洞測試）。放 `tests/` 下依現有慣例命名。
8. 全套 test 綠：`uv run pytest -q`（若太慢，至少跑相關子集 + 說明）。

## 誠實要求

- phantom event 要明確點名是哪一場、為何判定不存在。
- 7 個錯誤日期逐一列「舊值 → 正確值 → 差異對結論的影響」。
- 若重跑後任何結論方向改變，據實寫，不要為了保住舊敘事修飾。

## 產出（成功後置條件）

寫 `storage/event_articles/us_cpi_2026_06_11_t0/k1442_cpi_date_fix_results.json`，至少含：
```json
{"task_id":"assign_a31a311d","dates_fixed":[{"old":"...","new":"...","note":"..."}],
 "phantom_event_removed":"...","vix_2026_06_10_pct":11.827,"rank_among_official":<int>,
 "png_kept":[...],"png_regenerated":[...],"tests_added":[...],"pytest":"pass|fail+說明",
 "conclusion_changes":"...","honest_notes":"..."}
```

## 收尾

- 在 worktree 內 commit（訊息寫清楚 what|why）。**不要自己 merge 回 main**，由後續 fire 的 PHASE A followup 走 `merge_worktree.sh`。
- 不要寫 `storage/knowledge.json`（K1259 規則：agent 禁寫）。把該記的寫進上面 JSON 與 commit message。
