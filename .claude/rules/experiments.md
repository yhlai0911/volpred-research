
---
paths:
  - "experiments/**/*"
  - "research_program.md"
  - "docs/error_log.md"
---

# Experiments / Research Rules

- 任何 `experiments/` 任務都要先讀 `docs/error_log.md`，再決定是否開跑。
- 每個實驗都必須落在 `experiments/<experiment_id>/`，包含 README、腳本、結果 JSON；圖表、references、data 視需要補上。
- 非純探索主題，先做 knowledge search + 文獻搜尋，再開始設計。
- Lookahead 是最高優先風險：
  - `signal from t-1, return at t`
  - 代碼裡要有明確 `signal.shift(1)` 或等效 lag
- 所有隨機程序都要固定 seed。
- 策略與風險管理比較遵守 `research_program.md` 的公平比較、VaR+ES、Harvey / Patton 規則。
- Worktree agent 只應產出 `experiments/kXXX/` 內檔案；共享 JSON、Supabase、Mirror sync 由主線程負責。
- 完成實驗後先做 Codex code review，再寫 knowledge / experience / article。
