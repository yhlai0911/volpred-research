# K528 round 6 verdict

verdict: **PASS (fallback reviewers)** — *not* a primary-path Codex PASS
reviewed_commit: `52fde3f49`
reviewed_at: 2026-07-21（台灣時間）

---

## ⚠️ 這份裁決的效力範圍（先讀這段）

**primary-path Codex 沒有跑成功。** `codex exec` 回：

```
ERROR: You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage
to purchase more credits or try again at Jul 25th, 2026 1:30 PM.
```

這是**帳號額度**問題不是 CLI/config 問題 —— `codex --version` = `codex-cli 0.144.6`、
`codex login status` = `Logged in using ChatGPT`，兩項都正常。依
`.claude/rules/experiments.md` 的 fallback 條款改派獨立 reviewer。

依同一份規則：**「Subagent fallback PASS ≠ primary-path Codex PASS」**（K1259 前例：
fallback 判 PASS 後，Codex 在同一份 code 上找出 12 個 residual）。因此：

> **這份 PASS 不足以支撐 certify 或 merge。**
> Codex 額度 2026-07-25 恢復後必須用 primary path 重跑 round 6。

本輪已依 dispatch 硬性禁令：**未 merge、未 certify、未寫 knowledge.json**。

---

## 逐條裁決

| Blocker | 裁決 | 依據 |
|---|---|---|
| **B1** Friday estimand 錯置 | **PASS** | 全 claim surface 已統一為 session 口徑；243/237/6 三個數字逐處勾稽 |
| **B2** raw+selected 同步截短 | **PASS** | 要求月份由「請求視窗」推導，截短的 feed 動不到該量尺 |
| **B3** 價格尾端截短不 fail closed | **PASS** | 覆蓋 / ffill 年齡 / `n_outside_price_sample==0` 三道 gate，無 exception 吞噬 |
| **B4** 未定義 family 卻稱顯著 | **PASS** | family 揭露、雙口徑並列、README 不再授權 pre-registration 宣稱 |
| **殘留 gap**（single-month upstream truncation） | **CLOSED** | 由 B2 的 endpoint expectation 真正關閉，非僅揭露 |

### B1 — PASS

**裁決重點：沿用 session estimand（relabel）而非改用 release weekday 重跑，理由成立。**

被比較的是 **session 報酬**，被固定的是**該 session 的星期效應**。改用 release weekday
篩 243 筆，會把 6 筆 Good Friday 的**週一報酬**丟進純週五對照組 —— 那正好把要修的
星期別污染放回來。reviewer 特別針對「這是不是為了避免重跑而找的說辭」作攻擊，判定不是。

已修正的殘留（round-5 收件審查判 FAIL 的部分）：

- `build_article_correction.py` 七處讀者面字串（更正文產生器，`--apply` 由主線程對線上文章執行）
- `:108` 的錯話「253 場裡有 237 場落在週五」→ 243 場**發布日**在週五 / 6 場 Good Friday 休市 / 237 場**在週五盤**被消化

**本輪額外發現收件審查漏算**：retired 口徑不只在產生器，也在**產生出來的結果檔**裡 ——
`k528_nfp_event_study_results.json` 的 `conclusions[1]`、`B_nfp_vs_friday.claim_scope`，
以及 `k528_nfp_official_dates_results.json` 的 correction-audit note。收件審查曾宣稱
結果檔「CLEAN and single-estimand」，該宣稱不成立。已改 `.py` 字串來源後**重跑重新產生**，
未手改任何 JSON（reviewer 自行重跑比對確認）。

### B2 / B3 — PASS（未繼承前一輪結論，重新攻擊）

round-6 reviewer 被明確要求**不要繼承**收件審查對 B2/B3 的 PASS，自行重攻。
特別檢查 `KNOWN_MISSING_MONTHS` allowlist 與端點期望合起來的後門：`dropped` 檢查
（raw − selected）未扣除 allowlist，故惡意路徑必須動到 allowlist 本身，
而那是會出現在 git diff 上的可審查改動 —— 無 silent bypass。

### B4 — PASS

README:203 原授權下游寫「**事先聲明的**六項 confirmatory family」，與同檔 :199 及
`multiplicity.pre_registered=false` 直接矛盾。該行是發佈 agent 會整句複製的句子，
所以矛盾會往外傳。已改為不宣稱預先登記，並要求同時揭露「對全部 22 個 outputs 校正後不拒絕」。
`conclusions[1]` 的 `rejects at 5%` 亦改為明標 nominal 並指向 `multiplicity`。

三種讀法並列（皆照實報）：

| 口徑 | 值 | 判定 |
|---|---|---|
| Nominal | p = 0.02085 | 拒絕 |
| Holm，confirmatory family（6） | p = 0.04171 | 拒絕 |
| Holm，全部 inferential outputs（22） | p = 0.37538 | **不拒絕** |

