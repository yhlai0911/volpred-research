
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

## Methodology 硬規則

### 套件限制 ≠ 模型無效
套件（arch, statsmodels, rugarch 等）在某些 spec 上收斂失敗 / 不支援時，**不可推論模型本身無效**。需自己寫 MLE（通常 scipy.optimize.minimize + analytic gradient）重估。套件 fail 常是 numerical/parameterization 問題，不是模型問題。**K1213 教訓**：用戶研究經驗多次遇到套件限制被誤讀為「模型失敗」。

### Pooled-MLE 必 100+ multistart
所有 pooled / cross-entity MLE（多資產共用參數、多國 panel 估計）必須跑 **≥100 個 random init** + LR test 選 basin + 檢查 log-likelihood 分佈。**K1213→K1216b/K1216c 教訓**：9/9 markets all fragile 時才發現 single-start artifact，fix 後參數 magnitude 變化 5-10x。

### 跨市場比較必 symmetric refinement
若 benchmark 用 canonical spec（e.g. DEV refined EM）、alternative 用 unrefined EM-only，得到的係數差是 **asymmetric artifact 不是真效應**。必須**兩邊同步 refine** 或**兩邊同 EM-only**。**K1216b ρ=-0.071 教訓**：asymmetric refinement 下 spurious 負相關；K1216c 全 refine 後 ρ=+0.379 與 canonical +0.441 indistinguishable（null）。
