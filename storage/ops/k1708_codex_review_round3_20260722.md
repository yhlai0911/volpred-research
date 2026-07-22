OpenAI Codex v0.144.6
--------
workdir: /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-457427c2-k1708
model: gpt-5.6-sol
provider: openai
approval: never
sandbox: read-only
reasoning effort: high
reasoning summaries: none
session id: 019f875e-f79c-7ba0-af37-20546d4fd231
--------
user
# K1708 round-3 primary-path review

You are the primary-path reviewer for experiment K1708 (time-varying state-space HAR vs
fixed/rolling HAR). This is round 3. Round 2 returned **VERDICT: FAIL with 4 BLOCKERs**.
Your ONLY job this round is to decide whether those 4 BLOCKERs are genuinely closed.

## Files to read (all paths relative to cwd)

- `experiments/k1708/REMEDIATION_rev2.md` — the author's claim of what was fixed (read FIRST,
  but treat it as a claim to verify, not as evidence)
- `experiments/k1708/K1708.py` (2673 lines)
- `experiments/k1708/test_k1708.py` (1158 lines)
- `experiments/k1708/README.md`
- Prior reviews for context: `storage/ops/k1708_codex_review_round2_20260719.md` and
  `storage/ops/k1708_codex_review_20260717.md`

## The 4 round-2 BLOCKERs

1. **gate 鬆緊無法證明** — no evidence the corrected verdict gate is stricter/looser in the
   claimed direction.
2. **verdict 盲信欄位** — verdict derived by trusting stored fields instead of recomputing.
3. **untouched 不可驗證** — the "untouched" claim could not be verified (pre-fix bytes absent
   from git).
4. **新測試不咬** — the new tests did not discriminate: they passed under the OLD (buggy)
   logic too.

## What to check, per BLOCKER

For each: (a) does the code actually implement the claimed fix? (b) is the *verification
evidence* the author cites real and sufficient, or does it merely restate the fix? (c) does a
residual gap remain that the author is under-reporting?

Pay particular attention to:
- `legacy_derive_verdict()` (`K1708.py:~2463`) is a **reconstruction** of the pre-fix gate,
  not the original bytes. Is that reconstruction faithful enough to make the BLOCKER 4
  discrimination evidence meaningful, or is it circular (author writes both the "old" logic
  and the test that is supposed to fail against it)?
- The author admits the new gate has **never run on real data** and provenance covers only
  six numbers. Decide whether those admitted gaps are acceptable-with-disclosure or are
  themselves blocking.
- Any place where a test asserts on a stored field rather than on a recomputed value.

## Hard rules

- Research honesty outranks everything. Do NOT pass something to be agreeable.
- Do not accept "will fix later" as closure.
- Note that K1708's research verdict is NULL (state-space did NOT beat HAR). This review is
  about gate/test correctness ONLY — do not re-litigate the research finding, and do not
  treat the NULL result as a defect.

## Required output format

End your response with exactly this block:

```
VERDICT: PASS | FAIL
BLOCKER_1: CLOSED | OPEN — <one line>
BLOCKER_2: CLOSED | OPEN — <one line>
BLOCKER_3: CLOSED | OPEN — <one line>
BLOCKER_4: CLOSED | OPEN — <one line>
```

VERDICT is PASS only if all four are CLOSED. Before that block, give your reasoning with
concrete file:line citations.
codex
我會只審核 round-2 的四個 BLOCKER，不延伸評判 NULL 研究結論。先讀作者的 rev2 聲明，再逐項對照實作、測試、舊審查與可追溯證據；最後會實跑可行的針對性測試。
exec
/bin/zsh -lc "sed -n '1,260p' experiments/k1708/REMEDIATION_rev2.md" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-457427c2-k1708
 succeeded in 0ms:
# K1708 — round-2 BLOCKER remediation

- **對應 review**：`storage/ops/k1708_codex_review_round2_20260719.md`（VERDICT: FAIL, 4 BLOCKERs）
- **前一輪**：`storage/ops/k1708_codex_review_20260717.md`（VERDICT: FAIL, 3 BLOCKERs）
- **本階段 scope**：只修 gate 與測試。**不重跑 full sample**（brief 明列不在範圍），
  **不寫 `knowledge.json`**（K1259 gate，由主線程負責）。
- **pytest**：`54 passed in 112.27s`（修改前 35 passed）。
- **experiment gates**：`uv run python scripts/experiment_gates.py run --path experiments/k1708`
  → `PASS — 2 file(s) cleared 4 experiment-integrity gates`。
- **Codex 二審**：**本輪未執行**。brief 明令不得以 fallback reviewer 代替 primary path，
  也不得因審不了而宣稱通過。**本文件不是通過裁決**；二審由後續班次執行。

  > **⚠️ 更正（2026-07-22 08:16 台北）** —— 本行原文為「Codex 額度實測耗盡（重置
  > 2026-07-25 13:30 台北）」。**該宣稱已被實測推翻**：
  > `bash scripts/codex_exec_bounded.sh --timeout 100 "reply with exactly: QUOTA_OK"`
  > 於 2026-07-22 08:15 台北回傳 `QUOTA_OK`、exit 0、tokens used 11,432。
  > Codex primary path 在本文件寫成後（或當時即）是可用的，額度耗盡不是二審未執行的
  > 有效理由。round-3 primary-path 二審已於本日執行 →
  > `storage/ops/k1708_codex_review_round3_20260722.md`。
  > 保留原宣稱於此以存查，不刪除（研究誠實：錯誤前提要留痕，不是抹掉）。

**先講一個貫穿全文的關鍵事實**（它同時決定 BLOCKER 1/3/4 能做到什麼程度）：
已存檔的 `K1708_results.json` 是**修正前**的產物 —— 它帶的是舊 schema
`cw_vs_benchmark_primary`，**沒有 `cw_vs_own_restriction_primary`**，own-restriction 的對照序列
也從未被保存（不在 results.json，不在 forecast ledger）。所以**新口徑的 gate 從未在真實資料上
被評估過**。這不是缺陷，是 brief 刻意把 rerun 排除在本階段之外的後果；但它把「經驗上證明新
gate 更緊」這條路整條封死，下面會逐項講清楚。

---

## BLOCKER 1 — gate 鬆緊無法證明

**Review 指出**：comparator（`CW vs HAR_FIXED` → `CW vs own restriction`）與 bar
（`1.645` → `3.0`）同時改，所以「t≥3 是 t>1.645 的子集，故不可能把 NULL 轉正」不成立。

### 改了什麼

**這個宣稱已撤回，不是修補。** Review 判得對：兩個門檻套在**不同的統計量**上，
`t_own` 與 `t_fixed` 是不同 pair 上算出來的數，根本沒有集合可以談子集關係。

改採 review 給的兩個選項**各做一半**，因為它們各自只能覆蓋一半：

**(a) 拆解成兩個獨立移動，證明可排序的那一半**

| 移動 | 可排序？ | 機械證據 |
|---|---|---|
| **bar** 1.645 → 3.0（comparator 固定） | ✅ 嚴格子集 | `test_bar_move_is_a_subset_when_the_comparator_is_held_fixed`（`test_k1708.py:1094`）：200 組隨機 t 向量，斷言 `{t≥3} ⊆ {t>1.645}` |
| **併行條件** 加 Holm / MCS / regime / per-market | ✅ 單調收緊 | 加 conjunct 只能縮小通過集合 |
| **comparator** vs HAR_FIXED → vs own restriction | ❌ **兩方向都不可排序** | `test_comparator_move_is_not_orderable_in_either_direction`（`test_k1708.py:1105`）**明確造出兩個方向的交叉** |

**(b) 把鬆緊變成可查的事實表，而非論證**

`gate_transition_audit()`（`K1708.py:2539`）對任一 market payload 並列輸出兩個 gate 的 screen，
欄位不存在時明確回報 `evaluable: false`。已 wire 進 payload（`K1708.py:2178`），
下次 rerun 每個 market 都會帶一份。

配套：`legacy_derive_verdict()`（`K1708.py:2463`）是修正前 gate 的**重建**（見 BLOCKER 4 的
anchor 討論），讓「舊 gate 在這份 payload 上會說什麼」變成可執行的函數而不是回憶。

### 怎麼驗證的

- 上述兩個 test 各自釘住可排序與不可排序的那一半。
- `test_gate_audit_reports_the_stored_payload_as_not_comparable`（`test_k1708.py:1124`）在
  stored payload 上斷言 `cw_vs_own_restriction.evaluable is False` 與
  `cross_comparator_comparison.possible is False`。
- README §8.2.1（`README.md:292`）逐條寫明撤回什麼、為什麼、剩下能宣稱到哪。

### 還剩什麼沒解決

**「修正後的 gate 不會把 stored NULL 推成非 NULL」這句話，現在既無法用論證證明，
也無法用 stored artifact 的經驗證據補上。** 前者因為 comparator 移動不可排序；後者因為
own-restriction 統計量在這份 artifact 裡**不存在**（對照序列從未保存）。
要補這個表**必須重跑**，而重跑不在本階段範圍。

我沒有把這個缺口寫成「已解決」。誠實的現況是：**bar 與併行條件嚴格收緊，comparator 橫移，
整體方向未定**。

---

## BLOCKER 2 — verdict 盲信欄位

**Review 指出**：`derive_verdict` 沒核對 registry control 身分、也沒重算 Holm；
把 `exact` / `reject` 標籤貼到錯誤的比較上就能過關（reviewer 實測把 control 改成 `HAR_FIXED`
仍得到 `CONDITIONAL_PASS`）。

### 改了什麼

verdict 端不再相信 payload 的任何一個 label，全部自己重算：

