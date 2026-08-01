# K1738 — 財報盈餘驚喜（SUE）對次月 realized vol 的因果增量：DML + IV

**Model**: opus / xhigh (per model_router)
**Task id**: `K1738`（pool status 已 in_progress）
**Worktree（唯一可寫路徑）**: `.claude/worktrees/dispatch-slot-1-9783132d-k1738`（branch `k1738-slot1-9783132d`）
**Result artifact（成功後置條件）**: `experiments/k1738/K1738_results.json`

## 研究問題

估計 **earnings surprise（SUE）對後續 1-3 個月 realized volatility 的 ATE**
（average treatment effect），用 DML + instrumental variable 做識別。

不是問「SUE 能不能預測次月波動」（那是預測題，我方已有一批），
而是問**控制 confounders 後，SUE 是否有因果增量**。README 要明寫這個區隔。

來源：JFE 2025-26 event-driven causal inference；因果 ML 在盈餘波動的應用空白。

## 資料

- yfinance 美股**月度橫斷面** + **FRED 宏觀控制**。
- SUE = standardized unexpected earnings，需要 earnings 實際值與預期值。
  ⚠️ **先誠實盤點**：yfinance 的 earnings 資料（`earnings_dates` / `quarterly_earnings`）
  歷史深度與分析師預期覆蓋率都有限，且多為**當前快照非 point-in-time**。
  - 若拿不到歷史分析師預期，可用 **naive seasonal random walk 預期**（去年同季 EPS）當 SUE 定義，
    **但必須在 README 明寫這是代理定義、與文獻的 analyst-based SUE 不同**，不可混為一談。
  - 若覆蓋率低到無法支撐橫斷面推論，`INSUFFICIENT_DATA` 是正確結論。
- 記錄實際樣本：股票數、季別數、時間範圍、SUE 覆蓋率、缺漏處理。

## 方法要求（硬規則）

1. **明確寫出因果設定**：treatment = SUE（連續或離散化？寫清楚）、
   outcome = 後續 1/2/3 個月 realized vol、confounders = 哪些、
   **instrument = 什麼，以及為何滿足 relevance 與 exclusion restriction**。
   ⚠️ **exclusion restriction 是本題最脆弱的一環**。若找不到可信的 instrument，
   **明寫「無可信 IV」並退回純 DML（unconfoundedness 假設下）**，
   把結論降級為 conditional association 而非因果——**這比硬造一個爛 IV 誠實得多，也是可接受的產出**。
2. **DML 要有 cross-fitting**（sample splitting），nuisance 與 effect 不可同一份資料。
3. **明確 lag**：SUE 在 t 期公佈，outcome 必須是**公佈之後**的 realized vol。
   任何 signal 必須 `signal.shift(1)` 或等價 lag，且在 README 的 lookahead policy 寫死。
   ⚠️ 財報**公佈日**與**財季結束日**不同，用錯就是 look-ahead——這點要特別小心並在程式碼註明。
4. **多重檢定**：1/2/3 個月三個 horizon（若再乘上子樣本）須做 FDR 校正，
   pre/post 校正結論都要進 results.json。
5. **與樸素基準對照**：報「naive 迴歸」vs「DML」vs「IV（若有）」三者對照，
   讓讀者看到控制前後差多少——這個對照是主要產出。
6. **報不確定性**：point estimate + 標準誤 + CI，不要只給點估計。

## Workflow（per `.claude/rules/experiments.md`，開工前必讀該檔）

- **(a)** `experiments/k1738/README.md`：motivation + method + **lookahead policy**（須明確處理
  公佈日 vs 財季結束日、以及 SUE 定義的代理性）+ **success criteria**（看到結果**之前**寫死）
- **(b)** `experiments/k1738/K1738.py`：`signal.shift(1)` 或等價 lag；`seed=42`
- **(c)** `experiments/k1738/K1738_results.json`：byte-traceable；**嚴禁手打數字**
- 跑 `uv run python scripts/check_experiment_artifacts.py check --path experiments/k1738`
- 寫 `experiments/k1738/test_k1738.py` 並跑過
- **Codex review 為 primary path**（quota 被擋才 fallback）

## 研究誠實（不可協商）

- **NULL result 完全可接受**。「控制 confounders 後 SUE 的因果增量不顯著」是有價值的答案。
  **不要為了「有發現」而換 instrument / 調 specification 直到顯著。**
- IV 不可信就說不可信；資料不足就給 `INSUFFICIENT_DATA` 或 `CONDITIONAL_PASS`，**不要硬給 PASS**。
- 嚴禁把 post-hoc 探索包裝成 pre-registered finding；嚴禁事後改 success criteria；嚴禁假數字。

## 禁止事項

- ❌ **不要寫 `storage/memory/knowledge.json`**（K1259：只有主線程能寫）
- ❌ 不要 `git push`、不要 `--no-verify`、不要 force push
- ❌ 不要寫到 worktree 以外的路徑
- ❌ 不要 spawn `claude -p` / `agy -p`

## 回報（return value，非給人看的訊息）

- verdict（PASS / CONDITIONAL_PASS / FAIL / NULL / INSUFFICIENT_DATA）與一句話理由
- 三個 horizon 的 naive vs DML vs IV 估計（點估計 + CI），pre/post FDR 顯著性
- SUE 的實際定義（analyst-based 還是 seasonal-RW 代理）與覆蓋率
- instrument 是什麼、exclusion restriction 是否站得住的誠實判斷（或「無可信 IV，已退回純 DML」）
- 公佈日 vs 財季結束日的處理方式
- `check_experiment_artifacts.py` 與 `test_k1738.py` 的結果
- Codex review 的結論（或 fallback 的理由）
- 三件套的絕對路徑