**不可回溯修復的部分**（如實記錄，非缺陷隱瞞）：family 定義在看到資料**之後**
（git：family 標籤首見於 `17f12d16c`，比重跑 `e42dc25ad` 晚約 26 小時）。
六個 endpoint 本身首見於 `461d23ae4`，早重跑三個月 —— 這是 Codex 最小修法要求的部分，成立。

---

## 新發現的缺陷

**無。**

---

## Non-blocking observations

1. **yfinance 浮點漂移**：重跑會重新下載，adjusted-close 非 byte-stable。
   4075 個 numeric leaf 中 1322 個改變，最大相對變化 **1.65e-3**（發生在一筆接近零的
   `event_return`，大的是相對值不是絕對值）。**所有呈報數字在呈報精度上完全未動**
   （1.1890x、p=0.0209、p=0.1121、2.03x、r=0.440）。此實驗**不是 bit-reproducible，
   只是 reproducible to reported precision** —— 已主動揭露，reviewer 裁為 non-blocking。

2. **兩個新 gate 是釘字串**：`test_reader_facing_surfaces_...` 與
   `test_readme_does_not_sanction_...` 以字串比對防守（`在週五公布`、`事先聲明`），
   同義詞（如 `預先登記`）在理論上可繞過。第三個 gate
   `test_friday_estimand_pins_release_vs_session_and_names_the_good_fridays` 是
   **結構性**的（驗 243/237/6 的勾稽，並逐筆確認每個具名發布是「週五發布 / 週一 session」），
   不受此限。reviewer 判定此界限可接受。

---

## 反空洞實測（三個新 gate 都做過）

「兩邊都會過的測試等於沒有測試」。每個 gate 都把帶缺陷的產物擺回去確認轉紅，之後還原：

| Gate | 餵入 pre-fix 產物 | 結果 |
|---|---|---|
| `test_friday_estimand_pins_release_vs_session_...` | `73dca01d0` 的結果檔（無 friday_estimand 區塊） | **1 failed** ✅ |
| `test_reader_facing_surfaces_do_not_resurrect_...` | `17f12d16c` 的 `build_article_correction.py` | **1 failed** ✅ |
| `test_readme_does_not_sanction_a_pre_registration_claim` | `17f12d16c` 的 `README.md` | **1 failed** ✅ |

三者在現況 HEAD 全綠；還原後工作區經 `git status` 驗證乾淨。
agy reviewer **獨立重跑**了第二項（對 `17f12d16c` 產生器），自行看到 `:118` / `:168` / `:200`
被標記 —— 未採信本輪敘述。

---

## Reviewer A：agy（Antigravity CLI 1.1.4，非 Claude 模型）

verdict: **PASS**（B1/B2/B3/B4/殘留 gap 全 PASS，新缺陷 0）
完整裁決：`storage/ops/codex_reviews/k528_round6_verdict_agy.md`

**實際執行過（非讀碼推論）**：

- `pytest` 三個 k528 suite → `93 passed`
- 匯入 FRED key **重跑主實驗腳本**，diff 重新產生的 JSON → 確認僅 yfinance 浮點漂移、
  統計結論與 p-value 精度未翻轉，隨後還原工作區
- 對 `17f12d16c` 的產生器重跑 reader-facing gate → 看到 `:118` / `:168` / `:200` 觸發
- `build_article_correction.py` dry run → `validated 19/19 replacements, each matched exactly once`

---

## 範圍外改動裁決

1. **`test_missing_month_inside_the_observed_span_fails` 放寬 regex**（上一輪）——
   新端點期望比舊 span 檢查更早觸發，原測試 match 錯字串而轉紅（仍有 raise，只是換了層）。
   同 commit 新增 `test_span_gap_check_still_fires_where_the_endpoint_expectation_cannot`，
   用一個結束於 `2024-03-10` 的視窗讓端點期望**無法**要求 2024-03，逼 span 檢查成為觸發者。
   **裁決：真正的獨立覆蓋，不是放寬。**

2. **`"Friday NFP" in claim_scope` 斷言被取代**（本輪）—— 該字串本身就是 B1 判掉的歧義
   （243 與 237 都讀得通）。改為釘 session 措辭、**並額外**要求明文否定 release-dated 讀法，
   一條變三條。**裁決：收緊，不是放寬。**

---

## 下一步（給主線程）

1. **2026-07-25 之後**用 primary-path Codex 重跑 round 6 —— 這是 certify/merge 的前提。
2. Codex 判 PASS 後才走 `experiment_gates.py verdict-template` → certify → `merge_worktree.sh`。
3. 更正文（`mile_35eef830`）已 **validated 但未 apply**；`--apply` 須由主線程從 repo root 執行
   （`storage/reports/feed.json` 是 worktree 不可寫的共享狀態）。
4. Apply 後重製兩張內文圖與兩張懶人包圖 —— 目前仍是 proxy 期數字，文中已有可見說明。