| 檢查 | 位置 | 做法 |
|---|---|---|
| **registry 身分** | `K1708.py:2190` `registry_identity_violations()` | `control_series` / `restriction` / `forecast_map` 三個欄位逐一比對 `NESTING_REGISTRY`；`exact_on_scored_object` **由 registry 推導**，payload 與 registry 不一致即列為 violation |
| **t/p 內部一致性** | `K1708.py:2230` `t_p_inconsistency()` | `clark_west_test` 定義 `p = 1 − Φ(t)`；不符即拒。擋掉「小 t 配貼上去的小 p」這種兩個數不可能同時為真的列 |
| **Holm 重算** | `K1708.py:2298-2300` | 從**通過身分檢查的列**的 p-value 重新跑 `holm_bonferroni`；condition (3) 讀重算值（`K1708.py:2323`），不讀 payload |
| **condition (1) 改讀重算值** | `K1708.py:2318` | `"exact_nesting": identity_ok`，不再是 `bool(cw.get("exact_on_scored_object"))` |

兩個設計細節值得點出：

1. **身分不合格的列會被踢出 Holm family**，不只是自己不通過 —— 否則一個造假的列仍會把 `m`
   撐大、放寬其他所有列的門檻。`test_a_relabelled_row_is_excluded_from_the_holm_family`
   （`test_k1708.py:1003`）釘住。
2. **payload 與重算不一致時會被記錄**（`holm_payload_flag_disagrees`），不是安靜覆蓋 ——
   不一致本身就是手改過的簽名。

### 怎麼驗證的

- `test_a_row_that_contradicts_the_registry_cannot_qualify`（`test_k1708.py:966`）4 個
  parametrize case，其中 `forecast_map=forecast_ols_block` 就是 2026-07-17 缺陷的原形。
- `test_exact_flag_pasted_onto_a_registry_mismatch_still_fails`（`:979`）—— reviewer 的攻擊
  加強版：control 改成 `HAR_FIXED`、`exact` 與 `holm.reject` 兩個標籤同時貼上去，仍然 NULL。
- `test_stored_holm_flag_is_recomputed_not_trusted`（`:1016`）—— 反向：把 `reject` 從 True
  改成 False，verdict **不動**（重算說 True），且不一致被記錄。
- `test_t_and_p_must_come_from_the_same_test`（`:992`）。
- 這 4 個 test **全部在舊邏輯下 FAIL**（見 BLOCKER 4 證據表）。

### 還剩什麼沒解決

**檢查的是「這列是否是 registry 宣告的那一對」，不是「這列的數字是否真的由那個 map 算出來」。**
一份完全捏造但自洽的 payload（t/p 一致、欄位全對、數字憑空生成）仍會通過 verdict 端的檢查。
verdict 讀的是 JSON，JSON 端能做的極限就是自洽性與身分。

真正擋掉「數字不是那個 map 算的」需要在**生產端**驗證 —— 那是 BLOCKER 4 的
`test_nesting_controls_are_produced_by_the_declared_forecast_map` 負責的層，兩層合起來才完整：
生產端保證 artifact 裡的數字來自宣告的 map，verdict 端保證讀到的列是宣告的那一對。

---

## BLOCKER 3 — untouched 不可驗證

**Review 指出**：`cd135b00e^` 沒有 `experiments/k1708/`，整份 `K1708_results.json` 以新增檔進入
diff，沒有 pre-fix blob 可比對，所以「數字沒被動過」無法用 git 證明。

### 改了什麼

**先確認 review 的前提為真**，而且比它說的更絕對：

```
$ git log --all --oneline -- experiments/k1708/K1708.py
cd135b00e fix(k1708): close verdict-gate false positive; ...     ← 唯一一個 commit
$ git cat-file -t 43bffdd4784b1522b68aa2ac5cfecbb5b5d6bcfbe5003dd6df687b49d80f018e
fatal: Not a valid object name                                    ← pre-fix bytes 不在任何 object db
```

整個 `experiments/k1708/` 只被一個 commit 碰過，而那個 commit 就是修正本身。
**pre-fix 的 code 與 results 都不在 git 裡**，`code_trace` 記的 sha256 指向一份沒有任何
object database 存有的內容。git 這條路是死的，不只是「不方便」。

改為用 review 指定的旁證路徑：`provenance_check_recorded_numbers()`（`K1708.py:2629`）
對 2026-07-17 review **已記錄**的六個數字逐項核對 stored payload。

### 怎麼驗證的

`test_stored_numbers_still_match_the_20260717_review`（`test_k1708.py:1145`）。實跑結果：

| 數字 | 2026-07-17 review 記錄 | stored payload 重算 | |
|---|---|---|---|
| QLIKE 改善 HAR_KF_DISC | `+0.776%` | `+0.776%` | ✅ |
| QLIKE 改善 HAR_KF_MLE | `+1.460%` | `+1.460%` | ✅ |
| QLIKE 改善 HAR_S_BM | `−1.677%` | `−1.677%` | ✅ |
| CW t HAR_KF_DISC | `1.202` | `1.2015472928…` → `1.202` | ✅ |
| CW t HAR_KF_MLE | `1.545` | `1.5449555590…` → `1.545` | ✅ |
| CW t HAR_S_BM | `−1.209` | `−1.2087975704…` → `−1.209` | ✅ |

**六項全中。** 值得一提的是 QLIKE 三項並非直接存成百分比 —— 它們是從 `mean_qlike` 的
原始值重算出來的，所以要偽造必須同時移動原始平均值**且**恰好落回同樣三個四捨五入後的百分比。

### 還剩什麼沒解決

**這是六個數字的旁證，不是「全部 stored numbers 未被動過」的證明。**

review 印了哪六個數字，就只能核對哪六個；results.json 裡其餘約 1768 行（MCS、GW、regime、
schedule diagnostic、tuning log…）**沒有任何獨立來源可比對**。此性質**只能靠旁證**，
現有材料下不存在更強的驗證方式，我也沒有假裝證明了它 —— 這句話同時寫進
`provenance_check_recorded_numbers()` 的 `scope` 欄位與該 test 的 docstring，
避免下一輪有人把「all_match: true」讀成全檔認證。

---

## BLOCKER 4 — 新測試不咬

**Review 指出**：4 個新測試在 pre-fix logic 下同樣返回 NULL 而通過；registry 測試只驗名稱與
boolean，沒呼叫真正的 forecast generator。

### 根因（比 review 描述的更嚴重）

不是「舊 logic 不讀新欄位所以碰巧也 NULL」而已 —— 是**結構性的**：舊 gate 讀
`cw_vs_benchmark_primary`，新 schema 寫 `cw_vs_own_restriction_primary`。
**用新 schema 寫的 payload 對舊 gate 是隱形的**，舊 gate 一律走 default 回 NULL。
所以任何「新 schema fixture + 斷言 NULL」的測試**在設計上就不可能鑑別新舊**，
不管斷言寫得多細。

### 改了什麼

**(1) fixture 改成雙 schema** — `_dual_schema_market()`（`test_k1708.py:494`）同時帶
`cw_vs_own_restriction_primary` 與 `cw_vs_fixed_descriptive_not_nested`，
也就是**真正 rerun 後會產生的形狀**。舊 gate 讀得到前者、新 gate 讀後者，兩個 gate 才能在
同一份 artifact 上給出不同答案 —— 有分歧，斷言才有內容。

**(2) 鑑別性寫成斷言，不是宣稱** — `test_gate_regression_cases_actually_discriminate`
（`test_k1708.py:931`）對每個 case **同時**斷言兩件事：新 gate 必須 NULL，
**且重建的舊 gate 必須 SUPPORTED**。測試哪天不再鑑別，這裡直接 FAIL，不會安靜通過。

**(3) 加 guard-on-the-guard** — `test_the_differential_fixture_is_not_broken_by_construction`
（`:942`）：不加 mutation 時 fixture 必須真的通過新 gate。否則上面每個 case 都可能是因為
fixture 壞掉而過，正是 review 抓到的失敗模式。

**(4) registry 測試改成真的呼叫 generator** —
- 從 `run_market` 抽出 `build_nesting_controls()`（`K1708.py:1334`，純抽取、無數值變動），
  並把 `hyper_for` 從 closure 提升為 module-level（`K1708.py:1311`），讓測試能走**生產路徑**。
- `test_nesting_controls_are_produced_by_the_declared_forecast_map`（`test_k1708.py:748`）
  用 `getattr(K, spec["forecast_map"])` **把 registry 的字串 deref 成函數並執行**，
  再與生產產出比對 `assert_array_equal`。字串正是它該抓的錯誤唯一能倖存的地方。
- `test_each_restriction_actually_bites`（`:790`）：control 不得等於未受限模型 ——
  patch 沒生效時 CW 會拿模型跟自己比，adjustment term 為 0，t 值無意義。

**(5) Holm 條件改成兩個誠實的測試** — 原 parametrize 裡的 `holm` case 已移除，因為在
verdict 重算 Holm 之後它不可能再被 payload 編輯打破，而**在 t ≥ 3 時 Holm 也不可能被數字打破**
（單尾 p ≤ 0.00135 < 0.05/3）。硬湊一個「打破 Holm」的 case 會是假測試。改成：
- `test_holm_cannot_bind_at_the_pre_registered_bar`（`:1050`）—— 直接驗證 README §8.2 那句話。
- `test_holm_starts_biting_the_moment_the_t_bar_is_relaxed`（`:1064`）—— monkeypatch 把 bar 放回
  1.645，三個模型 t=1.9（p 落在 α/m 與 α 之間），**且每列都手貼 `holm.reject=True`**；
  只有重算的 Holm 擋在這份 payload 與 CONDITIONAL_PASS 之間。這驗證了 `evaluate()` 註解裡
  「放寬 t 門檻，Holm 會立刻開始咬」那句原本只是散文的承諾。

### 怎麼驗證的 — **舊邏輯下 FAIL 的實測證據**

在 `/tmp` 的**獨立複本**上做（不動 production checkout），只把生產 gate 換成重建的 pre-fix gate，
其餘一字不改：

