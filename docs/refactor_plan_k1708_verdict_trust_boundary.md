# Refactor plan — K1708 verdict gate 的信任邊界

**3-STRIKE TRIGGER**（CLAUDE.md § Three-Strike Rule）
**開立**：2026-07-22（round-3 Codex primary-path review 判 FAIL 後）
**狀態**：待執行。K1708 worktree `dispatch-slot-1-457427c2-k1708` **保留未合併**，branch `wt/dispatch-slot-2-8dda242d-k1708`。

---

## 觸發事實：同一個 surface 連續三輪 FAIL

| # | 日期 | 審查對象 | 裁決 | 落在 verdict gate 上的缺陷 | 審查檔 |
|---|---|---|---|---|---|
| 1 | 2026-07-17 | pre-fix bytes（不在 git，見下） | FAIL / 3 BLOCKERs | BLOCKER 2：gate substitution 比 pre-registered 的鬆（`K1708.py:1952-1960`）<br>BLOCKER 3：`derive_verdict` 沒實作宣告的 cross-market success condition（`K1708.py:1941-1968`） | `storage/ops/k1708_codex_review_20260717.md` |
| 2 | 2026-07-19 | `cd135b00e` | FAIL / 4 BLOCKERs | BLOCKER-2：`derive_verdict` 盲信 payload 的 `exact_on_scored_object` 與 `holm.reject`，未核 registry 身分、未重算 Holm（`K1708.py:2176-2182`）。實測把 `control_series` 改成 `HAR_FIXED` 仍得 `CONDITIONAL_PASS`。 | `storage/ops/k1708_codex_review_round2_20260719.md` |
| 3 | 2026-07-22 | `01efab8c8` | FAIL / 2 BLOCKERs | BLOCKER-5（新）：`assess_market` 仍盲信 `mcs_qlike.superior_set`、`regime_breakdown` 的任意 key、`qlike_vs_control`（`K1708.py:2282-2286, 2325`）。實測把合格 fixture 的 regime key 改成 `foo`/`bar`，仍得 `CONDITIONAL_PASS` 且 `regime_consistent=True`。 | `storage/ops/k1708_codex_review_round3_20260722.md` |

三輪打的是**同一個函數**（`derive_verdict` / `assess_market`），失敗模式是**同一類**：
**gate 的判決依賴它自己沒有驗證的東西。**

round-2 的 remediation 品質其實不差 —— 它把 reviewer 點名的三個欄位
（`control_series` / `restriction` / `forecast_map`）對 registry 驗證、把 Holm 重算、加了 t/p 一致性檢查，
而且四個新測試在重建的舊 gate 下確實全 FAIL（鑑別力是真的）。round-3 也確認 BLOCKER-1/2/4 **CLOSED**、
lookahead **乾淨**。

問題不在修得不夠用力，在**修的範圍是 reviewer 點名的那幾欄，不是那個 class**。
於是 round 3 攻擊沒人點名過的欄位，一擊即中。這正是 repo 自己
`.claude/rules/experiments.md` §「Audit methodology hard rule」寫過的失敗模式：
**子集 audit 把 false negative 留在子集外的盲區**。照現在的做法，round 4 會找到下一批欄位。

---

## 三層診斷

### 1. 底層邏輯（domain model 錯了）

`assess_market()` 宣稱回答的問題是「**這個實驗支持什麼結論**」，
但它的實際輸入是「**一份摘要 JSON**」。這兩者不是同一個定義域。

只要 verdict 的輸入是 serialized summary，**逐欄再推導永遠關不掉這個 class** ——
一份自洽的捏造 payload（t/p 互相一致、身分欄位全對、數字憑空生成）必然能通過任何
只看 payload 的檢查。round-2 的 remediation 自己就誠實寫下了這句話
（`REMEDIATION_rev2.md` BLOCKER 2 §「還剩什麼沒解決」），但沒有據此改變 verdict 的輸入。

結論該由**原始 forecast 序列**決定；payload 應該降級成「可從序列重算出來的 cache」，
而不是 verdict 的 source of truth。

### 2. 流程（audit 是 subset-driven，沒有 full-population sweep）

- 沒有任何一處**宣告**過「verdict 的 gate condition 讀了哪些 payload 欄位、
  其中哪些是 authoritative、哪些必須重算」。清單只存在於歷次 review 的攻擊紀錄裡。
- 因此「修完了嗎」無法回答，只能等下一個 reviewer 猜到下一欄。
- repo 已有規則要求 full-population audit + 機械 gate
  （`.claude/rules/experiments.md`、memory `feedback_declare_complete_requires_class_sweep`），
  K1708 的 remediation 沒有套用；也沒有任何機械物擋住「新增一個 gate condition 卻沒宣告它的 authority」。

