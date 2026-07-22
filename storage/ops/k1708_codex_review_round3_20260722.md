# K1708 Codex primary-path re-review (round 3) — 2026-07-22

- **Reviewer**: `codex exec` v0.144.6 (read-only, bounded 1500s, via `scripts/codex_exec_bounded.sh --timeout 1500 -s read-only -`)
- **Subject**: worktree `dispatch-slot-1-457427c2-k1708`, branch `wt/dispatch-slot-2-8dda242d-k1708`, commit `01efab8c8` (post round-2 remediation)
- **Prior rounds**: `k1708_codex_review_20260717.md` (FAIL, 3 BLOCKERs) → `k1708_codex_review_round2_20260719.md` (FAIL, 4 BLOCKERs)
- **This round**: **VERDICT: FAIL** — worktree NOT merged, no `review_verdict.json` written, no `knowledge.json` write.
- **Wall clock**: 2026-07-22 08:17:56 → 08:27:31 台北 (575s). Tokens used: 172,987.
- **Full raw transcript** (streaming + tool calls + final message, 6347 lines): `k1708_codex_review_round3_20260722.raw.log`

**Correction carried into this round**: `REMEDIATION_rev2.md` claimed Codex quota was exhausted until
2026-07-25 13:30 台北 and that this was why round-2 was never independently reviewed. That claim was
disproved by measurement at 2026-07-22 08:15 台北 (`codex_exec_bounded.sh --timeout 100 "reply with
exactly: QUOTA_OK"` → `QUOTA_OK`, exit 0, 11,432 tokens). The false premise has been annotated in place
in `REMEDIATION_rev2.md` (original text preserved, not deleted).