```bash
cp experiments/k1708/{K1708.py,test_k1708.py,K1708_results.json} /tmp/k1708_legacy_probe/
printf '\nderive_verdict = legacy_derive_verdict\n' >> /tmp/k1708_legacy_probe/K1708.py
uv run --extra dev python -m pytest /tmp/k1708_legacy_probe/test_k1708.py -q -k "<gate tests>"
```

**結果：`23 failed, 31 deselected`** —— 所有 gate 測試在舊邏輯下全數 FAIL。
review 點名的四個，逐一對應：

| review 點名的測試 | 現在的名字 | 舊邏輯下的實測輸出 |
|---|---|---|
| `test_gate_holds_the_pre_registered_t_bar` | `…discriminate[t_below_pre_registered_bar]` | `AssertionError: current gate failed to reject: t = 2.0 clears the old 5% cutoff but not the pre-registered t >= 3` / `assert 'SUPPORTED' == 'NULL'` |
| `test_inexact_nesting_flag_is_load_bearing` | `…discriminate[exact_nesting_flag_false]` | `AssertionError: … a row that admits it is not exactly nested must not become inference` / `assert 'SUPPORTED' == 'NULL'` |
| `test_regime_consistency_needs_both_regions_scored` | `…discriminate[only_one_regime_scored]` | `AssertionError: … regime consistency needs both regions actually scored` / `assert 'SUPPORTED' == 'NULL'` |
| `test_stored_full_sample_verdict_is_still_null` | `…_and_says_why` | `KeyError: 'market_assessment'`（見下方誠實說明） |

外加 reviewer 攻擊本身的 case：`…discriminate[control_relabelled_to_har_fixed]` →
`assert 'SUPPORTED' == 'NULL'`。

registry 測試的鑑別性另外用**兩個獨立的 break-then-verify probe** 驗（同樣在 `/tmp` 複本上）：

| probe | 注入的缺陷 | 結果 |
|---|---|---|
| `wrong_map` | 把 `HAR_S_BM_AT_SIGMA_ETA_ZERO` 改回由 `forecast_ols_block` 產生（**2026-07-17 缺陷原形**），registry 仍宣稱 `forecast_harsl` | `test_nesting_controls_are_produced_by_the_declared_forecast_map` **FAIL** — `Mismatched elements: 308 / 308 (100%)`, `Max relative difference: 2074.9` |
| `no_op_restriction` | 讓 `sig2_eta=0` 的 patch 變成 no-op | `test_each_restriction_actually_bites` **FAIL** — `HAR_S_BM_AT_SIGMA_ETA_ZERO is identical to unrestricted HAR_S_BM` |

**重建 gate 的可信度 —— 這是整段證據的支點，所以單獨講。**
pre-fix bytes 不在 git（見 BLOCKER 3），所以 `legacy_derive_verdict` 是**重建**而非原件。
它之所以能當差異基準，是因為它同時重現兩個**獨立記錄下來**的事實，兩者都寫成測試：

- **anchor A**（`test_k1708.py:678`）：stored `verdict` 區塊就是 pre-fix 函數在真實 full-sample

exec
/bin/zsh -lc "sed -n '261,520p' experiments/k1708/REMEDIATION_rev2.md
cat storage/ops/handoff_latest.md" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-457427c2-k1708
 exited 1 in 0ms:
  payload 上的**自身輸出**。重建版必須逐欄重現 `label` / `qualified_markets` /
  `supported_unreachable` / `state_space_in_mcs_superior_set` /
  `state_space_beating_fixed_har` / `benchmark_in_mcs` **六個欄位** —— 已全部相符。
- **anchor B**（`test_k1708.py:699`）：2026-07-17 review 實測的假陽性 payload
  （TAIFEX 過 5% CW + 第二個市場只有 `status=OK`）必須回 `SUPPORTED` —— 相符。

任一 anchor 失守，這份重建即失效，上面所有差異測試連帶失效 —— 所以兩者是測試而不是註解。

### 還剩什麼沒解決 — **一個我做不到、不硬湊的項目**

**`test_stored_full_sample_verdict_is_still_null` 無法被改成用 label 鑑別新舊，這是設計上的
不可能，不是我沒做。** stored run 在**兩個 gate 下都真的是 NULL** ——
舊 gate 因為三個 CW t（1.202 / 1.545 / −1.209）都沒過 1.645；
新 gate 因為這份 artifact 裡**根本沒有精確 nested 的比較欄位**。
兩個 NULL 都成立，label 相同是事實而非缺陷。

我的處理不是硬湊一個假的鑑別，而是**承認它不是 regression test 並改變它的職責**：
它現在是 **anchor**，且斷言的是**理由**而不只是 label ——
`assert "no exactly-nested Clark-West comparison" in reason`，
外加 `assert "cw_vs_own_restriction_primary" not in tw`（一旦重跑填了這個欄位，
此測試的前提失效，會 FAIL 並要求重寫，不會安靜繼承祝福）。
它在舊邏輯下確實 FAIL（`KeyError: 'market_assessment'`），
但**那是 schema 差異造成的，不是 label 鑑別** —— 我不把這個 KeyError 當成鑑別力宣稱。

其餘未解決項：
- **本輪未經 Codex 二審**（見開頭更正：非額度問題）。pytest 全綠是必要條件，不是充分條件。
- 新 gate 從未在真實資料上跑過（BLOCKER 1 尾段）。
- provenance 只覆蓋六個數字（BLOCKER 3 尾段）。

---

## 檔案變動摘要

| 檔案 | 變動 |
|---|---|
| `K1708.py` | `hyper_for` 提升為 module-level（`:1311`）；`RESTRICTION_PATCH`（`:1326`）；抽出 `build_nesting_controls`（`:1334`）；`gate_transition_audit` wire 進 payload（`:2178`）；`registry_identity_violations`（`:2190`）；`t_p_inconsistency`（`:2230`）；`assess_market` 改重算身分與 Holm（`:2288-2323`）；`legacy_derive_verdict`（`:2463`）；`gate_transition_audit`（`:2539`）；`provenance_check_recorded_numbers`（`:2629`） |
| `test_k1708.py` | 35 → 54 tests。新增雙 schema fixture、差異測試、registry 真呼叫測試、Holm 雙向測試、身分測試、provenance 測試、gate audit 測試 |
| `README.md` | 新增 §8.2.1（`:292`）撤回「嚴格更緊」宣稱，改列可排序 / 不可排序拆解表 |
| `REMEDIATION_rev2.md` | 本檔（新增） |

## 下一步（不在本階段）

1. **Codex primary-path 二審** —— 已於 2026-07-22 執行（原寫「額度 2026-07-25 恢復後」，
   該前提已推翻，見開頭更正）。
2. 二審 PASS 後才談 full-sample rerun；rerun 會首次產生 own-restriction 統計量，
   屆時 `gate_transition_audit` 的 cross-comparator 欄位才會從 `not evaluable` 變成有內容，
   BLOCKER 1 的經驗缺口也才可能補上。
3. `knowledge.json` 由主線程在有裁決後寫入（K1259 gate）。
cat: storage/ops/handoff_latest.md: No such file or directory

codex
作者已明確承認兩個殘留限制：新 gate 尚未用真實資料跑過、provenance 只覆蓋六個數字。接下來我會判斷這些是充分揭露下可接受的範圍限制，還是仍直接違反原 BLOCKER 的 closure 標準；同時核查 legacy gate 的兩個 anchor 是否真的獨立且足以約束重建。另：本 worktree 沒有 `storage/ops/handoff_latest.md`，不影響本次指定檔案審查。
exec
/bin/zsh -lc "sed -n '1,280p' storage/ops/k1708_codex_review_round2_20260719.md" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-457427c2-k1708
 exited 1 in 0ms:
sed: storage/ops/k1708_codex_review_round2_20260719.md: No such file or directory

exec
/bin/zsh -lc "sed -n '1,280p' storage/ops/k1708_codex_review_20260717.md" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-457427c2-k1708
 exited 1 in 0ms:
sed: storage/ops/k1708_codex_review_20260717.md: No such file or directory

exec
/bin/zsh -lc 'git status --short && git log --all --oneline --decorate -- experiments/k1708 | head -30 && git rev-list --all --objects -- experiments/k1708/K1708.py | head -30' in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-457427c2-k1708
 succeeded in 345ms:
801f7f552 (HEAD -> wt/dispatch-slot-2-8dda242d-k1708) docs(k1708): retract the false 'Codex quota exhausted' premise in REMEDIATION_rev2
01efab8c8 fix(k1708 rev2): close the 4 round-2 BLOCKERs; make the gate tests discriminate
cd135b00e fix(k1708): close verdict-gate false positive; move CW to the comparison that actually nests
01efab8c8e29f8c8f1faf7fef8721ed0baa4285d
cd135b00e89a7153f24217c7969f1bcb5da6efe5
0ad03072ad8f413d45f2fbe5f0685663b4f06d73 
86dade314c9340ad8308fa22a0edfb21b70f764c experiments
97a25a7359608a5024ab7d954a6a5b5676f68375 
b7e96d3c2b5aed8f2d63020c855f0f58ea23f720 experiments
1686ab1aecc18fc600d630a8bdd35949c07bfaa6 
8ba212506a3b02f552ed2f899863d8c23d269881 experiments
dc0709c75cac1718e5c202bc78d4625c16947b17 
4cf622c7d658a0edb6a784187bb7c9ec5dd3cb16 experiments
7b921e079c80f8a91de8fa1622cd5033ab7ad5ea 
bed76b7d5d202b334c87e0c81032a8be69f69707 experiments
c60f742864fb5c6cd4b9d826588cec204c869867 
67b0bc90af00e8594323c9904632ad94d05f6199 experiments
368a2adede4c32d7ec7026283b772b659588e1bf baseline/pre-token-opt-2026-04-20
23a5a9c64ae8ed1c9f98a07867e5b85e401f8ad6 pre-doc-refactor
88edd8e2e0b62aea9575635959dce96d742f6aad pre-phase-1
c5731bcc0d84e6b4d85a2f2afcc6b8aa297263f1 pre-phase-2
b5696b85d8cc1fca20417f47ba2ea5d37b2d6c69 pre-phase-3
5eacdea8540c16b2965f69e4fd57200180cefb31 pre-phase-4
da6f6517d8fcb1338ff47a70259265c9d8dbf206 pre-supervisor-refactor
ec331e70adaf0104fc4de26e2da9637502bf7bd1 stable-pre-refactor-20260529
a81541b61f2f96e57aca2e451e4a8d6b3930c461 
39162b772e41dd2b025763af4b727aec5f753bac experiments
e4442f908e2839c4d65b83d804f3eb09556a2dd2 experiments/k1708
0300ed674615590206808b00cb3fa4e1ff3b4934 experiments/k1708/K1708.py
39f347e143775d6c36862caa80eb73efcba7d865 
66a8e37cdc11ac179cee1433f6dc4c158ad2e791 experiments
d6636c1f40aec35c5093d62261a70dc2385bff21 experiments/k1708
433e5735d677423283c660d25bcf730d5161d5c3 experiments/k1708/K1708.py

