# K1709 — Codex 獨立審查（2026-07-14 12:23 台灣時間）

**審查者**: Codex CLI (gpt-5.6-sol, ultra reasoning) via `scripts/codex_exec_bounded.sh`
**受審對象**: `experiments/k1709/k1709.py` (worktree `dispatch-slot-2-c873d04d-k1709`, commit 9be94342d)
**結論**: **FAIL** — 兩個 CRITICAL 打掉招牌宣稱；不得寫入 knowledge.json，不得發文。

## Codex 的核心判決（原文）

> 可以接受：「在現有 expanding OOS 點估與診斷中，未發現 ETF flow 的穩健增量預測證據。」
>
> **不能**接受：「NULL 已成立」或「可排除每 1sd flow shock 帶來 ≥16% RV 效果」。

## 交叉驗證：專案自己的機械 gate 同意 Codex

`scripts/tests/test_nested_dm_misuse_ratchet.py::test_no_new_nested_raw_dm_sites` 對本檔 **FAIL**，
訊息與 Codex CRITICAL #1 完全一致（巢狀模型不得用 raw DM 承載 verdict；CW 只修正 MSPE，不能貼標成 QLIKE general-loss inference）。
K1709 重犯 2026-07-13 05:47 才修好的 K1701 教訓（見 docs/error_log.md）。

## 完整審查輸出

