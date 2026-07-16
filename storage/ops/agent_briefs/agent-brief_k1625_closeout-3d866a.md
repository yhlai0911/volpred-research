# Task: 收尾孤兒實驗 k1625（寫入 knowledge.json）

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Task ID**: dreaming_orphaned_experiment_k1625
**Owner token**: hourly-slot-1-215e3e27ac5b46b78a013cb996257633

## 背景

`experiments/k1625/` 已有完整結果但**沒有任何 consumer**（knowledge.json / feed.json / paper / open task 都找不到 'k1625'）。
dreaming 巡檢在 2026-07-12 首次偵測（結果產出於 8.4 天前），已餓死 85.1h（P3 門檻 72h）。本任務目的：把結果正式收進機構記憶，讓它不再是孤兒。

## 你要做的事（依序）

1. **讀結果**：`experiments/k1625/k1625_results.json` + `experiments/k1625/README.md` + `experiments/k1625/k1625.py`（確認方法、樣本、lag 處理）。
   - 特別檢查：signal 有沒有 `.shift(1)`？baseline 用同樣 lag 嗎？結果好得不像真的 = 90% 有 bug。
2. **讀既有 Codex review**：`experiments/k1625/codex_review.md` 已存在。
   - 若其 verdict ≥ CONDITIONAL PASS → 可直接引用為 reviewer provenance。
   - 若 verdict 是 FAIL / REJECT / 不存在明確 verdict → **重跑一次 Codex review**（用 codex-cli skill 或 `codex exec`），把新 review 追加到同檔並記錄日期。
   - **CONDITIONAL PASS 以上才可寫 knowledge.json**。未達標 → 不要硬寫，改在 README.md 記錄「review 未通過，結論不採信」並在最終回報說明。
3. **寫 knowledge.json**（canonical: `/Users/yhlai0911/volpred-research/storage/knowledge.json`，用既有 helper script 或 append 相同 schema，**不要手改成不合法 JSON**）：
   - 必含 `experiment_id`（k1625）、reviewer provenance（哪個 model / 哪份 review / verdict / 日期）、方法摘要、樣本期間、主要數字（照抄 results.json，**禁止四捨五入成漂亮數字、禁止編造**）。
   - **Null result 照實寫 — null 也是結果。** 不要把不顯著寫成「有趨勢」。
4. **判斷可發佈性**：若結論夠強且對讀者有價值 → 在 `storage/next_tasks.json` 新增一筆 `daily_article` task（description 註明 source k1625），**不要自己寫文章**。若是 null/太技術 → 不排文章，直接說明理由。
5. **work_log**：在 `storage/work_log.json` append 一筆，`actor` 與 `owner` 欄位**逐字**填 `hourly-slot-1-215e3e27ac5b46b78a013cb996257633`。

## 硬規則

- 研究誠實 > 一切。假數字 = 最嚴重違規。
- 禁止 force push / `--no-verify`。
- 不要跑新的 heavy compute；這是收尾任務，只讀既有結果。
- 完成後回報：verdict、寫了哪些檔、knowledge entry id、有無排文章 task。

## 回報格式（你的 final text = 回傳值）

```
k1625 closeout:
- review verdict: <...>
- knowledge entry: <id or "not written: reason">
- article task: <task_id or "none: reason">
- files touched: <list>
```
- files touched: <list>
```

## Worktree 規範

你在 registered linked worktree `.claude/worktrees/dispatch-slot-1-215e3e27-k1625`（branch 同名）工作。
所有編輯在此 worktree 內完成並 commit 到該 branch。**不要**自己跑 `merge_worktree.sh`、不要碰 main —
合併由後續 followup 統一走正式 `scripts/merge_worktree.sh` 處理。