exec
/bin/zsh -lc "rg --files | rg 'k1708_codex_review|k1708.*review|review.*k1708' || true
git ls-tree -r HEAD storage/ops | rg 'k1708_codex_review' || true
git log --all --oneline -- storage/ops/k1708_codex_review_round2_20260719.md storage/ops/k1708_codex_review_20260717.md | head -30" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-457427c2-k1708
 succeeded in 225ms:
f0350b912 dispatch(14:42): 自動摘要（agent 未留 receipt）: 動到 storage/ops/(8)、scripts(1)、scripts/tests/(1) 等 5 處
ce63a5616 dispatch(08:24): CI red: arc-dedup 把「讀不出機制」當成「機制不同」，於是它最該攔的那家族文章永遠攔不到

exec
/bin/zsh -lc "git show f0350b912:storage/ops/k1708_codex_review_20260717.md | sed -n '1,320p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-457427c2-k1708
exec
/bin/zsh -lc "git show f0350b912:storage/ops/k1708_codex_review_round2_20260719.md | sed -n '1,320p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-457427c2-k1708
 succeeded in 0ms:
# K1708 Codex primary review — 2026-07-17

- **Stage**: stage 3 of the K1708 split (`k1708_stage3_codex_review_merge_20260717`)
- **Reviewer**: `codex exec` (read-only, bounded 900s, via `scripts/codex_exec_bounded.sh`)
- **Subject**: frozen `experiments/k1708/K1708.py` sha256 `43bffdd4784b1522b68aa2ac5cfecbb5b5d6bcfbe5003dd6df687b49d80f018e` + the full-sample numbers in `K1708_results.json` (quick_mode=false, runtime 1571.6s, verdict NULL)
- **Worktree**: `.claude/worktrees/dispatch-slot-2-8dda242d-k1708` (NOT merged — see verdict)
- **VERDICT: FAIL** — do not merge.

The two original BLOCKERs are genuinely fixed and the stored NULL is honest and reproducible. The review fails on the *inference design and the verdict gate*, which are defects that would misfire on a future run even though they did not distort this one.

## What passed

| # | Item | Finding |
|---|---|---|
| 1 | BLOCKER 1 — sigma2 refit on full training | Fixed. `_init_block` reads finite rows `< upto` only (K1708.py:913-927); `sigma2_full` re-estimated on `[0, rp)` and served to production (1103-1124); `forecast_kalman` reads that value (986-996). The δ-selection scale comes only from `[0, val_start)` (1054-1067) — genuinely separate, both logged. |
| 2 | BLOCKER 2 — same filter for estimation and forecasting | Fixed. MLE likelihood and production build the prior by the same rule and start row (532-559, 950-996); MLE input truncated to `X[:rp], y[:rp]` (1116-1118). Enforced in code, not merely asserted. |
| 3 | New look-ahead | None found. Checked feature `.shift(1)` (333-369), `hyper_for` serving `k <= i` (1642-1669), MLE truncation (1117), predictive-moment ordering before the update (491-524), δ-validation window (1054-1071). |
| 4 | BLOCKER tests non-vacuous | Both discriminate. `full_training_scale` asserts the two scales differ before checking which reached the filter (test_k1708.py:328-342); the MLE test replays the production prior and pins likelihood at rel=1e-9 (361-370). Re-ran in isolation: 2 passed. pytest exit 1 is only the CI-parity gate firing on the untracked directory. |
| 5 | Clark-West math | Correct. Adjustment term, sign, one-sided p-value, HAC wiring (1179-1225) recomputed against the repo canonical `clark_west_test` on the real forecast ledger — all three t-stats match to floating-point precision. |
| 6 | NULL follows from the numbers | Yes. TAIFEX QLIKE: DISC +0.776%, MLE +1.460%, HARSL −1.677%; CW t = 1.202 / 1.545 / −1.209, none clears 1.645. SPY/QQQ `FAIL_NO_DATA`. Re-running `derive_verdict` reproduces the stored verdict exactly — not hand-filled, not pressured toward significance. |
| 7 | Provenance | Holds. sha256 + size + mtime_ns in `code_trace` all match disk. Timeline reconstruction in the verify report is correct: code final 22:46:00Z < run start 22:51:08Z, +1571.6s = 23:17:19.9Z = artifact mtimes. The 23:15:51Z rerun receipt did read the superseded results and is correctly treated as obsolete. |

## Blocking defects

**BLOCKER 1 — K1708.py:1394-1405: Clark-West applied where the scored forecasts are not exactly nested.**
`HAR_FIXED` re-estimates β/σ² daily (863-882) while KF/HARSL refit every 252 days with a different σ². The code itself acknowledges those differences propagate into `exp(mu + var/2)` (1242-1268), and README.md:280-306 states outright that δ=1 does not equal `HAR_FIXED` on the scored object and that the HARSL restriction is not `HAR_FIXED` either. Governing the verdict by "any of the three clears CW" therefore reaches past CW's valid domain — CW corrects the nested-model bias, but only for comparisons that actually nest on the forecasts being scored.

**BLOCKER 2 — K1708.py:1952-1960: the gate substitution is materially looser than the pre-registered one.**
The brief pre-registered DM-HLN |t| ≥ 3. The code governs on "any of three models clears one-sided CW at 5% (t > 1.645)" with QLIKE requiring only a point improvement — no Harvey-strength threshold retained, no multiple-testing correction across the three models. When the direction agrees this is plainly easier to clear, which is verdict-shopping risk. The substitution is disclosed honestly (README.md:223-226, results.json:1763), and CW's formula and the 1.645 one-sided cutoff are themselves faithful to the paper — but disclosure does not make an unapproved looser gate equivalent to the approved one.

**BLOCKER 3 — K1708.py:1941-1968: `derive_verdict` does not implement the declared cross-market success condition.**
It reads QLIKE/CW for TAIFEX only, then decides SUPPORTED on `len(qualified) >= 2`, where a second market qualifies merely by `status == "OK"` — it need not show any improvement. Demonstrated empirically during the review: a minimal payload with SPY `status=OK` but no metrics, and only TAIFEX clearing, returns **SUPPORTED**. It also never checks the GW, MCS and regime-consistency conditions declared at README.md:246-251. This did not distort the current run (SPY/QQQ are `FAIL_NO_DATA`, so nothing false could qualify), but it is a live false-positive path for any future run with data.

## Non-blocking

- **NIT** — test_k1708.py:361-366: the MLE regression test hand-copies the production prior rule instead of calling `forecast_kalman`. It catches the old estimator bug but would miss a future regression that changes only the production wiring.
- **NIT** — K1708_results.json:10-23: `code_trace` byte-pins `K1708.py` only, not `model_evaluation.py` / `mcs.py`, which also produce the numbers. The working tree currently recomputes consistently, so provenance holds today, but it is not a complete dependency closure.

## Disposition

Per the split brief, FAIL → **no merge, no rerun, no knowledge write of a merged result**. A bounded fix stage is queued as `k1708_fix_verdict_gate_20260717`. Blocker 3 is a mechanical bug with a clear fix. Blockers 1 and 2 are inference-design questions (which comparison is legitimately nested, and which gate governs) that need a research decision before code changes — the numbers must not move to fit a gate.

 succeeded in 0ms:
# K1708 Codex primary-path re-review (round 2) — 2026-07-19

- **Reviewer**: `codex exec` (read-only, bounded 1500s, via `scripts/codex_exec_bounded.sh`)
- **Subject**: post-fix bytes at worktree `dispatch-slot-2-8dda242d-k1708`, commit `cd135b00e`
- **Prior round**: `storage/ops/k1708_codex_review_20260717.md` (VERDICT: FAIL, 3 BLOCKERs)
- **This round**: **VERDICT: FAIL** — worktree NOT merged, no knowledge.json write of a merged result.
- **Independent checks by main thread**: `pytest experiments/k1708/test_k1708.py -q` → 35 passed (115.7s); no `*.quick.*` artifacts remain; `experiments/k1708/` absent from `main` (confirms BLOCKER-3 premise).

---

1. **FAIL — gate 條件有綁定，但「整體 gate 是嚴格子集」不成立。**

   `assess_market()` 確實要求 exact flag、`t>=3`、Holm、QLIKE `<0`、MCS membership、兩個 regime 同號，缺一即失敗（`K1708.py:2174-2193`）。`t>=3` 本身也確實是 `t>1.645` 的嚴格子集。

   但新舊門檻套在不同比較上：新 gate 使用 own-restriction（`K1708.py:1513`），舊 gate 使用 HAR_FIXED（現為描述性，`K1708.py:1560-1561`）。因此可能有 `t_own>=3`、同時 `t_fixed<=1.645`；不能由臨界值子集推出整體 gate 不會把舊 NULL 轉正。README §8.2 的結論過度宣稱（`README.md:292-293`）。

   此外 verdict 只信任 payload 的 `exact_on_scored_object` 與 `holm.reject`，沒有核對 `control_series` 是否等於 registry，也沒有重算 Holm（`K1708.py:2176-2182`）。實測把 control 改成 `HAR_FIXED` 但保留 exact flag，仍得到 `CONDITIONAL_PASS`。

