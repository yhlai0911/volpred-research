
---
paths:
  - "experiments/**/*"
  - "research_program.md"
  - "docs/error_log.md"
  # 2026-04-20 加：查 knowledge 即為「實驗前查相似 K」階段，規則此刻 load
  # 才能在設計實驗前提醒 lookahead / seed / 文獻先於主題 等防錯規則。
  - "storage/memory/knowledge.json"
  - "storage/memory/experiment_experiences.json"
---

# Experiments / Research Rules

- 任何 `experiments/` 任務都要先讀 `docs/error_log.md`，再決定是否開跑。
- 每個實驗都必須落在 `experiments/<experiment_id>/`，包含 README、腳本、結果 JSON；圖表、references、data 視需要補上。
- 非純探索主題，先做 knowledge search + 文獻搜尋，再開始設計。
- Lookahead 是最高優先風險：
  - `signal from t-1, return at t`
  - 代碼裡要有明確 `signal.shift(1)` 或等效 lag
  - Forward-label target（例如 `fwd_*`, 未來 H 日 RV/variance/return）不可只檢查 feature lag；OOS/expanding/rolling refit 的訓練列必須滿足 `target_end < forecast_origin`，等價於 row `j` 的 label window `j + H < i`，否則訓練尾端會看見預測日或之後的 realized return。
  - 多 horizon forward-label 實驗不可共用同一個 DM/HAC/HLN horizon；每個 target 的 inference horizon 必須等於該 target 的 H。
- 所有隨機程序都要固定 seed。
- 策略與風險管理比較遵守 `research_program.md` 的公平比較、VaR+ES、Harvey / Patton 規則。
- Worktree agent 只應產出 `experiments/kXXX/` 內檔案；共享 JSON、Supabase、Mirror sync 由主線程負責。
- 完成實驗後先做 Codex code review，再寫 knowledge / experience / article。
  - **Codex CLI 故障 diagnostic 順序**（2026-04-28 教訓寫入；2026-04-26/27 兩 entries 因順序錯誤花 4 天才修）。Codex error 時**先**這 5 步，不直接懷疑 plugin 版本：
    1. `codex --version` — 看 CLI binary 真正版本（**不**是 `~/.claude/plugins/cache/openai-codex/codex/<x>/` 目錄名，後者是 marketplace plugin 版號）
    2. `codex login status` — 確認 auth mode（ChatGPT account vs API key 接受不同 model whitelist）
    3. `cat ~/.codex/config.toml` 看 `model =` 欄位
    4. **暫時移除** `model = ` line → CLI auto-pick default（目前 0.121.0 default = `gpt-5.4`）→ smoke test `codex exec --skip-git-repo-check "echo TEST"`
    5. 若 default model PASS 就改回 config 鎖定（如 `model = "gpt-5.4"`）；若 default 仍 fail 才考慮 plugin 升級
  - **Fallback**：上述 diagnostic 全 fail 仍無法恢復 Codex 時，改派 `feature-dev:code-reviewer` subagent 做 independent fresh-context review（K1259 / K1261 / K1262 已走過此 path）。Knowledge entry 必註明 reviewer source（`Codex review` vs `code-reviewer subagent fallback`）。Bar 不變：CONDITIONAL PASS 以上才寫 knowledge.json。
  - **Codex 已於 2026-04-28 21:58 CST production-path 端到端驗證恢復**（`docs/error_log.md` RESOLVED entry；session `019dd462`，task `task-moioyr49-g0dg9v`）— primary path 是 Codex review，不是 fallback。
  - **Subagent fallback PASS ≠ primary-path Codex PASS**（2026-04-29 K1259 教訓）：subagent 走過 PASS-with-caveats 後若 Codex 恢復可用，**必須**用 primary-path Codex 二次驗證 — 不可只靠 subagent verdict 標 closure。K1259 案例：subagent v1 PASS 標「provenance-clean」，1 天後 Codex v2 在同份 code 找到 12 個 residual non-DM rows（`statistical_tests`/`stat_test`/`welch`/`vs_zero` patterns 全 keyed via `t_stat` 欄位，落在原 audit subset 之外）。Closure 才能立。
  - **Audit methodology hard rule**（2026-04-29 K1259 v2 教訓）：任何 ledger / dataset / output JSON 的 quality audit **必須 re-walk full population**，不可只 sample suspect subset。子集 audit 把 false negative 限在子集外的盲區（K1259 v1 只 audit `t`/`stat`-keyed rows，漏看 `t_stat` priority-5 keyed 的 12 residuals）。Audit doc 須明記：(a) 掃描範圍（全 population 或 subset criteria）、(b) blind-spot 分析（子集外有什麼可能漏掉）、(c) verification 方法（jq / hash / row-count invariant 等可驗證的 evidence）。
  - **K1259 process gate**（2026-05-17 T3）：`src/volpred/memory/system.py:_append_to_index` 現強制 enforce knowledge.json provenance — `verdict == "PASS"` 必須帶 `experiment_id`/`experiment_ids`/`k_id`/`experiment_path`(任一非空) **且** 帶 reviewer 欄位（`reviewer`/`reviewer_source`/`codex_review`/...任一非空）；`verdict == "CONDITIONAL_PASS"` 只需 provenance，不需 reviewer。NULL/FAIL/MIXED/無 verdict 不 gated。Validator: `src/volpred/memory/provenance.py`. CI invariant: `scripts/validate_knowledge_provenance.py`（baseline 284；超過代表有人用 jq/Edit 繞過 Python writer）。測試: `tests/test_knowledge_provenance.py`（19 tests）。手動 jq/Edit 不會被 Python validator 攔截 — 走 CI script 才會發現。

