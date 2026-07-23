# K1623 rev2 — primary-path review (round 2)

你是獨立二審。第一輪（2026-07-04）的 K1623 被你（codex/gpt-5.6-sol）判 **FAIL**：算術沒錯，
但 headline 宣稱超出證據。rev2 是針對那份 FAIL 的修復輪。請審**凍結後的 bytes**，不要建議「順便再跑一次」。

## 凍結位置（read-only）

`.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/`

claim surface：
- `k1623.py`（第一輪 forecasting code，**rev2 宣稱未改動**）
- `k1623_rev2.py`（rev2 主腳本：重跑 + MSE DM + HAC + 多重比較）
- `k1623_rev2_mc.py`（generated-regressor Monte Carlo）
- `k1623_rev2_results.json`（**權威數字**）
- `k1623_rev2_mc_results.json`
- `k1623_results.json`（第一輪，被 supersede 的是推論不是預測值）
- `README.md`（rev2 全面改寫，§0 是撤回總表）

## 必答問題（逐項給 verdict，不要只給總評）

1. **撤回是否真的撤乾淨**：README 全文（含 Verdict 行、§6、§7、圖表 caption）是否還殘留
   (a)「拒絕 Diebold-Inoue / 確有真 long memory」的識別宣稱、(b)「不可交易」、
   (c)「多處顯著更差」？只要有一處殘留就是 FAIL。
2. **數字對得上嗎**：README 每一個引用的統計量，是否都能在 `k1623_rev2_results.json` 找到同值？
   重點抽驗 `dm_comparisons[]`、`loss_function_sign_reversal[]`、`summary` 的計數
   （nominal_sig_05 / bh_sig_05_within_loss / bonferroni / focal_*）。counts 是否與明細一致？
3. **HAC 與多重比較是否正確實作**：`k1623_rev2.py` 是否真的呼叫 canonical
   `volpred.stats.model_evaluation.dm_test`（Newey-West，bandwidth ceil(n^(1/3))）而非自製版？
   BH / Bonferroni 的 family 定義是否**在 code 裡預先指定**（宣稱 primary family = within_loss_20）
   而不是事後挑對自己有利的那個？`inference_method.multiple_comparison` 自承是「五個 nested 集合」，
   這個揭露是否誠實且與 code 一致？
4. **loss reversal 的敘述強度**：headline 宣稱「排序隨 loss 反轉，但兩者統計上無法區分」。
   這是否過度銷售？MSE 的 ratio 11–16% 的下界（N225 = 0.8914 → 10.86%）與「11–16%」的寫法
   是否算 rounding 誤述？p 值範圍宣稱 [0.2654, 0.9744] 是否與明細一致？
5. **reproduction_guard 是否誠實**：宣稱 4 資產 aggregate loss 重現到 1e-9、TW0050 是
   near-replication（n 4263→4264）。`scope_and_limits` 自承「沒有 per-period forecast vector 可比」。
   這個限制陳述是否**足夠**？有沒有任何句子仍暗示「same forecasts」而對 TW0050 為偽？
6. **data vintage pin**：rev2 宣稱把 end date pin 回第一輪以免混淆「檢定修好了」與「樣本移動了」。
   code 是否真的 pin 住？pin 的實作有沒有 off-by-one 或只 pin 部分資產？
7. **Monte Carlo（`k1623_rev2_mc.py`）**：它宣稱量化 generated-regressor 不確定性。
   DGP 設定是否能支撐它被用來下的結論？有沒有把 MC 結果當成「識別問題已解決」來用？
8. **有沒有新的 overclaim**：rev2 新增的貢獻宣稱（§1「rev2 後仍然獨有的貢獻」四點）是否每一點都有
   對應計算支撐？「獨有」類的 uniqueness 宣稱是否被重新查證過？

## 輸出格式

第一行必須是下列其一：
`VERDICT: PASS` / `VERDICT: CONDITIONAL PASS` / `VERDICT: FAIL`

接著：
- 每個必答問題一段，標 `[OK]` / `[MINOR]` / `[BLOCKER]`，附檔案:行號證據。
- 若 CONDITIONAL PASS：列出**必須改的最小集合**（可逐條打勾的具體修改，不是泛泛建議）。
- 若 FAIL：明確指出哪一條宣稱仍然超出證據。

## 判準

- 只審「宣稱 vs 證據」與「推論方法正確性」。不要求補跑新實驗。
- 描述性陳述（descriptive）若已明確標為描述性，不算 overclaim。
- 這是修復輪：第一輪已撤回的東西不要再重複扣分，只檢查**撤乾淨了沒**與**新增部分對不對**。