2. **PASS — Holm 實作正確且正常生產路徑有使用。**

   `holm_bonferroni()` 依 p-value 遞增排序，以 `α/(m-rank)` step-down，第一次失敗後全部停止拒絕（`K1708.py:1449-1462`）。`evaluate()` 對 exactly-nested family 的單尾 CW p-values計算並附回每列（`K1708.py:1524-1529`），`assess_market()` 要求 `holm.reject=True`（`K1708.py:2180`）。

3. **PASS — 生產路徑的 nesting 已實質修正。**

   Registry 為三個模型指定獨立 control（`K1708.py:1283-1302`）。`HAR_S_BM_AT_SIGMA_ETA_ZERO` 由原 HARSL hyperparameters 複製後將 `sig2_eta=0`，再直接呼叫 `forecast_harsl()`（`K1708.py:1893-1907`），不是 `forecast_ols_block()`。

   `cw_vs_benchmark_primary` 不存在於現行 executable code；HAR_FIXED 比較只寫入 `cw_vs_fixed_descriptive_not_nested`（`K1708.py:1550-1569`）。但第 1 項所述 metadata 驗證缺口仍允許人工「重新貼標」後進 verdict。

4. **PASS — regime 使用同一 nested pair。**

   每個 regime 的 `qlike_vs_own_restriction` 與 CW 都使用 registry control（`K1708.py:1664-1683`）；verdict 讀取同一欄位並要求至少兩個 regime 全為負（`K1708.py:2160-2189`）。

5. **FAIL — NULL 保持不變，但「結果檔未動」無法由 Git 證明。**

   `K1708_results.json` 內原 verdict 是 `NULL`，目前 `derive_verdict()` 仍回 NULL；agent claim 的 `A_verdict_label_after_fix` 也是 `NULL`。

   然而 `cd135b00e^` 完全沒有 `experiments/k1708/`；commit 將 `K1708_results.json` 以新增檔提交，diff 是 `1768 insertions`。因此 Git diff 觸及全部 stored numbers，沒有可比較的 pre-fix blob/hash。舊 code trace、mtime 和先前 review 敘述只能提供旁證，不能驗證「每個數字 untouched」。

6. **FAIL — 35/35 通過，但數個新測試不具 pre-fix 鑑別力。**

   唯讀模式實跑結果：`35 passed in 111.14s`。`test_codex_minimal_payload_does_not_return_supported` 確實會咬住原假陽性。

   但以下測試在 pre-fix logic 也會通過：

   - `test_stored_full_sample_verdict_is_still_null`：舊 verdict 本來就是 NULL，而且結果檔不存在時會 skip（`test_k1708.py:610-622`）。
   - `test_gate_holds_the_pre_registered_t_bar`：fixture 只提供新欄位，舊 derive 忽略後同樣返回 NULL（`test_k1708.py:535-541`）。
   - `test_inexact_nesting_flag_is_load_bearing`：同樣可因舊 logic 不讀新欄位而假通過（`test_k1708.py:544-548`）。
   - `test_regime_consistency_needs_both_regimes_scored`：亦只斷言 NULL，舊 logic 不讀 regime 即可通過（`test_k1708.py:581-585`）。

   Registry 測試也只驗證名稱與 boolean，沒有呼叫實際 forecast generator（`test_k1708.py:625-640`）。

7. **PASS — 沒有 quick artifact 殘留。**

   找不到 `K1708_results.quick.json`、quick PNG、quick CSV 或 `.tmp`。正式結果仍標示 `quick_mode=false`。

8. **PASS — README 已誠實撤回。**

   §8.1–8.2 明確承認 HAR_FIXED 不精確 nested，以及先前 `t>1.645`、無 multiple-testing correction 是缺陷（`README.md:228-294`）。§12 明確推翻先前「不改推論設計」的處置（`README.md:399-408`）。§15 亦揭露現行程式與 stored result code trace 不一致（`README.md:527-547`）。

BLOCKER-1: 新舊 gate 使用不同 comparator，故 `t>=3 ⊂ t>1.645` 無法證明整體 gate 不會把舊 NULL 轉正 :: experiments/k1708/K1708.py:1513,1560-1561  
BLOCKER-2: verdict 未核對 registry control 身分或重算 Holm，錯誤比較只要重新貼上 exact/reject 標籤仍可通過 :: experiments/k1708/K1708.py:2176-2182  
BLOCKER-3: commit 將完整 results 檔列為新增，沒有 pre-fix Git blob，因而無法驗證 stored numbers untouched :: experiments/k1708/K1708_results.json:1  
BLOCKER-4: 多個號稱 gate/nesting regression 的新測試在 pre-fix logic 也會返回 NULL 而通過 :: experiments/k1708/test_k1708.py:535-548  
VERDICT: FAIL
tokens used
140,183
1. **FAIL — gate 條件有綁定，但「整體 gate 是嚴格子集」不成立。**

   `assess_market()` 確實要求 exact flag、`t>=3`、Holm、QLIKE `<0`、MCS membership、兩個 regime 同號，缺一即失敗（`K1708.py:2174-2193`）。`t>=3` 本身也確實是 `t>1.645` 的嚴格子集。

   但新舊門檻套在不同比較上：新 gate 使用 own-restriction（`K1708.py:1513`），舊 gate 使用 HAR_FIXED（現為描述性，`K1708.py:1560-1561`）。因此可能有 `t_own>=3`、同時 `t_fixed<=1.645`；不能由臨界值子集推出整體 gate 不會把舊 NULL 轉正。README §8.2 的結論過度宣稱（`README.md:292-293`）。

   此外 verdict 只信任 payload 的 `exact_on_scored_object` 與 `holm.reject`，沒有核對 `control_series` 是否等於 registry，也沒有重算 Holm（`K1708.py:2176-2182`）。實測把 control 改成 `HAR_FIXED` 但保留 exact flag，仍得到 `CONDITIONAL_PASS`。

2. **PASS — Holm 實作正確且正常生產路徑有使用。**

   `holm_bonferroni()` 依 p-value 遞增排序，以 `α/(m-rank)` step-down，第一次失敗後全部停止拒絕（`K1708.py:1449-1462`）。`evaluate()` 對 exactly-nested family 的單尾 CW p-values計算並附回每列（`K1708.py:1524-1529`），`assess_market()` 要求 `holm.reject=True`（`K1708.py:2180`）。

3. **PASS — 生產路徑的 nesting 已實質修正。**

   Registry 為三個模型指定獨立 control（`K1708.py:1283-1302`）。`HAR_S_BM_AT_SIGMA_ETA_ZERO` 由原 HARSL hyperparameters 複製後將 `sig2_eta=0`，再直接呼叫 `forecast_harsl()`（`K1708.py:1893-1907`），不是 `forecast_ols_block()`。

   `cw_vs_benchmark_primary` 不存在於現行 executable code；HAR_FIXED 比較只寫入 `cw_vs_fixed_descriptive_not_nested`（`K1708.py:1550-1569`）。但第 1 項所述 metadata 驗證缺口仍允許人工「重新貼標」後進 verdict。

4. **PASS — regime 使用同一 nested pair。**

   每個 regime 的 `qlike_vs_own_restriction` 與 CW 都使用 registry control（`K1708.py:1664-1683`）；verdict 讀取同一欄位並要求至少兩個 regime 全為負（`K1708.py:2160-2189`）。

5. **FAIL — NULL 保持不變，但「結果檔未動」無法由 Git 證明。**

   `K1708_results.json` 內原 verdict 是 `NULL`，目前 `derive_verdict()` 仍回 NULL；agent claim 的 `A_verdict_label_after_fix` 也是 `NULL`。

   然而 `cd135b00e^` 完全沒有 `experiments/k1708/`；commit 將 `K1708_results.json` 以新增檔提交，diff 是 `1768 insertions`。因此 Git diff 觸及全部 stored numbers，沒有可比較的 pre-fix blob/hash。舊 code trace、mtime 和先前 review 敘述只能提供旁證，不能驗證「每個數字 untouched」。

6. **FAIL — 35/35 通過，但數個新測試不具 pre-fix 鑑別力。**

   唯讀模式實跑結果：`35 passed in 111.14s`。`test_codex_minimal_payload_does_not_return_supported` 確實會咬住原假陽性。

   但以下測試在 pre-fix logic 也會通過：

   - `test_stored_full_sample_verdict_is_still_null`：舊 verdict 本來就是 NULL，而且結果檔不存在時會 skip（`test_k1708.py:610-622`）。
   - `test_gate_holds_the_pre_registered_t_bar`：fixture 只提供新欄位，舊 derive 忽略後同樣返回 NULL（`test_k1708.py:535-541`）。
   - `test_inexact_nesting_flag_is_load_bearing`：同樣可因舊 logic 不讀新欄位而假通過（`test_k1708.py:544-548`）。
   - `test_regime_consistency_needs_both_regimes_scored`：亦只斷言 NULL，舊 logic 不讀 regime 即可通過（`test_k1708.py:581-585`）。

   Registry 測試也只驗證名稱與 boolean，沒有呼叫實際 forecast generator（`test_k1708.py:625-640`）。

7. **PASS — 沒有 quick artifact 殘留。**

   找不到 `K1708_results.quick.json`、quick PNG、quick CSV 或 `.tmp`。正式結果仍標示 `quick_mode=false`。

8. **PASS — README 已誠實撤回。**

   §8.1–8.2 明確承認 HAR_FIXED 不精確 nested，以及先前 `t>1.645`、無 multiple-testing correction 是缺陷（`README.md:228-294`）。§12 明確推翻先前「不改推論設計」的處置（`README.md:399-408`）。§15 亦揭露現行程式與 stored result code trace 不一致（`README.md:527-547`）。