```

  它只檢查同一段程式人工 `.shift(pub_lag)` 出來的 `src_date`，無法證明各 predictor 的真實 provenance。我把同列 `y` 直接複製進 `z`，assert 仍通過；刪掉一個 Sunday 時，違規列也可能先被 `dropna(z)` 刪掉，h=5 的五列 rolling target 會跨成六個日曆日而 assert 仍通過。

  具體修法：在任何 rolling/shift 前檢查 index 完整、排序、無重複且等於完整 daily range；分開保存每組 predictor 的 source date；要求 `y_end_date == target_date + horizon - 1`；加入 future-mutation 與「刪 Sunday」測試。

實際主規格仍是乾淨的：rolling SD 在 [k1709.py:324–371](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c873d04d-k1709/experiments/k1709/k1709.py:324) 有 `.shift(1)`；forward target 在 [k1709.py:426–430](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c873d04d-k1709/experiments/k1709/k1709.py:426) 正確對應 `[τ, τ+h−1]`，沒有 target 混入 X。

### 2. 日曆對齊

- [MAJOR] 休市日 `Total=0.0` 被誤當成真實 flow day。[k1709.py:138–167](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c873d04d-k1709/experiments/k1709/k1709.py:138)

  現行 Farside 資料中，BTC 有 16 個、ETH 有 10 個美股非交易日被保留為零 flow，包括 MLK、Good Friday、Memorial Day、Juneteenth、Thanksgiving、Christmas。`sum(skipna=True)` 會把全為 dash/NaN 的基金欄加成 0，因此 parser cross-check 也抓不到；這些休市日還會進入「20 flow-day」rolling SD。

  修法：在標準化前用 US equity session calendar 過濾非交易日，休市列記為 missing；只保留交易日上的 genuine zero，並記錄 dropped dates/count，再完整重跑。我的 session-only 診斷未翻轉主結論，但統計量確實有位移，例如 BTC h=1 H1 的 DM 由 0.140 變 1.542。

- [MAJOR] `pub_lag=2` 穩健性把 HAR/return controls 也錯誤 lag 2。[k1709.py:415–424](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c873d04d-k1709/experiments/k1709/k1709.py:415)、[k1709.py:973–980](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c873d04d-k1709/experiments/k1709/k1709.py:973)

  若 flow_t 到 t+1 日終才可用並預測 t+2，則 `RV_{t+1}`、`ret_{t+1}` 已知；只有 flow 應 lag 2，state controls 仍應 lag 1。現行 robustness 使用過時 HAR baseline。

  修法：拆成 `state_lag=1`、`flow_lag=pub_lag`，並分別驗證 `state_src_date`、`flow_src_date`。

基準 `pub_lag=1` 的週五 flow 正確映到週六，沒有被當成週日 lag-1，也沒有 weekend forward-fill。

### 3. OOS

未發現全樣本 leakage。[k1709.py:527–584](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c873d04d-k1709/experiments/k1709/k1709.py:527) 每個 origin 都重新估 beta 與 training residual variance；h=5 嚴格要求 `y_end_date < forecast_origin`。沒有全樣本 scaler、參數或選變數。

另外，修改 cutoff 後的 RV/flow 不會改變 cutoff 前 forecast；26/26 tests 通過。

### 4. 統計推論

- [CRITICAL] QLIKE、raw DM 與 Clark-West 被混成同一個 NULL gate。[k1709.py:629–683](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c873d04d-k1709/experiments/k1709/k1709.py:629)、[k1709.py:1161–1215](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c873d04d-k1709/experiments/k1709/k1709.py:1161)

  DM 用的是 QLIKE loss；CW helper 實際計算 variance-level squared forecast errors。Clark-West 原始方法是 MSPE adjustment，不是 QLIKE general-loss test。[Clark–West 原文](https://www.nber.org/papers/t0326)

  因此 CW 公式與方向雖正確，卻只能標成 MSPE 證據，不能被稱為「QLIKE nested-correct」並單獨承載 NULL。這也直接重犯專案已記錄的 K1701 教訓：[error_log.md:511–536](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c873d04d-k1709/docs/error_log.md:511)。

  修法：使用共同 complete-case、共同 training dates 的 fixed rolling window，再對 Patton QLIKE 跑 Giacomini–White；raw expanding DM 降為 diagnostic-only。CW 可保留為另一个 MSPE estimand。

- [CRITICAL] 現行 MDE 不是功效分析，也不能推出「沒有 ≥16% 效果」。[k1709.py:693–768](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c873d04d-k1709/experiments/k1709/k1709.py:693)

  每個 β 只在同一條實際噪音路徑注入一次，再取第一個 crossing；沒有重複模擬、預設 80%/90% power、size 校準或 CI。結果還不單調：BTC CW 在 β=.15 時為 1.713，但 β=.8 時降回 1.623，[results.json:1948–2005](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c873d04d-k1709/experiments/k1709/k1709_results.json:1948)。所有 `detected_both` 也都是 false，和 docstring 宣稱的「BOTH gates」矛盾。

  此外 β=.15 的 BTC/ETH CW 單尾 p 約 0.043/0.031；光校正這兩格後 Holm p 就約 0.061，並未通過 5%。而 MDE 只算 H1、h=1，不能外推至 H2、h=5、H4。

  修法：若要正式 MDE，固定 seed，以 block/wild bootstrap 至少 1,000 次，每次完整重估 OOS path，按預先指定的整體 gate 計算 rejection rate。若要宣稱效果上界，必須另做預先指定 material margin 的一側 exclusion/equivalence test或反演信賴區間；power 本身不能證明效果小於 MDE。

- [MAJOR] 這不是 Harvey–Leybourne–Newbold modified DM。[model_evaluation.py:89–117](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c873d04d-k1709/src/volpred/stats/model_evaluation.py:89)

  現行只有 HAC-DM，再套 Harvey–Liu–Zhu 2016 的 `|t|>3` heuristic；沒有 HLN finite-sample factor。單尾 p 又在 [k1709.py:672–674](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c873d04d-k1709/experiments/k1709/k1709.py:672) 改用 normal CDF，與 helper 的 Student-t p 不一致。[HLN 原文](https://www.sciencedirect.com/science/article/pii/S0169207096007194)

  修法：實作 HLN modified-DM 並統一 p-value 分布，或誠實改名為「HAC-DM + t>3 gate」。本樣本 h=5 修正約 0.98–0.99，不會單獨翻轉結果。

- [MINOR] Holm 演算法本身正確，但 caller 使用已四捨五入至四位的 p，且所謂「EVERY DM test」漏掉 no/shared-smearing 的 8 個 DM tests。[k1709.py:773–781](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c873d04d-k1709/experiments/k1709/k1709.py:773)、[k1709.py:1097–1119](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c873d04d-k1709/experiments/k1709/k1709.py:1097)

  修法：保留 raw p 到最終 serialization，並由單一 test registry 產生完整 family。

### 5. NULL 誠實度

Flow 不是全零、全 NaN 或被 shift 掉：BTC/ETH 各有 642/504 筆，標準差約 342/146 百萬美元；面板 621/483 筆，OOS 371/233 筆。主 `verdict` 也確實由 OOS comparisons 而非 in-sample coefficient 產生。

但因上述正式推論錯誤，目前只能接受：

> 「在現有 expanding OOS 點估與診斷中，未發現 ETF flow 的穩健增量預測證據。」

不能接受：

> 「NULL 已成立」或「可排除每 1sd flow shock 帶來 ≥16% RV 效果」。

附帶地，[README.md:210–216](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c873d04d-k1709/experiments/k1709/README.md:210) 的 H3/H4 段落重複，第二組 H4 數字已過期，也應由結果檔重新生成。
```
