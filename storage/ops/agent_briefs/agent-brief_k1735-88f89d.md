# K1735 — 日內 diurnal pattern 是否「足夠」解釋 RV 變異？

**Model**: opus / xhigh (per model_router)
**Task id**: `K1735`（pool status 已 in_progress）
**Worktree（唯一可寫路徑）**: `.claude/worktrees/dispatch-slot-1-9783132d-k1735`（branch `k1735-slot1-9783132d`）
**Result artifact（成功後置條件）**: `experiments/k1735/K1735_results.json`

## 研究問題

日內（intraday）已實現波動率有眾所周知的 U 型季節：開盤與收盤活躍、午盤低落。
問題是——**剔除這個已知的日內 U 型季節之後，是否仍有顯著的 intraday vol 變異？**
換句話說：diurnal pattern 對 RV 變異的解釋力是否「足夠」（sufficient）？
並**量化季節成分佔 RV 的比例**。

來源：research_program.md line 628（arXiv 2601 diurnal sufficiency nonparametric assessment）。
這是**方法論基礎題**——結論會校準我方所有日內 RV 估計，優先於任何單一策略發現。

## 資料

- yfinance 或其他可得的 **5 分鐘**（或最細可得）intraday 代理。
- 先誠實盤點可得性：yfinance 的 intraday 歷史深度有限（通常 60 天內）。
  **若樣本深度不足以支撐結論，這件事本身就是要寫進 README 與 results.json 的發現**，
  不要用日資料硬湊成「日內」結果，也不要把短樣本的結果講得像長期定論。
- 標的建議：流動性最高的代表（如 SPY），必要時加 1-2 個對照。
- 記錄資料抓取的實際日期範圍、bar 數、缺漏處理方式。

## 方法要求（硬規則）

1. **無母數方法**為主（不要一上來就假設參數化 U 型函數）。
   典型作法：以 time-of-day bin 估計季節成分（如 nonparametric regression / bin means /
   kernel smoother），剔除後對殘差做顯著性檢定。
2. **量化季節佔比**：報告 diurnal 成分解釋的 RV 變異比例（如 R²-like 分解或 variance share），
   附信賴區間或 bootstrap 不確定性，不要只給一個點估計。
3. **剔除季節後的殘差檢定**：用無母數檢定判斷殘差是否仍有顯著 intraday 結構
   （避免只靠視覺判讀圖形就下結論）。
4. **多重檢定**：若跑多組 bin / 多個標的 / 多個 horizon，必須做 FDR 或等價校正，
   並在 results.json 記錄 pre/post 校正的結論。

## Workflow（per `.claude/rules/experiments.md`，開工前必讀該檔）

- **(a)** `experiments/k1735/README.md`：motivation + method + **lookahead policy** + **success criteria**
  （success criteria 要在看到結果**之前**寫死，不可事後配合結果改寫）
- **(b)** `experiments/k1735/K1735.py`：任何 signal 必須 `signal.shift(1)` 或等價 lag；`seed=42`
- **(c)** `experiments/k1735/K1735_results.json`：byte-traceable outputs，
  每個數字都要能追回計算來源；**嚴禁手打數字**
- 跑 `uv run python scripts/check_experiment_artifacts.py check --path experiments/k1735`
  （會確認 run-time 產生的 `reproduce_spec.json` 與三件套齊全）
- 寫 `experiments/k1735/test_k1735.py` 並跑過
- **Codex review 為 primary path**（quota 被擋才 fallback 到 subagent review 或 audit）；
  在 worktree 內執行是允許的

## 研究誠實（不可協商）

- **NULL result 是完全可接受的產出**。「剔除季節後沒有顯著剩餘變異」與
  「仍有顯著剩餘變異」兩個方向都是有價值的答案。**不要為了「有發現」而調參數直到 p<0.05。**
- 若樣本深度、資料品質或方法限制讓結論站不住，**明寫限制**，
  給 `CONDITIONAL_PASS` 或 `INSUFFICIENT_DATA` 而不是硬給 PASS。
- 嚴禁假數字、嚴禁事後改 success criteria、嚴禁把 post-hoc 探索包裝成 pre-registered finding。

## 禁止事項

- ❌ **不要寫 `storage/memory/knowledge.json`**（K1259：只有主線程能寫）
- ❌ 不要 `git push`、不要 `--no-verify`、不要 force push
- ❌ 不要寫到 worktree 以外的路徑（canonical root 由主線程管理）
- ❌ 不要 spawn `claude -p` / `agy -p`

## 回報（return value，非給人看的訊息）

- verdict（PASS / CONDITIONAL_PASS / FAIL / NULL / INSUFFICIENT_DATA）與一句話理由
- diurnal 成分佔 RV 變異的比例（點估計 + 不確定性區間）
- 剔除季節後殘差檢定的統計量與 p 值（pre/post FDR）
- 實際資料範圍、bar 數、標的
- `check_experiment_artifacts.py` 與 `test_k1735.py` 的結果
- Codex review 的結論（或 fallback 的理由）
- 三件套的絕對路徑