**Main-thread independent verification of the two surviving blockers** (not taken on Codex's word):
- BLOCKER-3 site confirmed — `README.md:553-557` reads "「`K1708_results.json` 裡的每一個估計數字…一個都沒動」",
  a whole-file absolute claim, while `provenance_check_recorded_numbers()` only covers the six numbers
  printed in the 2026-07-17 review.
- BLOCKER-5 site confirmed — `K1708.py:2282-2286` reads `mcs_qlike.superior_set` straight off the payload,
  and `scored_regimes` iterates `regimes.items()` with no constraint that the keys be `high`/`low`, so any
  two dict keys satisfy the regime-consistency condition.

---

## Codex final verdict (verbatim)

## A. 四個既有 BLOCKER 裁決

1. **BLOCKER-1 — CLOSED**

   原本「新 gate 嚴格包含於舊 gate，因此不可能把 NULL 推正」的錯誤論證已明確撤回；README 現在承認 comparator 移動不可排序，並明列新口徑尚未在真實資料上評估：`experiments/k1708/README.md:292-314`。

   `gate_transition_audit()` 也會在 own-restriction 統計量缺失時回報不可評估，而不是宣稱兩個 gate 結論相同：`experiments/k1708/K1708.py:2565-2601`。雙向 crossing 測試確實證明 comparator 不可排序：`experiments/k1708/test_k1708.py:1105-1121`。

2. **BLOCKER-2 — CLOSED（但 D 發現另一條殘留盲信路徑）**

   Round-2 的具體攻擊已關閉：

   - `control_series`、`restriction`、`forecast_map` 均對 registry 驗證：`experiments/k1708/K1708.py:2206-2226`
   - t/p 一致性由 `1-Φ(t)` 重算：`experiments/k1708/K1708.py:2230-2247`
   - 身分不合格列排除於 Holm family，Holm 由 verified p-values 重算：`experiments/k1708/K1708.py:2288-2301`
   - gate condition 使用重算結果，不讀 payload 的 `holm.reject`：`experiments/k1708/K1708.py:2310-2323`

   原 reviewer 的 `HAR_FIXED + exact=True + holm.reject=True` 攻擊現在回 NULL；對應測試為 `experiments/k1708/test_k1708.py:979-1027`。

3. **BLOCKER-3 — STILL_OPEN**

   現有補強只核對六個被 round-1 review 記錄的數字；程式自己承認這不是全檔證明：`experiments/k1708/K1708.py:2609-2617`、`experiments/k1708/K1708.py:2660-2667`。測試也明確只檢查六項：`experiments/k1708/test_k1708.py:1145-1158`。

   Git 仍沒有 pre-fix blob，`K1708_results.json` 仍是整檔新增；因此上一輪的核心問題沒有被解決。更嚴重的是 README 仍絕對宣稱「每一個估計數字……一個都沒動」：`experiments/k1708/README.md:553-557`。這個強度超過現有六項旁證，屬於不可驗證的 provenance 宣稱。

4. **BLOCKER-4 — CLOSED**

   核心修復現在具鑑別力：

   - 雙 schema fixture 讓新舊 gate 都能讀到各自 comparator：`experiments/k1708/test_k1708.py:494-510`
   - 四個 regression case 同時要求「新 gate NULL、舊 gate SUPPORTED」：`experiments/k1708/test_k1708.py:916-939`
   - guard-on-the-guard 要求未修改 fixture 必須通過新 gate：`experiments/k1708/test_k1708.py:942-953`
   - registry 測試實際 dereference 並呼叫 forecast generator：`experiments/k1708/test_k1708.py:748-787`
   - no-op restriction 會因 control 等於 unrestricted forecast 而失敗：`experiments/k1708/test_k1708.py:790-820`

   完整 suite 實跑結果為 `54 passed in 135.90s`。

## B. 未重跑下的 gate 缺口

**這個缺口本身 acceptable，不構成 BLOCKER。**

理由是程式與 README 現在沒有宣稱新舊 gate 可排序，也沒有把缺失的 own-restriction 統計量當成通過證據。stored artifact 在舊 gate 下因 t 未達標而為 NULL；在現行 gate 下則因 primary nested 欄位不存在而 fail-closed 為 NULL：`experiments/k1708/K1708.py:2270-2280`、`experiments/k1708/test_k1708.py:650-675`。

所以目前不存在「corrected gate 已把 stored NULL 推正」的實例，也沒有把「沒有資料可評估」冒充成「實證確認仍為 NULL」。

條件是：重跑前不得宣稱 corrected gate 已在 full sample 得到 NULL；任何論文、knowledge 或正式結果更新前，必須先重跑並產生 own-restriction series。這項條件不因「本輪未重跑」本身阻擋合併；本次 FAIL 來自其他缺陷。

## C. 獨立 lookahead 檢查

**未發現 lookahead。**

- 三個訊號都有明確 `.shift(1)`：`experiments/k1708/K1708.py:361-378`
- OLS 在 origin `i` 只估計 `valid[lo:i]`：`experiments/k1708/K1708.py:890-898`
- Kalman forecast 先記錄 prediction，再用 `y_t` 更新：`experiments/k1708/K1708.py:505-537`
- HARSL 同樣先 forecast、後 update：`experiments/k1708/K1708.py:694-717`
- rolling／discount validation 僅使用 `[val_start, rp)`，discount scale 更只用 `[0,val_start)`：`experiments/k1708/K1708.py:1032-1050`、`experiments/k1708/K1708.py:1053-1087`
- MLE 與 HARSL hyperparameters 明確只吃 `X[:rp], y[:rp]`：`experiments/k1708/K1708.py:1132-1134`
- `hyper_for` 只選 `k <= origin` 的最新 refit：`experiments/k1708/K1708.py:1311-1320`
- restriction controls 是逐 refit patch 對應的 training-only fitted hyperparameter，再按 `k <= origin` 配給：`experiments/k1708/K1708.py:1365-1376`
- 生產端 refit table 每個 `rp` 都由 `select_hypers_at_refit(..., rp, ...)` 建立：`experiments/k1708/K1708.py:1911-1935`

因此 restriction patch 沿用的是當期 training-window hyperparameters，不是用 full sample 選出的單一參數。

## D. Verdict payload 信任邊界

**發現新的 BLOCKER。**

原始 BLOCKER-2 的 registry／Holm 問題已修好，但 `assess_market()` 仍直接信任：

- `mcs_qlike.superior_set`：`experiments/k1708/K1708.py:2282`
- payload 的 `qlike_vs_control`：`experiments/k1708/K1708.py:2325`
- regime 名稱、樣本數及 margin：`experiments/k1708/K1708.py:2283-2286`、`experiments/k1708/K1708.py:2313-2332`

特別是 regime gate 只要求「至少兩個字典項目」，沒有要求它們必須是 `high` 與 `low`。我把合格 fixture 的兩個 key 改成 `foo`／`bar`，其餘不動，仍得到 `CONDITIONAL_PASS` 且 `regime_consistent=True`。

另外，測試中的 `_passing_market()` 本身就是純手工 payload；沒有 forecast/control arrays、沒有可重算的 MCS 輸入，仍可得到正 verdict：`experiments/k1708/test_k1708.py:478-491`、`experiments/k1708/test_k1708.py:570-575`。生產端 map 測試能防止目前 generator 接錯，但不能驗證一份 serialized payload 的 MCS、regime 或 QLIKE 數字確實來自該 generator。forecast ledger 也只保存正式模型，不保存 nesting controls：`experiments/k1708/K1708.py:2159-2165`。

`gate_transition_audit()` 同樣只依欄位存在與 t-stat 判斷 comparator 是否可評估，沒有呼叫 registry identity 驗證：`experiments/k1708/K1708.py:2565-2587`。它不控制 verdict，但可能產生錯誤的 reader-facing audit。

`legacy_derive_verdict()` 的兩個 anchors 對本輪差異測試所需的狹窄行為足夠可信：stored 六欄相符及 reviewer false-positive 均被釘住：`experiments/k1708/test_k1708.py:678-712`。但它仍不是原 bytes，也不能被解讀成完整等價重建。

## E. 測試是否真的會咬

四個指定核心測試目前都會咬：

- differential cases 不再只是斷言 NULL，而是明確要求舊 gate 接受、新 gate 拒絕：`experiments/k1708/test_k1708.py:929-939`
- fixture guard 防止 malformed baseline 讓所有 mutation 假通過：`experiments/k1708/test_k1708.py:942-953`
- forecast-map 測試執行 production generator 並和 registry dereference 的 map 逐元素比對：`experiments/k1708/test_k1708.py:748-787`
- restriction test 會抓到 no-op patch：`experiments/k1708/test_k1708.py:790-820`

仍有刻意不是 regression discriminator 的測試，例如 stored NULL anchor：`experiments/k1708/test_k1708.py:650-675`，以及只覆蓋六個數字的 provenance test：`experiments/k1708/test_k1708.py:1145-1158`。它們的 scope 已在測試內誠實標示；問題是 README 對 provenance 的外部宣稱仍超出這個 scope。

BLOCKER-3: 無 pre-fix blob，六項旁證不足以支持 README「每一個估計數字一個都沒動」的全檔宣稱 :: experiments/k1708/README.md:555
BLOCKER-5: assess_market 仍盲信 MCS membership 與任意 regime labels/margins；自洽人工 payload 可直接取得正 verdict，生產端測試未綁定 serialized payload 與原始 forecasts :: experiments/k1708/K1708.py:2282
VERDICT: FAIL
