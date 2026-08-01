# K1737 — Double-ML 因果 factor 檢定：價值／動能／品質是否有真正因果效應？

**Model**: opus / xhigh (per model_router)
**Task id**: `K1737`（pool status 已 in_progress）
**Worktree（唯一可寫路徑）**: `.claude/worktrees/dispatch-slot-1-9783132d-k1737`（branch `k1737-slot1-9783132d`）
**Result artifact（成功後置條件）**: `experiments/k1737/K1737_results.json`

## 研究問題

價值（低 book-to-market 對高 B/M）、動能（12-1M）、品質（ROE）這三個 factor，
**在控制高維 confounders 之後，是否仍有顯著的「因果」效應——還是只是預測性關聯？**

這題與我方既有的「純預測 factor ETF」題**目標不同**：那些題問「能不能預測」，
本題問**因果識別**。請在 README 明寫這個區隔，不要退化成又一個預測性 backtest。

來源：López de Prado / JFQA 2026 causal factor investing；FAJ 2025 causal ML 趨勢。

## 資料

- yfinance 美股**月度橫斷面**。
- 需要 book-to-market、ROE 等基本面欄位——**先誠實盤點 yfinance 能不能供給這些欄位、
  以及是否有 point-in-time 問題**（yfinance 的基本面多為當前快照，不是歷史 PIT）。
- ⚠️ **這是本題最大的效度風險**：用當前快照的 B/M、ROE 回推歷史橫斷面 = **look-ahead bias**。
  若無法取得 PIT 基本面，**必須明寫此限制**，並：
  (a) 改用可 PIT 化的代理（如動能純用價格，可乾淨計算），或
  (b) 把受污染的 factor 標為 `CONTAMINATED_NO_PIT` 並降級結論，
  **不可**當作乾淨結果報出來。動能（12-1M）可由價格算出、無此問題，是最乾淨的一支。

## 方法要求（硬規則）

1. **DoubleML / debiased ML 框架**（`doubleml` 或 `econml` 免費套件）。
   要有 cross-fitting（sample splitting），不要用同一份資料同時學 nuisance 與估 effect。
2. **明確寫出因果估計目標與識別假設**：treatment 是什麼、outcome 是什麼、
   confounders 是哪些、識別靠的是什麼假設（unconfoundedness？）。
   **識別假設站不住就明寫站不住**——這比硬給一個 ATE 有價值得多。
3. **高維 confounders**：控制變數要真的是高維（市值、產業、流動性、beta、過去波動等），
   否則 DML 沒有意義（低維直接回歸就好）。
4. **報告不確定性**：point estimate + 標準誤 + 信賴區間；三個 factor 一起檢定要做
   **FDR 或等價多重檢定校正**，pre/post 校正的結論都要寫進 results.json。
5. **與樸素基準對照**：同時報「naive OLS / 單純 factor return」與「DML 估計」，
   讓讀者看到控制 confounders 前後差多少——這個對照就是本題的主要產出。

## Workflow（per `.claude/rules/experiments.md`，開工前必讀該檔）

- **(a)** `experiments/k1737/README.md`：motivation + method + **lookahead policy**（本題必須特別
  處理 PIT 基本面問題）+ **success criteria**（在看到結果**之前**寫死，不可事後改）
- **(b)** `experiments/k1737/K1737.py`：任何 signal 必須 `signal.shift(1)` 或等價 lag；`seed=42`
- **(c)** `experiments/k1737/K1737_results.json`：byte-traceable outputs；**嚴禁手打數字**
- 跑 `uv run python scripts/check_experiment_artifacts.py check --path experiments/k1737`
- 寫 `experiments/k1737/test_k1737.py` 並跑過
- **Codex review 為 primary path**（quota 被擋才 fallback）

## 研究誠實（不可協商）

- **NULL result 完全可接受**。「控制 confounders 後 factor 效應消失」是本題最有價值的可能答案之一。
  **不要為了「有發現」而調 specification 直到顯著。**
- 若 PIT 資料問題讓因果宣稱站不住，**給 `CONDITIONAL_PASS` 或 `INSUFFICIENT_DATA`，不要硬給 PASS**。
- 嚴禁把 post-hoc 探索包裝成 pre-registered finding；嚴禁事後改 success criteria；嚴禁假數字。

## 禁止事項

- ❌ **不要寫 `storage/memory/knowledge.json`**（K1259：只有主線程能寫）
- ❌ 不要 `git push`、不要 `--no-verify`、不要 force push
- ❌ 不要寫到 worktree 以外的路徑
- ❌ 不要 spawn `claude -p` / `agy -p`

## 回報（return value，非給人看的訊息）

- verdict（PASS / CONDITIONAL_PASS / FAIL / NULL / INSUFFICIENT_DATA）與一句話理由
- 三個 factor 各自的 naive 估計 vs DML 估計（點估計 + CI），pre/post FDR 的顯著性
- PIT 基本面可得性的實際結論，以及哪些 factor 被標為 `CONTAMINATED_NO_PIT`
- 識別假設是否站得住的誠實判斷
- `check_experiment_artifacts.py` 與 `test_k1737.py` 的結果
- Codex review 的結論（或 fallback 的理由）
- 三件套的絕對路徑
