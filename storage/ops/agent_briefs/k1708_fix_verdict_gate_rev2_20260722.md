# K1708 fix stage rev2 — 修 Codex round-2 FAIL 的 4 個 BLOCKER

**Model**: opus / max (per model_router, attempt=1, at_ceiling=true)
**Task id**: `k1708_fix_verdict_gate_rev2_20260719`
**Worktree（你的寫入範圍）**: `.claude/worktrees/dispatch-slot-1-457427c2-k1708`
（branch `wt/dispatch-slot-2-8dda242d-k1708`；原 worktree `dispatch-slot-2-8dda242d-k1708`
已被回收，本 worktree 是從同一 branch 重新簽出的，內容一致）

## 先讀

1. `storage/ops/k1708_codex_review_round2_20260719.md` — 本輪要修的 review 全文，**你的起點**
2. `storage/ops/k1708_codex_review_20260717.md` — 上一輪 review（BLOCKER 3 要用到它記錄的數字）
3. `experiments/k1708/README.md`、`K1708.py`、`test_k1708.py`

## Round-2 已 PASS，不要重做

Holm 實作正確；`NESTING_REGISTRY` 的 control 由自身 forecast map 在受限參數下產生；
`regime_breakdown` 用 nested pair；無 quick artifact 殘留；README §8.1/8.2/12/15 已誠實撤回。
pytest 35 passed（主線程獨立複跑 115.7s 確認過）。

## 要修的 4 個 BLOCKER

### 1. gate 鬆緊無法證明（`K1708.py:1513, 1560-1561`）

comparator（`CW vs HAR_FIXED` → `CW vs own restriction`）與 bar（`1.645` → `3.0`）**同時改**，
所以原本的論證「t≥3 是 t>1.645 的子集，故不可能把 NULL 轉正」不成立 —— 兩邊的統計量本身就不同，
子集關係無從談起。

二選一，都可以：
- 證明新 gate 在**同一 comparator** 下的保守性（把 comparator 固定，只動 bar，證明單調）；或
- 改用可驗證的方式：對 stored ledger **同時算出兩種 gate 的結果並列表**，讓保守性成為可檢查的
  事實而非論證。

### 2. verdict 盲信欄位（`K1708.py:2176-2182`）

`derive_verdict` 沒有核對 registry control 身分、也沒有重算 Holm。也就是說，只要把
`exact` / `reject` 標籤貼到**錯誤的比較**上就能過關。要在 verdict 端做 identity 檢查 + 重算防呆：
verdict 必須自己驗證它讀到的比較確實是 registry 宣告的那一對，並自己重算 Holm，而不是信任上游欄位。

### 3. untouched 不可驗證

`cd135b00e^` 沒有 `experiments/k1708/`，整份 `K1708_results.json` 是以**新增檔**進入 diff 的，
沒有 pre-fix blob 可比對，所以「數字沒被動過」目前無法用 git 證明。

要補獨立佐證：用 2026-07-17 review 文件**已記錄**的數字 —— QLIKE `+0.776` / `+1.460` / `-1.677%`、
CW t `1.202` / `1.545` / `-1.209` —— 對 stored payload 逐項核對，寫成一段 provenance。
若核對後仍有無法覆蓋的部分，**明講此性質只能靠旁證**，不要假裝證明了。

### 4. 新測試不咬（`test_k1708.py:535-548, 625-640`）

`test_gate_holds_the_pre_registered_t_bar` / `test_inexact_nesting_flag_is_load_bearing` /
`test_regime_consistency_needs_both_regions_scored` / `test_stored_full_sample_verdict_is_still_null`
在 **pre-fix logic 下同樣返回 NULL 而通過**（舊 logic 根本不讀新欄位）。

regression test 必須**在舊邏輯下 FAIL** 才有價值 —— 請重寫成能鑑別新舊行為的形式，並在 commit
訊息或 README 裡說明你怎麼確認它會咬（例如暫時還原舊邏輯跑一次，記錄 FAIL 輸出）。
registry 測試也只驗名稱與 boolean，沒呼叫真正的 forecast generator —— 要真的呼叫。

## 硬規則

- **不得為了過 gate 動任何數字**。研究誠實 > 一切。
- full-sample rerun **不在本 stage 範圍**（先修 gate 與測試，再談 rerun）。
- `knowledge.json` **由主線程寫，你不得寫**（K1259 gate）。
- 只在上面那個 worktree 內寫入。不要碰 `storage/next_tasks.json` / `feed.json` 等共用狀態。
- ⚠️ **Codex 額度目前耗盡**（實測 usage limit，重置 2026-07-25 13:30 台北）。所以本輪
  **你不需要也不應該嘗試跑 codex 二審** —— 做完 4 個 BLOCKER、跑完 pytest、把成果 commit 在
  worktree 上即可。二審由後續班次在額度恢復後執行。不要用 fallback reviewer 替代 primary path，
  也不要因為審不了就宣稱通過。

## 交付物

寫 `experiments/k1708/REMEDIATION_rev2.md`，逐一對應 4 個 BLOCKER：
每個 BLOCKER 一段，寫「改了什麼 / 改在哪個檔案行號 / 怎麼驗證的 / 還剩什麼沒解決」。
BLOCKER 4 必須附「舊邏輯下 FAIL」的證據。pytest 全綠是必要條件不是充分條件。

若某個 BLOCKER 你判斷做不到或問題本身有誤，**寫下來說明理由**，不要硬湊一個看起來完成的樣子。