BLOCKER-1: 新舊 gate 使用不同 comparator，故 `t>=3 ⊂ t>1.645` 無法證明整體 gate 不會把舊 NULL 轉正 :: experiments/k1708/K1708.py:1513,1560-1561  
BLOCKER-2: verdict 未核對 registry control 身分或重算 Holm，錯誤比較只要重新貼上 exact/reject 標籤仍可通過 :: experiments/k1708/K1708.py:2176-2182  
BLOCKER-3: commit 將完整 results 檔列為新增，沒有 pre-fix Git blob，因而無法驗證 stored numbers untouched :: experiments/k1708/K1708_results.json:1  
BLOCKER-4: 多個號稱 gate/nesting regression 的新測試在 pre-fix logic 也會返回 NULL 而通過 :: experiments/k1708/test_k1708.py:535-548  
VERDICT: FAIL

exec
/bin/zsh -lc "rg -n '"'^def |''^class |NESTING_REGISTRY|CW_T_PRE_REGISTERED|derive_verdict|legacy_derive_verdict|gate_transition_audit|provenance_check|registry_identity|t_p_inconsistency|build_nesting_controls|cw_vs_own|cw_vs_fixed'"' experiments/k1708/K1708.py
rg -n '"'^def test_|''^class |legacy_derive|derive_verdict|stored|recomput|assert .*'"\\[|assert .*reject|assert .*exact|gate|registry|provenance' experiments/k1708/test_k1708.py
rg -n '8\\.2|untouched|strict|嚴|comparator|legacy|provenance|rerun|gate|Holm|NULL' experiments/k1708/README.md" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-457427c2-k1708
 succeeded in 0ms:
