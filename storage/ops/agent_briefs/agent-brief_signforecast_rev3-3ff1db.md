# signforecast 方向可預測性 — round 3 bounded remediation（逐項修 Codex round 2 FAIL）

**Model**: opus / max (per model_router, escalation at ceiling — 這是 3-strike「拆解問題」分支，禁止原樣重派、禁止 force-merge)

## 背景
實驗 `experiments/direction_predictability_signforecast/`（worktree `dispatch-slot-2-7087efc0-signfc`）
Codex round 2 review 判 **FAIL**，凍結核對通過（非 freeze mismatch，是真 FAIL）。
完整 verdict：`storage/ops/codex_reviews/signforecast_rev1_verdict.md`。
**只准在此 worktree 內寫**：`experiments/direction_predictability_signforecast/` 及其 figures/。禁碰 feed.json / knowledge.json / 主線其他檔。

## 開工先讀
- verdict 全文（上路徑）
- 現有 `direction_predictability_signforecast.py` / `README.md` / `..._results.json`
- AGENTS.md「研究誠實原則」第 7、9、10、11 條（正式檢定、null 如實、不過度宣稱、lookahead）

## 三個 blocking defect —— 逐項修，每項要有可驗證產出

### Defect 1（code + rerun 必要）：GARCH no-silent-fallback 宣稱與實作不符
- 現況：`py 45` 全域關 warnings；不檢查 `arch` convergence flag；finiteness 檢查漏 `mu` 與 `resid_prev`；fallback 到 EWMA 時 `used_garch=False` 無 log（py 169、179–182）；NaN 特徵可能被 `dropna()`（py 239–240）靜默刪。
- 修法：
  1. 移除或收窄全域 `warnings` 關閉；改成每塊擷取 `arch` 的 convergence 狀態。
  2. finiteness 檢查補上 `mu`、`resid_prev`；任一非有限 → 記錄該資產/該塊 fallback 事件。
  3. 產出**逐資產／逐塊診斷**（convergence 成功率、fallback 次數、因 NaN 被 dropna 的列數），寫進 results.json 一個新 key（如 `garch_diagnostics`）。
  4. **重跑**產生帶診斷的 results.json（固定 seed；不得改動已驗證的 lag/shift 邏輯）。
- 驗收：results.json 有 `garch_diagnostics`；README 的 no-silent-fallback 宣稱要嘛被診斷數字支持，要嘛改寫成實況。

### Defect 2（純 README 改寫 + 由既有 results.json 重新點算）：DM 單尾 p 值誤讀
- 現況：README 把 DM 單尾 p 解讀為 8/8 模型「顯著較差」；實際僅 **6/8** 在反方向 5% 檢定顯著。
- 修法：從**現有** results.json 重新逐一點算每組 DM 統計量與單尾 p，訂正 README 為正確的 6/8，並明確標示是「反方向（模型較 benchmark 差）5% 顯著」。不需重跑。
- 驗收：README 的計數與 results.json 逐格一致；措辭精確到「哪個方向、哪個顯著水準」。

### Defect 3（純 README 改寫，收斂結論強度）：把 failure-to-reject 寫成「證實 NULL」/ 過度宣稱
- 現況：README 146/194 稱 multiple-correction 後不顯著＝「證實 NULL／證明假陽性」；「波動率明顯可預測」只有 OOS R²/QLIKE 點估、無 HAC DM/bootstrap 等正式檢定。圖標題 `variance is predictable OOS; sign is not` 也超出證據。
- 修法（不新增過度宣稱，改為誠實收斂）：
  1. 把「證實 NULL / 證明假陽性」改為「在本樣本、這兩類模型與這組特徵下，未找到穩健方向 edge；failure-to-reject 不等於證實不可預測」。
  2. 「波動率明顯可預測」限定為「本樣本 3/4 資產的 HAR 點估優於 expanding-mean benchmark；0050.TW 為負」，或補一個對 loss differential 的正式檢定（HAC DM 或 bootstrap，二選一，若做則固定 seed）。若不做正式檢定，就必須把措辭降到點估層級。
  3. 修正圖 `direction_vs_vol_predictability.png` 標題與 README 一致，不超出證據。
- 驗收：README 無「證實/證明」等超出 failure-to-reject 的字眼；每個保留的宣稱都能對應到 results.json 的數字或正式檢定。

## 收尾（agent 內完成到可交付；合併與 knowledge 由收件 fire 決定）
1. 重跑後更新 `review_verdict.json`（沿用格式；`reviewed_sha256` 換成新檔雜湊；verdict 先留 `PENDING_ROUND3`）。
2. README 補一段 `## Round 3 修訂紀錄`：逐條對應上面三個 defect 說明改了什麼、驗收證據在哪。
3. 產出 `experiments/direction_predictability_signforecast/direction_predictability_signforecast_results.json`（含 garch_diagnostics）為 result-artifact。
4. **不要自己 merge、不要寫 knowledge.json**（收件 fire 會派 Codex round 3 review，PASS 才 merge + 記 NULL）。
