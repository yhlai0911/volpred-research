# K1623 rev3 — bounded claim-alignment remediation（Codex round 2 = FAIL）

**Model**: opus / max (per model_router --task-type experiment --attempt 2；`at_ceiling=true`)

**這不是「同法重派」**：Codex round 2 已逐行指出「文字宣稱超出／違反凍結證據」的具體位置與正確值。
本次任務是**照單修文字與凍結欄位**，不重跑任何 estimation、不改任何預測值、不重新設計方法。
若你發現任何一條 blocker 需要重跑 compute 才能修 → **停手**，把該條寫進 `blocked_items` 並在結果 JSON 說明，
不要自行 enqueue compute、不要自行改 estimation code。

## 工作目錄

`/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/experiments/k1623/`

**禁止合併 worktree**（verdict = FAIL，合併由後續 round 3 PASS 後才做）。
**禁止寫 knowledge.json**（K1259：agent 不得自寫，主線程負責）。

## 先讀

1. `/Users/yhlai0911/volpred-research/storage/ops/codex_reviews/k1623_rev2_verdict.md`（97 行，本任務的權威 spec）
2. worktree 內 `experiments/k1623/README.md`、`k1623_rev2_results.json`、`k1623_rev2_mc.py`、`k1623_rev2_mc_results.json`

## 必修的 4 個 BLOCKER（逐條，全部要修）

### B1 — TW0050 最大相對偏差寫錯（§2）
- README:95 / :106 / :319 三處寫 `2.51e-3`；權威值是 `k1623_rev2_results.json:31` 的
  `0.005259349489457132` ≈ `5.26e-3`。
- `k1623_rev2_results.json:54` 的**文字欄位**也硬寫成 `2.5e-3` → 一併改（這是 JSON 內的 prose 欄位，
  不是計算輸出；改文字不等於改數據，但務必確認你改的那個 key 確實是描述性字串）。
- 順手修 §2 末指出的 README:335「每一個 README 數字都可在 rev2 JSON 對上」— 這句為假
  （raw d / ACF / break 表在第一輪 JSON，MC 數字在 MC JSON）。改成誠實的三份 artifact 對應說明。

### B2 — HAR 冠軍宣稱過寬（§2）
- README:35 宣稱「QLIKE 下 HAR 是 5 資產冠軍或並列最佳」為假：JSON 全模型 winner 是
  VIX=`AR1`（:118）、N225=`ARFIMA`（:278），只有 3 資產是 HAR。
- 改成 Codex 給的較窄正確說法：**「HAR 對 ARFIMA 在 4/5 資產有較低 QLIKE」**，並確認全文沒有第二處
  重複同一過寬宣稱（grep `冠軍` / `並列最佳` / `winner`）。

### B3 — 「所有數字／預測值不變」對 TW0050 為假（§5）
- README:134「故所有數字不變」、README:327「`k1623.py` 未修改故所有預測值不變」— 兩句無限定，
  但 TW0050 已 n=4263→4264（歷史列修訂），同 code ≠ 同輸入 ≠ 同 forecasts。
- 改成有限定的說法（四資產不變、TW0050 因 vintage 列修訂而變動，並指向 `scope_and_limits`）。
- grep 全文找出所有 same-forecasts / 不變 類宣稱，一次修乾淨（round 2 的失分正是「撤回沒貫徹到全文」）。

### B4 — MC：source / README / frozen results 三方不一致 + attribution 錯（§7）
這條最重，拆成 4 個子項：
- (a) 凍結 `k1623_rev2_mc_results.json:159` / `:179` 仍把 `−0.085`～`−0.027` 的 Arm-A total bias
  **全歸因於重新估斷點**；現行 `k1623_rev2_mc.py:141` 已承認正確 contrast 是 **A−B**。
  凍結 artifact 與 source 必須一致 —— 若不重跑就無法產生正確欄位，**允許**在 JSON 內新增
  `superseded_claim` / `corrected_attribution` 明確標註舊欄位失效並給出 A−B 的正確區間
  （`−0.056`～`−0.020`，見 README:354），**但不得偷改原始數值欄位假裝一直是對的**。
- (b) README §6.4（:287）仍重複舊 attribution，而 §9（:354）已是新的 A−B → 兩段自相矛盾，統一到 A−B。
- (c) `k1623_rev2_mc_results.json:180` 宣稱 break **dates** 有 substantial uncertainty，但凍結 JSON
  只記 break **count**、沒有日期比較；`k1623_rev2_mc.py:237` 自己也承認該宣稱不受支撐 → 撤回該句。
- (d) Arm B 用 `piecewise_demean` 從模擬資料估各段均值（`k1623_rev2_mc.py:118`），因此**不是純
  「ELW alone」**，只 oracle 化了 break locations、未消除 mean-structure generated-regressor 不確定性。
  在 README 與 MC JSON 的 scope 段落據實描述 Arm B 的真實身分，勿再稱其為 ELW-only baseline。

### B5 — uniqueness 宣稱未被證成（§8）
- README:56 宣稱四點是「仍然獨有的貢獻」，但 README:66 自己說 §6.3 是既有 K1016 教訓的「又一個實例」，
  直接否定 (d) 的 uniqueness；(c) MC 只有 model-conditional 支撐。
- 依 Codex 的四點狀態評估重寫該段：(a)(b) 保留為有計算支撐的貢獻、(c) 降級為 model-conditional、
  (d) 改寫成「本資料提供 K1016 教訓的一個新實例」。
- **禁止**用 knowledge.json grep + README grep 去支撐一般性學術 uniqueness（Codex 已明指這不成立）。

## 同時修（MINOR，§3）
- 「五個 nested 集合」措辭不精確：QLIKE-20 與 MSE-20 互斥、pooled-40 是聯集、只有 focal-10 是各自
  within-loss-20 的子集。改成精確措辭（README:152 後文已有正確說明，是前文措辭問題）。

## 完成條件（機械可驗，不是自我宣告）

1. 上述 B1–B5 + MINOR 全部落地，且每一條在你的結果 JSON 裡有 `{blocker, files_changed, before, after}` 記錄。
2. 跑一次全文一致性自檢：對每個你改動的數字，grep 全 README 確認沒有殘留舊值（round 2 就是敗在殘留）。
3. **verdict template 必須重跑**：任何 claim-surface 檔案（README / results JSON）被改過，
   `experiments/k1623/review_verdict.json` 的 sha256 就失效 →
   用 `experiment_gates.py verdict-template` 機器重產，**禁手改 sha256**。
   verdict 欄位此輪仍填 FAIL/pending（round 3 審完才由主線程更新）。
4. 產出 `experiments/k1623/k1623_rev3_remediation.json`（本 job 的 result artifact），內容含：
   `blockers_fixed[]`、`blocked_items[]`（若有）、`files_changed[]`、`self_check`（第 2 點的 grep 結果）、
   `verdict_template_regenerated: true/false`。
5. **不要** merge worktree、**不要**寫 knowledge.json、**不要** enqueue 下一輪 Codex（由主線程收件時決定）。

## 誠實紅線
研究誠實 > 一切。任何一條你修不動、或修了會讓結論站不住的，**寫進 `blocked_items` 誠實回報**，
不要用模糊措辭把它糊過去 —— round 2 的 FAIL 正是「文字比證據走得遠」造成的。
