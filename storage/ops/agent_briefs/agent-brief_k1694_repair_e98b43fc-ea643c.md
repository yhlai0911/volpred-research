# K1694 Codex round-1 FAIL 修復 + 重跑 + round-2 重審

**Model**: opus / xhigh (per model_router --task-type experiment)
**Task id**: `k1694_codex_fail_repair_20260729`（priority 2）
**Worktree**: `.claude/worktrees/dispatch-slot-1-e98b43fc-k1694`（branch `wt/dispatch-slot-1-e98b43fc-k1694`，開自 main 39830de18）

---

## 任務

Codex primary-path review round 1 對 K1694 回 **VERDICT: FAIL**。本任務 = 依 Codex 的「最低修復要求」修好、重跑、送 round 2 重審。

**這不是重新設計實驗。** 範圍就是 Codex 點名的缺陷，不要擴張。

## 開工前必讀（照這個順序，不要跳）

1. `storage/ops/codex_reviews/k1694_verdict.md` —— **裁決全文，這是缺陷清單的唯一 source of truth**。
   task 描述裡的 8 點是摘要，**以裁決原文為準**；兩者有出入時信裁決原文，並在 README 註明差異。
   （K1715 的教訓：轉述會漂移。不要照抄二手摘要就開工。）
2. `experiments/K1694/README.md` 的「Codex round 1 裁決」節
3. `storage/ops/codex_reviews/k1694_prompt.md` —— round 1 用的 prompt，round 2 沿用並補上「本輪修了什麼」
4. `.claude/rules/experiments.md`（尤其 §審查認證、Methodology 硬規則）
5. `.claude/rules/worktree.md`
6. `docs/error_log.md`（開工前必讀，AGENTS.md 硬規則）

## 修復範圍（摘要 — 細節以裁決原文為準）

1. **bootstrap 規格錯配（阻擋 PASS 的主因）**：bootstrap 必須與 spec1 共用**完全相同**的 design matrix / sample / 時間趨勢 t。現況 spec1 RHS 含 t（`K1694.py:472`）而 bootstrap 沒有（`K1694.py:521`）；主模型 3293 列 vs bootstrap 3300 列。
   **治本作法（要求採用）**：抽出單一 `build_spec_frame(panel)` 當估計樣本的唯一 owner，`panel_regression` 與 `bootstrap_interaction` 都吃它 —— 讓「兩邊一致」由**結構保證**，而不是靠人工對齊兩份清單。這是「永遠修流程，不修資料」在程式層的直接應用。
2. **`K1694.py:368` `highvol = (s > s.median()).astype(float)`**：rv 缺值時 `NaN > median` 回 False，highvol 被錯標成 0。要 mask 成 NaN。
3. **bootstrap 命名誠實性**：現行是 IID month-cluster（保留同月橫截面、破壞月間序列相關）。二選一：改成 consecutive moving / stationary block bootstrap，**或**誠實改名為 month-cluster bootstrap（README / results JSON / 檔頭**三處一起改**，不可只改一處）。
4. **排除 partial month**：2026-07 只有一週 DCOT、10 個交易日 RV、15 個商品。用**可重複的完整性規則**排除（**不要寫死日期**），並在 `results.sample` 揭露排除規則與被排除的月份。
5. **方法論描述對齊程式**：
   (a) `_acf_bandwidth()` 根本沒讀 resid（`K1694.py:421`），永遠回 `max(ceil(T**(1/3)), 4)` —— 規則可以留，但**不得宣稱**由 residual ACF 決定；
   (b) 檔頭 `K1694.py:36` 宣稱「另附全落後 predictive spec」而實際沒有 —— 要嘛補 spec，要嘛刪宣稱。