133:# NESTING_REGISTRY and README section 8.1 for why the distinction is load-bearing.
148:def resolve_data_root() -> Path:
200:def sha256_file(path: Path) -> str:
208:def sha256_text(text: str) -> str:
212:def trace_file(path: Path) -> Dict:
226:def audit_us_intraday(intraday_dir: Path) -> Dict:
265:class MarketData:
273:def load_taifex(canonical_csv: Path) -> MarketData:
347:def build_har_design(md: MarketData) -> Tuple[pd.DataFrame, Dict]:
396:def build_common_ledger(design: pd.DataFrame) -> Tuple[np.ndarray, Dict]:
435:def ols_fit(X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, float, np.ndarray]:
450:def ols_predict_with_var(
464:def kalman_filter_har(
546:def kalman_mle(
660:def harsl_filter(
724:def _harsl_unpack(theta: np.ndarray) -> Tuple[np.ndarray, float, float, float]:
732:def harsl_mle(X: np.ndarray, y: np.ndarray, seed: int = SEED) -> Tuple[Dict, Dict]:
831:def forecast_harsl(
866:def lognormal_mean(mu: np.ndarray, var: np.ndarray, jensen: bool = True) -> np.ndarray:
879:def forecast_ols(
902:def forecast_ols_block(
929:def _init_block(X: np.ndarray, y: np.ndarray, upto: int) -> Tuple[np.ndarray, np.ndarray, float]:
946:def _init_state(
966:def forecast_kalman(
1023:def _qlike_from_log(mu: np.ndarray, var: np.ndarray, actual: np.ndarray, idx: np.ndarray) -> float:
1032:def select_roll_window(
1053:def select_discount(
1106:def select_hypers_at_refit(
1146:def _jsonable(v):
1160:def giacomini_white_test(loss1: np.ndarray, loss2: np.ndarray) -> Dict:
1195:def clark_west_test(actual: np.ndarray, f_small: np.ndarray, f_large: np.ndarray) -> Dict:
1283:NESTING_REGISTRY = {
1307:CONTROL_FOR = {m: v["control"] for m, v in NESTING_REGISTRY.items()}
1311:def hyper_for(i: int, table: Dict[int, Dict]) -> Dict:
1315:    ``build_nesting_controls`` -- and the tests that call it -- use the same
1334:def build_nesting_controls(
1355:    consume, i.e. exactly the controls named in ``NESTING_REGISTRY``.
1399:                        for spec in NESTING_REGISTRY.values()
1404:def schedule_artifact_diagnostic(
1449:                NESTING_REGISTRY[model]["exact_on_scored_object"]
1503:def boundary_diagnostic(tuning_log: List[Dict]) -> Dict:
1534:def holm_bonferroni(pvals: Dict[str, float], alpha: float) -> Dict[str, Dict]:
1559:def evaluate(
1596:    # model-vs-HAR_FIXED (see NESTING_REGISTRY).  This is the ONLY statistic the
1600:        spec = NESTING_REGISTRY.get(name)
1622:    out["cw_vs_own_restriction_primary"] = cw_own
1655:    out["cw_vs_fixed_descriptive_not_nested"] = cw_fixed
1656:    out["cw_vs_fixed_note"] = (
1757:                 "cw_vs_own_restriction": {},
1759:                 "cw_vs_fixed_descriptive_not_nested": {},
1765:            spec = NESTING_REGISTRY.get(name)
1773:                block["cw_vs_own_restriction"][name] = clark_west_test(
1777:            block["cw_vs_fixed_descriptive_not_nested"][name] = clark_west_test(
1797:def _mcs_block(losses: Dict[str, np.ndarray], n_boot: int) -> Dict:
1820:def _concentration(losses: Dict[str, np.ndarray], benchmark: str) -> Dict:
1841:def make_chart(out_png: Path, dates: np.ndarray, losses: Dict[str, np.ndarray],
1883:def write_json_atomic(path: Path, payload: Dict) -> None:
1896:def run_market(md: MarketData, n_boot: int, jensen: bool = True) -> Dict:
1960:    diagnostic_series, nesting_controls = build_nesting_controls(
2033:def main() -> int:
2178:            mkt["gate_transition_audit"] = gate_transition_audit(mkt)
2180:    payload["verdict"] = derive_verdict(payload)
2190:def registry_identity_violations(name: str, cw: Dict) -> List[str]:
2200:    ``NESTING_REGISTRY`` here, and the caller re-derives Holm from the p-values,
2206:    spec = NESTING_REGISTRY.get(name)
2208:        return [f"{name} has no NESTING_REGISTRY entry, so no comparison of it can be inference"]
2224:    inconsistency = t_p_inconsistency(cw)
2230:def t_p_inconsistency(cw: Dict) -> Optional[str]:
2250:def assess_market(mkt: Dict) -> Dict:
2264:    here -- identity from ``NESTING_REGISTRY``, Holm from the p-values -- so
2270:    cw_all = mkt.get("cw_vs_own_restriction_primary") or {}
2276:                "verdict consumes cw_vs_own_restriction_primary only; cw_vs_fixed_* is "
2296:            violations[name] = registry_identity_violations(name, cw)
2317:            #     against NESTING_REGISTRY, not against the payload's own flag
2342:            "registry_identity_violations": violations[name],
2358:        "rows_failing_registry_identity": relabelled,
2360:            f"rows {relabelled} do not match NESTING_REGISTRY, and no other model cleared "
2367:def derive_verdict(payload: Dict) -> Dict:
2459:LEGACY_CW_FIELDS = ("cw_vs_benchmark_primary", "cw_vs_fixed_descriptive_not_nested")
2460:NESTED_CW_FIELDS = ("cw_vs_own_restriction_primary",)
2463:def legacy_derive_verdict(payload: Dict) -> Dict:
2539:def gate_transition_audit(mkt: Dict) -> Dict:
2567:                          ("cw_vs_own_restriction", NESTED_CW_FIELDS)):
2629:def provenance_check_recorded_numbers(payload: Dict) -> Dict:
47:def test_features_at_row_t_ignore_rv_at_t():
63:        assert design_a[col].iloc[t] == pytest.approx(design_b[col].iloc[t], rel=1e-12), (
68:    assert design_a["rv_actual"].iloc[t] != pytest.approx(design_b["rv_actual"].iloc[t])
71:def test_rv_at_t_reaches_row_t_plus_one():
80:    assert design_a["x_d"].iloc[t + 1] != pytest.approx(design_b["x_d"].iloc[t + 1]), (
85:def test_censored_rv_never_clipped_into_a_feature():
86:    """RV = 0 is a limit-locked (censored) session: it must propagate as NaN, not 1e-16."""
93:    assert not np.isfinite(design["y"].iloc[200]), "censored day survived as a target"
95:    assert not np.isfinite(design["x_m"].iloc[205]), "censored day was silently absorbed"
98:def test_common_ledger_is_shared_by_construction():
102:    assert info["n_admissible"] == int(admissible.sum())
103:    assert info["identical_across_models"] is True
104:    # the first LAG_M rows can never be admissible: the monthly aggregate needs 22 days + a lag
105:    assert not admissible[: K.LAG_M].any()
112:def test_clark_west_sign_convention():
123:    assert res["t_stat"] > 1.645
124:    assert res["reject_at_5pct"] is True
125:    assert res["direction"] == "large_model_better"
128:def test_clark_west_is_correctly_sized_under_the_nested_null():
156:    assert rej < 0.11, f"CW over-rejects under H0: {rej:.3f} at a nominal 0.05"
159:def test_clark_west_adjustment_term_is_nonnegative():
166:    assert res["mspe_adjustment_term"] >= 0.0
173:def test_kalman_forecast_never_uses_its_own_observation():
189:    assert pm_a[t] == pytest.approx(pm_b[t], rel=1e-12), "forecast for t moved when y[t] moved"
190:    assert pv_a[t] == pytest.approx(pv_b[t], rel=1e-12)
192:    assert pm_a[t + 1] != pytest.approx(pm_b[t + 1], rel=1e-9)
195:def test_discount_one_is_effectively_the_restricted_model():
210:    assert np.std(np.diff(pm_vary[tail])) > np.std(np.diff(pm_flat[tail]))
213:def test_lognormal_mean_exceeds_naive_exp():
240:def test_filter_survives_burnin_rows_with_nan_regressors_and_finite_y():
249:    assert np.isfinite(y[0]), "probe is void unless y is finite on a burn-in row"
250:    assert not np.all(np.isfinite(X[0])), "probe is void unless X has NaN on that row"
260:    assert not np.isfinite(pm[0])
263:def test_kalman_mle_scale_ignores_nonfinite_rows():
277:    assert np.isfinite(info["loglik"]), "likelihood undefined -> starts were NaN again"
280:def test_harsl_mle_runs_on_a_burnin_design():
283:    assert abs(hyper["phi"]) < 1.0, "phi must stay inside the stationary region"
284:    assert hyper["sig2_eta"] >= 0.0
285:    assert np.isfinite(info["loglik"])
288:def test_harsl_forecast_never_uses_its_own_observation():
296:    assert pm_a[t] == pytest.approx(pm_b[t], rel=1e-12)
297:    assert pm_a[t + 1] != pytest.approx(pm_b[t + 1], rel=1e-9)
310:def test_discount_filter_gets_the_full_training_scale():
333:    assert disc["sigma2"] == pytest.approx(sigma2_full, rel=1e-12), (
336:    assert disc["sigma2"] != pytest.approx(sigma2_selection, rel=1e-9), (
341:    assert d_log["sigma2_selection_only"] == pytest.approx(sigma2_selection, rel=1e-12)
342:    assert d_log["sigma2_production_full_training"] == pytest.approx(sigma2_full, rel=1e-12)
345:def test_kf_mle_params_are_optimal_for_the_filter_that_forecasts():
352:    Replaying the stored parameters through the production filter moved the
368:    assert ll_production == pytest.approx(info["kf_mle"]["loglik"], rel=1e-9), (
374:def test_restricted_filter_reproduces_expanding_window_ols_exactly():
383:    Equality holds only because (a) the prior is conjugate to the filter -- P0 =
403:    assert not np.isfinite(pm[:init_upto]).any(), (
417:        assert pm[i] == pytest.approx(mu_o, rel=1e-8), (
421:        assert pv[i] == pytest.approx(var_o, rel=1e-8)
424:def test_harsl_zero_state_variance_collapses_to_fixed_coefficients():
434:    assert np.all(np.isfinite(pm_flat[ok]))
435:    assert np.corrcoef(pm_flat[ok], xb)[0, 1] > 0.9
439:# Verdict gate (2026-07-19 fix stage)
443:# at all, plus one market that genuinely clears.  The old derive_verdict counted
455:    """A CW row that matches NESTING_REGISTRY, built FROM the registry.
457:    Reading the identity fields out of the registry rather than retyping them
499:    legacy gate reads the HAR_FIXED comparison; the current gate reads the
501:    the legacy gate, which returns NULL by default -- and a test built on that
503:    the two gates disagree on the same artifact, so a disagreement is evidence.
522:    current gate must reject, and it is anchor B for the pre-fix reconstruction
525:    wrote; a new-schema payload would be invisible to the pre-fix gate and could
541:def test_codex_minimal_payload_does_not_return_supported():
550:    v = K.derive_verdict(payload)
551:    assert v["label"] == "NULL", (
555:    assert v["qualified_markets"] == []
558:def test_market_with_no_metrics_cannot_qualify():
560:    v = K.derive_verdict(_codex_seed_payload())
561:    assert v["label"] != "SUPPORTED", (
565:    assert v["qualified_markets"] == ["TAIFEX_TX"]
566:    assert v["label"] == "CONDITIONAL_PASS"
567:    assert v["market_assessment"]["SPY"]["qualifies"] is False
570:def test_two_genuinely_passing_markets_still_reach_supported():
571:    """The gate is tighter, not broken: real cross-market evidence still passes."""
573:    v = K.derive_verdict(payload)
574:    assert v["label"] == "SUPPORTED"
575:    assert sorted(v["qualified_markets"]) == ["SPY", "TAIFEX_TX"]
578:def test_descriptive_cw_vs_fixed_cannot_qualify_a_market():
582:    v = K.derive_verdict({"markets": {"TAIFEX_TX": mkt}})
583:    assert v["label"] == "NULL"
584:    assert "descriptive" in v["market_assessment"]["TAIFEX_TX"]["reason"]
592:def test_every_declared_condition_is_load_bearing(break_it, label):
600:    the payload any more, because the verdict recomputes it; and at t >= 3 it
614:    v = K.derive_verdict({"markets": {"TAIFEX_TX": mkt}})
616:    assert conds[label] is False
617:    assert v["label"] == "NULL", f"condition {label} is declared but does not bind"
620:def test_no_admissible_market_is_fail_no_data():
621:    v = K.derive_verdict({"markets": {"SPY": {"status": "FAIL_NO_DATA"},
623:    assert v["label"] == "FAIL_NO_DATA"
626:def test_holm_bonferroni_step_down():
629:    assert out["a"]["reject"] is True and out["a"]["holm_threshold"] == pytest.approx(0.05 / 3)
630:    assert out["b"]["reject"] is True and out["b"]["holm_threshold"] == pytest.approx(0.05 / 2)
631:    assert out["c"]["reject"] is False
636:    assert stepped["a"]["reject"] is False, "0.03 > 0.05/2"
637:    assert stepped["b"]["reject"] is False, (
642:def _stored_payload():
650:def test_stored_full_sample_verdict_is_still_null_and_says_why():
651:    """The anchor: this fix changes the gate, never the numbers.
654:    asserted NULL, and NULL is what the stored payload returns under BOTH gates,
659:    The stored artifact predates the fix.  It carries ``cw_vs_benchmark_primary``
660:    and no own-restriction comparison at all, so the current gate returns NULL
665:    payload = _stored_payload()
666:    v = K.derive_verdict(payload)
667:    assert v["label"] == "NULL"
671:        "the stored artifact now has the nested field: it has been rerun, and this test's "
675:    assert "no exactly-nested Clark-West comparison" in reason, reason
678:def test_legacy_reconstruction_reproduces_the_stored_verdict_block():
681:    The stored ``verdict`` block IS the pre-fix function's own output on the real
683:    agreement is what licenses ``legacy_derive_verdict`` to stand in for them in
686:    payload = _stored_payload()
687:    stored = payload["verdict"]
688:    got = K.legacy_derive_verdict(payload)
693:        assert got[field] == stored[field], (
695:            f"{got[field]!r} vs {stored[field]!r}"
699:def test_legacy_reconstruction_reproduces_the_reviewers_false_positive():
704:    reconstruction of the gate that produced it.
707:    assert K.legacy_derive_verdict(payload)["label"] == "SUPPORTED", (
709:        "a faithful stand-in for the pre-fix gate"
711:    # ... and the current gate closes it: the same payload, the opposite answer.
712:    assert K.derive_verdict(payload)["label"] == "NULL"
715:def test_every_state_space_model_has_an_exact_nesting_control():
716:    """The registry is the thing that decides what may become inference.
724:        assert spec["exact_on_scored_object"] is True
725:        assert spec["control"] not in ("HAR_FIXED", K.SCHEDULE_COST_CONTROL), (
748:def test_nesting_controls_are_produced_by_the_declared_forecast_map():
749:    """Round-2 BLOCKER-4b: the registry test must CALL the generator, not read its label.
754:    while the registry said otherwise, and no string comparison could have seen
756:    dereferences the registry's ``forecast_map`` NAME and applies the registry's
764:    assert set(controls) == {s["control"] for s in K.NESTING_REGISTRY.values()}
785:                     f"{spec['restriction']} -- the registry's label and the production "
790:def test_each_restriction_actually_bites():
823:def test_evaluate_wires_the_nested_cw_and_only_the_nested_cw():
841:    assert set(out["cw_vs_own_restriction_primary"]) == set(K.STATE_SPACE_MODELS)
843:        assert row["control_series"] == K.NESTING_REGISTRY[name]["control"]
844:        assert row["exact_on_scored_object"] is True
849:        "the old field name is back; derive_verdict must not be able to find it"
855:            assert set(blk["qlike_vs_own_restriction"]) == set(K.STATE_SPACE_MODELS)
858:def test_controls_never_enter_the_model_ranking():
875:    assert set(out["mean_qlike"]) == set(forecasts)
876:    assert not (set(out["mcs_qlike"]["superior_set"]) & set(controls))
880:# BLOCKER-4 (round 2): the gate tests must DISCRIMINATE, not merely pass
885:# schema is INVISIBLE to the old gate (different field name), so the old gate
890:# and the test asserts BOTH labels: the current gate must reject it, and the
891:# reconstructed pre-fix gate must have accepted it.  A test that stops
917:    # (case, mutation, nested_t, why the current gate must reject it)
931:def test_gate_regression_cases_actually_discriminate(case, mutate, nested_t, why):
932:    """Each case: current gate says NULL, reconstructed pre-fix gate said SUPPORTED."""
935:    assert K.derive_verdict(payload)["label"] == "NULL", f"current gate failed to reject: {why}"
936:    assert K.legacy_derive_verdict(payload)["label"] == "SUPPORTED", (
937:        f"case {case!r} does not discriminate: the pre-fix gate would have rejected it too, "
942:def test_the_differential_fixture_is_not_broken_by_construction():
943:    """Guard on the guard: unmutated, the fixture must genuinely pass the current gate.
949:    v = K.derive_verdict(_differential_payload())
950:    assert v["label"] == "CONDITIONAL_PASS", v.get("rationale")
951:    assert v["qualified_markets"] == ["TAIFEX_TX"]
952:    # and the pre-fix gate is more permissive on the SAME payload
953:    assert K.legacy_derive_verdict(_differential_payload())["label"] == "SUPPORTED"
966:def test_a_row_that_contradicts_the_registry_cannot_qualify(field, bad_value):
970:    v = K.derive_verdict({"markets": {"TAIFEX_TX": mkt}})
972:    assert v["label"] == "NULL"
974:    assert assessment["rows_failing_registry_identity"] == ["HAR_KF_MLE"]
975:    violations = assessment["models"]["HAR_KF_MLE"]["registry_identity_violations"]
979:def test_exact_flag_pasted_onto_a_registry_mismatch_still_fails():
986:    v = K.derive_verdict({"markets": {"TAIFEX_TX": mkt}})
987:    assert v["label"] == "NULL"
988:    assert v["market_assessment"]["TAIFEX_TX"]["models"]["HAR_KF_MLE"][
992:def test_t_and_p_must_come_from_the_same_test():
996:    v = K.derive_verdict({"markets": {"TAIFEX_TX": mkt}})
997:    assert v["label"] == "NULL"
999:        "registry_identity_violations"]
1003:def test_a_relabelled_row_is_excluded_from_the_holm_family():
1009:    v = K.derive_verdict({"markets": {"TAIFEX_TX": mkt}})
1011:    assert assessment["holm_family_verified"] == ["HAR_KF_MLE"], (
1016:def test_stored_holm_flag_is_recomputed_not_trusted():
1020:    v = K.derive_verdict({"markets": {"TAIFEX_TX": mkt}})
1023:    assert model["conditions"]["holm_rejects"] is True, (
1024:        "the verdict took the payload's word for Holm instead of recomputing it"
1026:    assert model["holm_payload_flag_disagrees"] is True, "the disagreement was not recorded"
1027:    assert v["label"] == "CONDITIONAL_PASS"
1050:def test_holm_cannot_bind_at_the_pre_registered_bar():
1053:    A claim like this in prose is where a gate quietly stops being what it says
1059:        assert all(h["reject"] for h in holm.values()), (
1064:def test_holm_starts_biting_the_moment_the_t_bar_is_relaxed(monkeypatch):
1070:    hand-set ``holm.reject = True``.  Only the recomputed Holm stands between
1077:    assert all(r["t_stat"] > 1.645 for r in mkt["cw_vs_own_restriction_primary"].values())
1082:    v = K.derive_verdict({"markets": {"TAIFEX_TX": mkt}})
1083:    assert v["label"] == "NULL", "Holm did not bind after the t bar was relaxed"
1086:        assert conds["cw_t_at_or_above_bar"] is True
1087:        assert conds["holm_rejects"] is False
1091:# BLOCKER-1 (round 2): the gate transition, as facts rather than an argument
1094:def test_bar_move_is_a_subset_when_the_comparator_is_held_fixed():
1101:        audit = K.gate_transition_audit(mkt)["cw_vs_HAR_FIXED"]
1102:        assert audit["bar_move_is_a_subset"], t_stats
1105:def test_comparator_move_is_not_orderable_in_either_direction():
1108:    README 8.2 used to argue the corrected gate was strictly tighter. It is not:
1113:    # new gate positive, old gate negative: t_own >= 3 while t_fixed <= 1.645
1115:    assert K.derive_verdict(new_only)["label"] == "CONDITIONAL_PASS"
1116:    assert K.legacy_derive_verdict(new_only)["label"] == "NULL"
1118:    # old gate positive, new gate negative: the reverse crossing
1120:    assert K.derive_verdict(old_only)["label"] == "NULL"
1121:    assert K.legacy_derive_verdict(old_only)["label"] == "SUPPORTED"
1124:def test_gate_audit_reports_the_stored_payload_as_not_comparable():
1125:    """On the stored artifact the comparison cannot be made, and must say so.
1127:    This is the honest content of BLOCKER-1: the corrected gate has never been
1132:    payload = _stored_payload()
1133:    audit = K.gate_transition_audit(payload["markets"]["TAIFEX_TX"])
1135:    assert audit["cw_vs_HAR_FIXED"]["evaluable"] is True
1136:    assert audit["cw_vs_HAR_FIXED"]["clears_t_gt_1.645"] == []
1137:    assert audit["cw_vs_own_restriction"]["evaluable"] is False
1138:    assert audit["cross_comparator_comparison"]["possible"] is False
1142:# BLOCKER-3 (round 2): provenance by external corroboration, since git cannot
1145:def test_stored_numbers_still_match_the_20260717_review():
1148:    Git cannot show the stored numbers are untouched -- experiments/k1708/ is an
1154:    report = K.provenance_check_recorded_numbers(_stored_payload())
1156:    assert not failed, f"stored numbers no longer match the 2026-07-17 review: {failed}"
1157:    assert report["all_match"] is True
1158:    assert len(report["checks"]) == 6
135:- **週/月 aggregate 在 level 取平均再取 log**（Corsi 2009 慣例），且 `min_periods` = 窗長 →
225:  只會讓 NULL 結論**更保守**，不會製造假的 null。同一模擬也確認 unadjusted MSPE 在
241:所以即使在 δ=1 —— **係數路徑**確實等於 expanding OLS（`test_restricted_filter_reproduces_expanding_window_ols_exactly` 驗過）——
263:**為什麼這不是為了配合數字**：新設計下 verdict 讀的是 `cw_vs_own_restriction_primary`，
264:而**已存檔的 full-sample run 沒有這個欄位**（它是本次新增的），所以 stored run 依舊 NULL ——
269:## 8.2 哪個 gate 治理 verdict（2026-07-19 方法論決定）
273:Review 判為 verdict-shopping 風險，**這個判斷是對的**：揭露誠實不會讓較寬的 gate 變成等價的 gate。
284:| 多重比較 | Holm–Bonferroni，α=0.05，family = 精確 nested 的比較 | 3 個模型同時被檢定 |
288:brief 的 |t| ≥ 3 沿用該慣例。**t ≥ 3 時 Holm 不是 binding constraint**（單尾 p ≤ 0.00135，
290:任何人日後放寬 t 門檻，Holm 會立刻開始咬。常數在 `GATE_T_CRITICAL` / `GATE_FAMILY_ALPHA`。
292:### 8.2.1 方向性：前一版的「嚴格更緊」宣稱已撤回（2026-07-19 round 2）
294:**撤回的說法**：本節前一版寫「新 gate 嚴格緊於前一版（t≥3 ⊂ t>1.645），所以這次修正不可能把
295:NULL 推成非 NULL」。**這個論證無效**，round-2 review 判得對。
297:**為什麼無效**：這次修正**同時動了兩件事** —— 門檻（1.645 → 3.0）**和** comparator
306:| **門檻** 1.645 → 3.0（comparator 固定） | ✅ 嚴格子集 | `{t ≥ 3} ⊂ {t > 1.645}`，對任何 t 向量成立；`test_bar_move_is_a_subset_when_the_comparator_is_held_fixed` 用 200 組隨機 t 釘住 |
307:| **併行條件** 加 Holm / MCS / regime / per-market | ✅ 單調收緊 | 加 conjunct 只能縮小通過集合 |
308:| **comparator** vs `HAR_FIXED` → vs own restriction | ❌ **兩個方向都不可排序** | `test_comparator_move_is_not_orderable_in_either_direction` 明確造出兩個方向的交叉 |
310:**誠實的結論**：這次修正在**門檻與併行條件上嚴格收緊**，在 **comparator 上是橫移**。
311:「修正後的 gate 不可能把 stored NULL 推成非 NULL」**不成立為論證**；而在 stored artifact 上
313:那組比較，own-restriction 的對照序列**從未被保存**（不在 results.json，也不在 forecast ledger）。
314:**新口徑的 gate 從未在真實資料上被評估過**，要補這個表必須重跑（§14，本階段不重跑）。
316:**取代論證的機械物件**：`gate_transition_audit()` 對任一 market payload 並列輸出兩個 gate 的
318:在 stored payload 上它回報 `cross_comparator_comparison.possible = false`
319:（`test_gate_audit_reports_the_stored_payload_as_not_comparable` 釘住）。
322:gate 並列表寫進每個 market 的 `gate_transition_audit`。
350:| 2 | CW 單尾 t ≥ 3.0（事前註冊門檻，§8.2） | `cw_t_at_or_above_bar` |
351:| 3 | Holm–Bonferroni 在 nested family 內拒絕 | `holm_rejects` |
359:- `NULL`：沒有市場滿足全部條件。
367:`SUPPORTED`、qualified=`['TAIFEX_TX','SPY']`，新邏輯回 `NULL`、qualified=`[]`）。
373:gate（GW 在 nested 下需要有限估計窗，實際 fit 出來的 δ=1.0 / Q=0 沒有，見 §12）。
460:prior 用 filter 自己的 σ² 縮放（conjugate），因此：
463:  `test_restricted_filter_reproduces_expanding_window_ols_exactly` 逐點比對 pred mean 與
545:完整性 gate：
548:uv run python scripts/experiment_gates.py run --path experiments/k1708
553:## 15. 已存檔 full-sample run 與本次修正的關係（provenance，2026-07-19）
561:   provenance 依然誠實；但它**不再等於**現行檔案。要驗證現行程式碼請重新 pin。
562:2. **`markets.*.verdict` 相關欄位是舊 gate 的產物。** 存檔裡的
564:   現行 `derive_verdict` 讀這份 payload 仍然回 **NULL**（`test_stored_full_sample_verdict_is_still_null`
566:   精確 nested 的比較（`cw_vs_own_restriction_primary` 是本次新增欄位）」。**兩個理由都成立。**
568:   `cw_vs_own_restriction_primary`、`cw_holm_family`、regime 層的
569:   `qlike_vs_own_restriction`。要拿到新口徑的數字**必須重跑**。
571:**為什麼不順手重跑補上**：修正 gate 的同一輪裡重算被 gate 評判的數字，會讓「數字有沒有
576:`HAR_FIXED` 換成自己的限制，而 `qlike_vs_own_restriction` 已知比
578:**新的 t 值沒有理由更大**，門檻又從 1.645 升到 3.0 —— 所以預期仍是 NULL。
579:若重跑後出現非 NULL，那是需要當成異常去追的訊號，不是好消息。

