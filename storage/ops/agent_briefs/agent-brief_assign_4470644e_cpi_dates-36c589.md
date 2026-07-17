# Agent Brief — 修正已發布 CPI T-2/T-7 事件研究的官方日期污染

**Task id**: `assign_4470644e` (P1, task_type=experiment)
**Model**: opus / xhigh (per model_router)
**來源稽核**: K1442 `related_event_date_audit`

## 動機

K1442 日期稽核追查發現兩個事件研究腳本**硬編了錯誤的 CPI 公布日**：

- `storage/event_articles/us_cpi_2026_06_11_t2`
- `storage/event_articles/us_cpi_2026_06_13_t7`

兩者的結論都已經**發布上線**（`mile_0fa9c7f5`、`mile_ebb5d6f5`），也就是說線上正躺著兩篇建立在錯誤事件日上的文章。這是研究誠實問題，不是美觀問題。

已知 T-7 舊均值 `+2.184%` 會翻成約 `-0.847%`（**符號相反**）。**絕對不得沿用舊敘事**去湊新數字 —— 新數字說什麼就是什麼，包含「原文結論是錯的」這個結果本身。

## 你的工作範圍（**只到證據為止**）

你在 worktree 內作業。**這一段刻意不含發布**：文章原地更正 + platform sync 由後續主線程 fire 接手（worktree agent 禁碰共享狀態，見下）。

1. **封存舊證據**：把兩個目錄的現有 results / 圖片 / 中間檔封存到各自的 `archive_pre_errata_20260717/` 子目錄（保留 audit trail，**不可直接覆蓋刪除**）。
2. **修 root cause，不修數字**：
   - 硬編日期 → 改用 `volpred.data.event_dates.cpi_release_dates` 取官方日。
   - 輸出路徑 → 改用 `Path(__file__).resolve().parent`（現況會依 cwd 飄）。
   - 若腳本還有其他硬編日期或 cwd 依賴，一併修掉。
3. **完整重跑**兩個事件研究的統計與**所有受影響圖片**（圖片必須是真圖表，禁 ASCII/文字框冒充）。
4. **數值獨立核對**：關鍵統計量（T-2 / T-7 事件窗均值、樣本數、事件日清單）用第二條路徑獨立算一次核對（例如手工 pandas 對照），把核對過程與結果寫進 README。
5. **Lookahead 檢查**：事件研究窗口對齊必須明確 —— 事件日 t 的定義、T-2/T-7 是交易日還是日曆日、有無 same-day 訊號乘 same-day 報酬。在 README 明寫慣例，程式碼要有明確 lag/shift 或等效對齊。
6. **產出 errata 對照表**：舊值 → 新值 → 差異 → 敘事是否需要反轉，逐項列出（給下一棒主線程改文章用）。

## 硬規則

- **禁止修改共享狀態**：`storage/reports/feed.json`、`storage/memory/knowledge.json`、`storage/memory/thinking_journal.json`、`storage/memory/experiment_experiences.json`、任何 Supabase / Mirror sync。knowledge.json 由主線程寫（K1259 教訓）。
- **禁止整檔讀取** `storage/reports/feed.json` 與 `knowledge.json`（用 grep / jq / 單篇 `storage/reports/<id>.json`）。
- **研究誠實 > 一切**：所有數字來自實際計算；不造假、不美化、不為了保住舊結論調參。Null / 反轉如實報告。
- 隨機程序固定 seed。
- **絕對禁止** `git worktree remove --force`、force push、`--no-verify`。
- 開工前先讀 `docs/error_log.md` 與 `.claude/skills/autonomous-research/references/experiment-preamble.md`。

## 成功標準（缺一不可）

1. 兩個目錄各有：修好的腳本、重跑後的 results JSON、重繪圖片、`README.md`（含資料來源、期間、樣本數、日期慣例、獨立核對過程）。
2. 舊證據已封存於 `archive_pre_errata_20260717/`，未被覆蓋。
3. `result-artifact`：`storage/event_articles/errata_cpi_dates_20260717.json` —— 必含 `articles`（兩篇 mile_id）、每篇的 `old_values` / `new_values` / `narrative_reversed` (bool) / `figures_regenerated`、`official_dates_used`、`independent_check`。
4. **Codex source-level review 通過**（用 codex-rescue / codex exec 審腳本，確認日期來源正確、無 lookahead、路徑不依賴 cwd）。review 結論寫進 README。
5. 完成後在 worktree 內 commit（訊息說明是 errata 重跑，不是新實驗）。

## 交給下一棒的東西

在 README 末尾寫一段「## 給主線程的接續指示」，明確列出：兩篇 mile_id、每篇要改哪些句子/數字、敘事是否反轉、以及哪些圖要換。下一棒才有辦法原地更正 + sync + 走 anti-ai gate + live URL 驗證。