6. **results JSON 過度陳述**：`primary_interaction.bootstrap_ci95` / `bootstrap_interaction_spec1` **不得冒充 spec1 的 CI**；`panel_span` 要揭露 partial；`limitations` 補上 synthetic publication dates、月內 timing overlap、full-sample regime labels、bootstrap 不保留序列相關；timing 只能寫 **ex-post association**，**禁止** predictive / causal / known-before-outcome 用語。
7. **NULL 口徑**：只能寫「**負向 binary high-vol crowding-out 假說未獲支持**」。連續型 `fcm_x_rvz` 是**正向且顯著**（t_DK=2.50、month-cluster t=2.54），**不得**寫成「完全沒有關聯」。
8. **`reproduce_spec.json` 必須 run-time 產出**：用 `volpred.research.reproduce_spec.finalize_experiment()` 在腳本收尾時與 results 同一次 `trace_file()` 寫出。**禁止事後補寫**（K1708 教訓：事後補的 spec 描述的不是跑出結果的那份程式）。

## 執行注意

- `experiments/K1694/` 的 12 個檔（含 `data/` 快取 csv）**都已 tracked 在 HEAD**，worktree 直接看得到。
  （task 描述裡「目前在 canonical working tree 未 commit」那段**已過時** —— reap commits `84e9ff536` / `0f6c4e9eb` 已把它們收進 main，本班開工前已回讀確認。）
- **重跑優先走 `data/` 下的快取 csv**，避免不必要的 CFTC / yfinance 網路抓取。
- **lookahead 是最高風險**：訊號 `t-1`、報酬 `t`；程式裡要有明確 `.shift(1)` 或等效 lag；baseline 與新規格用同一套 lag 慣例。
- 隨機程序固定 seed。
- 結果好得不像真的 = 90% 有 bug，先懷疑再慶祝。

## 審查與收尾

1. 修完重跑，產出 `experiments/K1694/K1694_results.json` + run-time 的 `reproduce_spec.json`。
2. 送 **Codex round 2**：`scripts/codex_review_job.sh`，prompt 沿用 `storage/ops/codex_reviews/k1694_prompt.md` 並**補上本輪修了什麼**。
3. 裁決檔一律用 gate 產生，**不要手抄 schema**：
   ```
   uv run python scripts/experiment_gates.py verdict-template \
     --path experiments/K1694 --out experiments/K1694/review_verdict.json
   ```
   reviewer 只填 `verdict` / `reviewer` / `reviewed_at` / `reviewed_commit` / `review_artifact` / `blocking_defects`。
4. **審查回合的 commissioning prompt 與 raw transcript 不可留在 worktree 內未 commit**
   （`.claude/rules/experiments.md` §審查認證，2026-07-29 K1715 round-3 教訓：審查把自己的過程檔寫進被審樹，導致 read-back 時 `git status --porcelain` 非空而自我判死）。
   放 `storage/ops/codex_reviews/` 之類**被審樹之外**的位置，或在 read-back 前先 commit。
5. **round 2 PASS 之前不得寫 `knowledge.json`**（K1259 + 本任務前身的教訓）。knowledge 條目只能主線程寫；你負責產出 `*_results.json` 與裁決，主線程收件時再據以寫入。
6. 收工前 commit 到 worktree branch，並自查：
   ```
   python3 scripts/check_experiment_artifacts.py check --path experiments/K1694
   ```

## Scope 限制

- 只動 `experiments/K1694/` 內的檔（加上必要時 `storage/ops/codex_reviews/` 的 round-2 產物）。
- **禁止**修改共享狀態：`storage/reports/feed.json`、`storage/memory/knowledge.json`、
  `storage/memory/thinking_journal.json`、`storage/memory/experiment_experiences.json`、Supabase / Mirror sync。
- **禁止** `git worktree remove --force`、`--no-verify`、force push。
- 不要重新設計實驗、不要擴張到 Codex 沒點名的地方。

## 成功標準

- 8 項缺陷逐項有可驗證的修復證據（程式 diff + results JSON 欄位 + README 說明三者一致）。
- `K1694_results.json` 由修好的程式重跑產出；`reproduce_spec.json` 由 `finalize_experiment()` 在**同一次 run** 寫出，sha / byte size 與 results 的 `code_trace` 一致。
- Codex round 2 有明確裁決寫進 `experiments/K1694/review_verdict.json`。
- **若修完重跑結論仍是 NULL，如實報 NULL。null result 是結果，不是失敗** —— 不要為了拿 PASS 去調參數或改口徑。