### 3. 程式架構（函數簽名本身就是缺陷）

`assess_market(mkt: dict)` 只拿得到摘要 —— 它**在型別上就不可能**驗證數字的來源。
`forecast ledger` 只保存正式模型、不保存 nesting controls（`K1708.py:2159-2165`），
所以就算想重算也缺原料。

---

## 方案

**S1 — 宣告信任邊界（先讓問題可被度量）**
在 `K1708.py` 立一份 module-level 的 `VERDICT_INPUT_AUTHORITY`：
每個進入 gate condition 的 payload key 標成 `RECOMPUTED`（由 registry / 原始序列重推）、
`STRUCTURAL`（只用存在性，不用數值）、或 `TRUSTED`（明確承認信任，附理由）。
目前已知需入列的至少有：`status`、`cw_vs_own_restriction_primary.{t_stat, p_value_one_sided,
qlike_vs_control, control_series, restriction, forecast_map, holm.reject}`、
`mcs_qlike.superior_set`、`regime_breakdown.{keys, n, qlike_vs_own_restriction}`。

**S2 — 機械 gate（擋住 class 復發，不是擋住這兩個 bug）**
`test_k1708.py` 加一個 AST 測試：掃 `assess_market` / `derive_verdict` / `gate_transition_audit`
內所有對 payload 的 subscript / `.get()`，斷言**每一個 key 都出現在 `VERDICT_INPUT_AUTHORITY`**。
新增 gate condition 卻沒宣告 authority → 測試直接 FAIL。
這是本計劃唯一能防住 round 4 的東西；沒有它，S1 會在下次改動時腐化。

**S3 — 把 verdict 的輸入換成序列（真正的 domain fix）**
- `forecast ledger` 補存 nesting controls（S3 的前置，沒有它 S3 做不動）。
- `assess_market` 改成 `assess_market(ledger, registry)`：MCS superior set、regime 切分與
  `qlike_vs_control` 一律**從序列重算**，payload 僅作為 cache 並斷言 `recomputed == cached`。
- regime key 必須來自宣告的 regime 定義（擋掉 `foo`/`bar` 那個攻擊），不接受任意 dict key。

**S4 — README provenance 宣稱降級（關掉 BLOCKER-3）**
`README.md:553-557` 現在寫「`K1708_results.json` 裡的每一個估計數字…**一個都沒動**」——
這是全檔絕對宣稱，但證據只有 round-1 review 印出的**六個數字**
（`provenance_check_recorded_numbers()` 自己的 `scope` 欄位already 誠實標註了這件事）。
改為明確的六項旁證措辭，並寫明其餘約 1768 行**無獨立來源可比對**。
這一項不需要重跑，是純措辭修正，但**必須做**：研究誠實原則 §6「結論強度不超過證據」。

**S5 — rerun（S3 落地後）**
full-sample rerun 會首次產生 own-restriction 統計量，
`gate_transition_audit` 的 cross-comparator 欄位才會從 `not evaluable` 變成有內容。
**在 rerun 之前，不得宣稱「corrected gate 已在 full sample 得到 NULL」**
（round-3 §B 明列的條件）。

## 廢棄面

S3 落地後，`assess_market` 的 payload-only 路徑**整條廢棄**，不留兩套：
`registry_identity_violations` / `t_p_inconsistency` 從「verdict 的防線」降級為
「cache 一致性檢查」。不保留 `_legacy` 並行路徑（CLAUDE.md § Three-Strike「不留兩套」）。

## 驗證 gate（三次觸發條件都要被覆蓋）

1. round-1 條件：gate 實作與 pre-registered 條件不符 → 已由 `test_gate_regression_cases_actually_discriminate` 覆蓋，保留。
2. round-2 條件：relabel `control_series` → 已由 `test_a_row_that_contradicts_the_registry_cannot_qualify` 覆蓋，保留。
3. round-3 條件：**新增** regime key 改名（`foo`/`bar`）必須 NULL；MCS superior_set 造假必須 NULL；`qlike_vs_control` 與序列不符必須 NULL。
4. **class gate**：S2 的 AST 測試 —— 未宣告 authority 的 payload key 進入 gate condition 即 FAIL。

## 不做什麼

- **不再走「reviewer 點名 → 修那幾欄 → 重審」的第 4 輪。** 那正是造成 strike 3 的迴圈。
- 不在 S2 之前重跑 full sample（會用掉一次昂貴 run 去驗證一個已知會再破的 gate）。
- 不手改 `review_verdict.json` 讓 sha256 對上（K1709 事故）。

## Commit 慣例

落地 commit 開頭：`refactor(3-strike): k1708 verdict trust boundary`