## Methodology 硬規則

### 套件限制 ≠ 模型無效
套件（arch, statsmodels, rugarch 等）在某些 spec 上收斂失敗 / 不支援時，**不可推論模型本身無效**。需自己寫 MLE（通常 scipy.optimize.minimize + analytic gradient）重估。套件 fail 常是 numerical/parameterization 問題，不是模型問題。**K1213 教訓**：用戶研究經驗多次遇到套件限制被誤讀為「模型失敗」。

### `arch` forecast alignment 必須 target 對齊
用 `arch` 做 one-step OOS loss evaluation 時，不可把 default origin-aligned `h.1` forecast 和 same-index realized variance / squared return 直接相比。必須用 `forecast(..., align='target')`，或明確把 origin-aligned forecast shift 到 target return date 後，才計算 QLIKE / MSE / DM tests。**K445 教訓**：same-index 比較 origin-aligned forecasts 會產生 lookahead / off-by-one 風險，不能支撐 production claim。

### Pooled-MLE 必 100+ multistart
所有 pooled / cross-entity MLE（多資產共用參數、多國 panel 估計）必須跑 **≥100 個 random init** + LR test 選 basin + 檢查 log-likelihood 分佈。**K1213→K1216b/K1216c 教訓**：9/9 markets all fragile 時才發現 single-start artifact，fix 後參數 magnitude 變化 5-10x。

### 跨資產 pooled inference 不可把 asset-day 當 iid
多資產 forecast / strategy 檢定若把同一日期的多個資產樣本串成 pooled array，**不得**直接把 stacked asset-day DM / t-test 當 primary publication claim。除非已明確實作並揭露 cluster-robust / panel HAC，否則預設做法是先按日期聚合 cross-asset loss differential，再對日期序列做 HAC / DM；stacked asset-day 結果只能放 diagnostic。**K1355 教訓**：同日跨資產 loss differential 有共同市場 shock，直接串接會低估標準誤並誇大顯著性。

### 跨市場比較必 symmetric refinement
若 benchmark 用 canonical spec（e.g. DEV refined EM）、alternative 用 unrefined EM-only，得到的係數差是 **asymmetric artifact 不是真效應**。必須**兩邊同步 refine** 或**兩邊同 EM-only**。**K1216b ρ=-0.071 教訓**：asymmetric refinement 下 spurious 負相關；K1216c 全 refine 後 ρ=+0.379 與 canonical +0.441 indistinguishable（null）。
