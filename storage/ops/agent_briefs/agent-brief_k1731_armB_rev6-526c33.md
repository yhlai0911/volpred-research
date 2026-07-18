# K1731 arm B rev6 — Codex 一審 FAIL 的 bounded 修正

**Model**: opus / xhigh (per model_router)

**Worktree（唯一可寫範圍）**：`.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`
**禁止**：重跑整份 production MCMC、force-remove worktree、裸 `git merge`、改動任何已 freeze 的估計數字來讓檢查過關。

## 背景

rev5（ES estimator 由 per-draw 平均改為 posterior-mixture 閉式）已送 Codex 一審，**VERDICT: FAIL**。
完整報告：`storage/ops/codex_reviews/k1731_armB_rev5_verdict.md`（相對 canonical root）。

**已 PASS、不要動的部分**（避免你重工）：
- §1 ES estimator 推導與實作（1,120-case identity error 1.07e-14）— 正確
- §2 `conclusion_flipped: false` 的 ES-specific 宣稱 — 誠實
- §3 99% 案例措辭 — 無 absence-of-evidence 誤用
- §4 regression gate allow-list 完整性 — 本輪可接受
- §5 disclosed false-fail 解釋（57 leaves = 34+17+5+1）— 成立
- §6 provenance invariant（rev5 is_primary / rev4+original do_not_cite）— 正確

FAIL 落在 §7（stale prose）與 §8（claim–evidence 不匹配），共 7 條 blocking issues。

## 主線程已獨立複驗（不是轉述）

- README:169 與 README:665 寫 `3,776`，但 `k1731_regression_check_results.json` 的
  `n_leaf_values_compared` = **3834**。指控屬實。
- `k1731_es_mixture_check.py:200` 確為 `SEED + abs(hash(name)) % 10_000`。Python 的 `hash()`
  對 str 受 `PYTHONHASHSEED` 隨機化 → 宣稱的「固定種子」不成立，3.85–22.77% 區間不可重現。指控屬實。

其餘 5 條請你自行核對 bytes 後再改，**不要因為 Codex 說了就照抄**；若發現 Codex 判錯，
在 rev6 報告寫明理由並保留原文，這也是可接受的結案方式。

## 7 條 blocking issues

### B1（最重要，帶決策）nested-model DM 推論
`k1731_gevreg_midas_ssvs_returns.py:163` 建構 GEV-HAR 的方式是「關掉 macro block」→
SSVS vs GEV-HAR 是**嵌套比較**，但 `:382` 用的是一般 `dm_with_diagnostics` 跑未調整的
pinball-loss 差。HAC 只處理序列相關，**不移除 nested-model estimation bias**。
因此 README 標題與 §6 的 [-0.74%, 4.41%] 「bounded macro null」在本 repo 的既有規則下站不住。

**本輪指定路徑 = (b) 撤回宣稱**：把 raw DM 降級為 diagnostic-only，README 標題與 §6
撤下 "bounded null" 措辭，改寫成「在未針對嵌套估計偏誤校正的前提下，DM 診斷未顯示 macro
區塊有顯著增益；此為診斷而非正式界限」。
**不要**在本輪實作 recursive-bootstrap / nested-forecast 校正 —— 那是 heavy compute，
必須另走 compute_queue，本輪 timeout 塞不下，硬做只會做半套。
請在 rev6 報告的 `followup_needed` 欄位寫明「general-loss nested-forecast bootstrap 校正
以重建正式 bound」供主線程另立 task。
若你核對後認為 (b) 過度保守（例如比較其實非嚴格嵌套），可改走 (a) 但必須舉出 bytes 證據。

### B2 leaf count 不一致
README:169 與 README:665 的 `3,776` → 改為 **3,834**（以 gate JSON 為準）。
並延伸 traceability checker 覆蓋 gate/meta 數字 —— 目前它宣稱「zero mismatches」卻漏掉這兩處，
這個 checker 的覆蓋缺口本身就是 bug，修 checker 不只是修數字。

### B3 §3.7 引用被 supersede 的數字
README:343 用的是 original-run 全週 loss（0.1305/0.1433/0.1656），rev5 是
**GARCH 0.13325 / SSVS 0.14225 / Empirical 0.16559**。換掉，並讓該段唯一來源為 rev5 artifact。

### B4 §4 state lookup 敘述與實作矛盾
README:360 說 state lookup 解析到 origin day，但 rev5 的 `garch_origin_lag_trading_days=1`。
改寫為：自然 lookup 會落在 origin day，rev5 刻意回退一個交易日（並說明為何 —— lookahead 防護）。

### B5 §3 arm 差異宣稱過寬
README:93「any difference between the two arms is attributable to the target and nothing else」
與 README 自己記載的 macro set / GARCH 資訊集 / quick-vs-production 模式差異互相打臉。
限縮到：week keys、boundaries、origins、filter、HAR covariate construction；並**明列排除**
macro-set、GARCH-lag、estimation-mode 三項差異。

### B6 seed 不可重現
`k1731_es_mixture_check.py:200` 的 `abs(hash(name))` 換成固定 per-scenario seed 或穩定 digest
（例如 `int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "big")`）。
**重跑該 proof JSON**（這支是輕量檢查，不是 production MCMC，可在本輪內跑）。
README:294 把 3.85–22.77% 改述為「所建構情境的範圍」，**不是 worst-case bound**。
重跑後數字若變，以新數字為準並在報告寫明變動。

### B7 provenance 句與 review 輪次
README:541「Every file below」→ 收斂到三個 production artifact（`k1731_quickmode_results.json`
沒有 provenance 欄位，宣稱為假）。README:614 §10 的「Two Codex review rounds」→ 實際四輪，改正。

## 完成後必做

1. 重跑 regression gate，確認除了你**刻意**改的 README/檢查腳本外，**沒有任何估計數字漂移**。
   若有數字漂移 → 停下來寫進報告，不要自行合理化。
2. 產出 `experiments/k1731/k1731_armB_rev6.json`（= result artifact），至少含：
   - `verdict`: `ready_for_codex_review` | `needs_main_thread`
   - `blocking_issues_addressed`: 逐條 B1..B7 的 {id, action, evidence_path, bytes_changed}
   - `b1_decision`: 走 (a) 還是 (b) 及理由
   - `regression_check`: {n_leaf_values_compared, n_out_of_allowlist, drift_detected}
   - `es_mixture_recheck`: 重跑後的新區間數字（與舊值並列）
   - `followup_needed`: 陣列（至少含 nested-forecast bootstrap 校正）
   - `codex_claims_rejected`: 你核對後認為 Codex 判錯的條目（可為空陣列）
3. **不要**合併 worktree、**不要**寫 knowledge.json（K1259：agent 禁寫 knowledge）、
   **不要**改 next_tasks.json。這些由主線程在下一輪做。
4. commit 在 worktree branch 內即可。

## Sanity check

這是**修辭與宣稱層的修正 + 一支輕量檢查腳本重跑**，不是重新做實驗。
若你發現任何一條需要重跑 production MCMC 才能修 → 停下來，在 artifact 標
`verdict: needs_main_thread` 並說明，**不要**硬跑。誠實 > 通過。
