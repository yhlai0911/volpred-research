# K1729 Codex 認證 → merge → 寫 knowledge

## 背景

實驗 **K1729**（自有 TAIFEX tick 5-min RV vs 純日頻資訊，對次日 TX 日盤 RV 的預測增益）已執行完成並**凍結**於 worktree：

```
/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-30aeb902-taifexrv
branch: wt/dispatch-slot-1-30aeb902-taifexrv
experiments/k1729/  (README.md, k1729.py, k1729_results.json, PLANNED_K_BRIEFS.md)
```

**主線程（hourly-slot-2-4f0198b9）已完成的驗證，不必重做**：

1. **數字已獨立重跑驗證**：`uv run python experiments/k1729/k1729.py` 重現 results.json，除 timestamp 外 **bit-identical**（seed=42）。handoff 宣稱的 4 個 headline 數字與 results.json 逐一對得上，無 K1016 式誇大。
2. **代碼已人工過目**：`har_features()` 有明確 `.shift(1)`；`rolling_oos()` 訓練窗 `[t-WINDOW, t)`；兩模型同 spec / 同 window / 同 filter / 同 common ledger；DM 用 canonical `volpred.stats.model_evaluation.dm_test`。**但這不等於 Codex 二審 —— 你的任務就是補上這道**。
3. **K 號撞號已修**：本實驗原誤標 K1719，與 7/16 已由 `kid_reserve.py` 正式預留給 ASIA-5 spillover 的 K1719 撞號。已經 `kid_reserve.py` 正式配得 **K1729** 並全面改號 + 重跑驗證。**不要再改號**。

## 為什麼還沒 merge

`merge_worktree.sh` 的 review-certification gate（2026-07-14 加，因 K1709 被 Codex 判 FAIL 卻仍 merge、害 CI 連紅 4 次）要求
`experiments/k1729/review_verdict.json` 存在且 **PASS**，且其 `reviewed_sha256` 必須 pin 住**現在這份 bytes** 的 claim surface。
上一班 fire 的 Codex 審查超過 10 分鐘仍未收斂，fire 有 3000s 硬上限 → 依規定改走 queue，由你完成。

## 你要做的事

### 1. Codex 審查凍結後的實驗（用 codex exec，boss 規則：review 走 codex 省 token）

審查目標 `experiments/k1729/`，**重點是研究誠實 gate，不是風格審**：

- **Lookahead bias（本專案最高風險）**：`har_features()` 的 `.shift(1)`、`rolling_oos()` 訓練窗是否真的只用 <= t-1 資訊？origin t 的訓練 pair (X,y) 是否都已知？有無 same-day 訊號乘 same-day target？
- **Baseline 公平性**：HAR_DAILY 與 HAR_RV5 是否同 lag 慣例 / 同 window / 同 refit cadence / 同 insanity filter / 同 common ledger？insanity filter 觸發率不同（7 vs 0）是模型行為還是代碼不對稱？
- **DM 檢定正確性**：HAC/Newey-West bandwidth、h=1、正負號慣例（negative t => HAR-RV5 better）；loss 是否為 per-day QLIKE loss 而非已平均值？
- **結論射程**：README 宣稱有無超過證據？特別是已知 caveat「日頻 baseline 的 day_return 仍由 tick 算出」有無誠實揭露、結論有無被誇大成「外部廉價日頻資料可替代 tick pipeline」？
- 有無造假 / 寫死數字 / results.json 與代碼不一致。

**PASS 門檻**：無 lookahead、baseline 公平、DM 正確、結論射程不超過證據。文字/風格建議不構成 FAIL。
審查全文寫到 `experiments/k1729/codex_review.md`。**禁止修改 README.md / k1729.py / k1729_results.json 任何 byte**（改了裁決就作廢，要重審）。

### 2. 寫 review_verdict.json

用 canonical 模板（**會自動 pin 好 sha256，不要手算**）：

```bash
uv run python scripts/experiment_gates.py verdict-template \
  --path .claude/worktrees/dispatch-slot-1-30aeb902-taifexrv/experiments/k1729
```

填 `verdict` (PASS/FAIL) / `reviewer`（真實模型名，**誠實填**，不是 Codex 就不要寫 Codex）/ `reviewed_at` / `reviewed_commit` / `review_artifact` (`codex_review.md`) / `blocking_defects`（PASS 時 `[]`）。
**若審完又動了 code → 重審，不要手改裁決檔。**

### 3. 依裁決分流

- **PASS** → `bash scripts/merge_worktree.sh dispatch-slot-1-30aeb902-taifexrv`（走正式腳本，禁裸 git；禁 `worktree remove --force`）。合併後照 `worktree-merge-verification` skill 確認檔案真的進 main（K1032 教訓：腳本報 no commits 但 reflog 有 commit，成果曾遺失）。
- **FAIL** → **不 merge**。把 blocking defects 寫成修復 task 進 next_tasks，worktree/branch 留著不要砍。

### 4. merge 成功才寫 knowledge.json（主線程寫，agent 禁寫 — K1259 教訓）

一條 K1729 entry，誠實記載：

- **結論**：自有 TAIFEX tick 的 5-min RV 對次日 TX 日盤 RV 的預測，顯著優於純日頻資訊 baseline，且跨兩個 noisy proxy target 穩健。
- **數字**（primary target `rv_5min`，OOS 2016-01-20~2026-07-16, n=2548）：QLIKE 0.190861 (HAR-RV5) vs 0.223748 (HAR-DAILY)，改善 14.70%，DM t=-3.681, p=0.00024，Harvey |t|>3 ✓。
- **穩健性**（secondary target `daily_r2`，偏袒 baseline 的 proxy，n=2536）：QLIKE 1.394991 vs 1.443710，改善 3.37%，DM t=-3.367, p=0.00077 ✓。
- **必記的 caveats（誠實原則，不可省）**：
  - 2017+ 子樣本的 `daily_r2` target |t|=2.92 **未過** Harvey 門檻 → 該格判 NULL（改善幅度與全樣本相同 3.37%，降的是 n 帶來的 power）。主結論以全樣本為準，**不升格**。
  - HAR-DAILY baseline 的 `day_return` 仍由 collector 從 tick 算出。其資訊集確為日頻可得，但**未從外部日頻 feed 端到端驗證** → 不等於證明外部廉價日頻資料可逐位元替代 tick pipeline。
  - 無中立第三方 proxy（canonical 5-min RV 層未存 session high/low；TWII 現貨是不同資產有 basis 問題）。兩個 target 都是 noisy proxy，都不是 latent integrated variance。
  - 本 K 只用 canonical 日頻層 `data/intraday/taifex_5min_rv.csv`（3,550 天），**完全未讀 35.9GB raw tick**。
  - 設計只含日盤（`rv_5min == rv_day` 恆真，程式內有 assert 把關），故 2017-05-16 夜盤斷點天然不進樣本。

### 5. 收尾

- work_log 記一筆（`actor`/`owner` 用你自己的 owner token）
- `uv run python scripts/task_pool_claim.py complete --id <本 task id> --status succeeded --result "<摘要>"`
- 不要自己 git add/commit canonical（PHASE-Z 會收）；worktree 內的 commit 照 merge_worktree.sh 正式流程走

## 已建好的後續 task（不要重複建）

- `assign_680433de` — K-B 夜盤 RV 條件價值（含 hard kill criterion：子樣本 n<100 直接判 infeasible）
- `assign_6b29e647` — 選擇權 tick 資料 blocker 解除（coverage manifest）
- `assign_762984a5` — 治本：experiment brief 未強制走 kid_reserve.py 導致撞號
