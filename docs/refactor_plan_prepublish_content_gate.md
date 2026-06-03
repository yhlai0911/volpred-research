# Refactor Plan — Pre-publish Content-vs-Source Gate（3-STRIKE）

**Trigger 日期**：2026-06-03（台灣時間）
**觸發 incident**：mile_31b2b0bb（K1413 AI 五層產業鏈文）發佈後 Codex 24h-review 回 **FAIL** — 「截至 6 月初晶片層最抖」與 source `k1413_results.json` 衝突（最新最抖是 L3 基礎設施 64.6%，非晶片 42.4%）；「五層」prose vs 實作 4 籃；「四層同步觸頂」vs L4L5 晚到 5/16。文章已上線 + FB 雙發才被發現。

## 為何是 3-STRIKE（同類復發 ≥4 次）

「reader-facing 文章發佈後才被 Codex 24h-review 抓到 content-vs-source FAIL」是同一根因、同一症狀、同類 bug 的反覆發生：

| # | 日期 | 文章 | FAIL 類型 |
|---|---|---|---|
| 1 | 2026-05-06 | mile_291f9029（K263） | 數字 / lookahead 與 source 不符 |
| 2 | 2026-05-18 | mile_7ba7ee54 | 策略 spec 混用（NW t 來自 Strategy A，OOS 來自 C） |
| 3 | 2026-05-27 | mile_91af7c48（K562） | headline Sharpe 不在任何 results.json；patch 未 commit |
| 4 | 2026-06-03 | mile_31b2b0bb（K1413） | 現況結論與 source 衝突 + 框架/觸頂描述失準 |

**2026-05-19 已有一次 3-STRIKE TRIGGER**（publish pipeline 缺 verify gate），但當時只修了 **liveness**（URL 是否回 200，`live_verify.py`），**沒修 content 正確性**。對 content FAIL 的歷史「對策」一直是「**更嚴格執行發佈後 24h-rule**」= 表面補丁：review 永遠在 publish 之後，錯誤照樣先進線上 + FB，只能事後 retract / 更正。

## 三層診斷（Three-Strike Rule）

### 1. 底層邏輯（domain model 錯誤）
- **「正確性驗證」被放在 publish 之後（24h Codex review）**。對 trending「立刻發」文章尤其致命：發佈 → FB 雙發 → 數小時後才 review → 事後更正。正確的 domain model：**對外發佈前，cited 數字與結論必須先對得上 cited results.json**（research 誠實的 pre-condition，不是 post-hoc 稽核）。
- 既有 `_audit_general_content` 只檢 audience/學術關鍵詞，**不檢 numeric-vs-source**。

### 2. 流程（workflow 缺陷）
- publish 流程 gate 順序：dedup → audience audit → emdash/table sanitize → append → （published 時）live_verify。**缺一層 content-vs-source provenance gate**。
- 更正流程也壞：見根因 B。

### 3. 程式架構（silent-sync — 根因 B）
- `supabase_sync.py` incremental 用 **timestamp-gated** 選變更（`published_at/created_at/updated_at > last_sync_ts`）。直接改 `feed.json` content 而沒 bump `updated_at` → **silently 不同步**。2026-05-27 patch 只多加一個 timestamp 欄位（surface patch），本次更正一開始也被 silent-skip（report `articles:1` 卻沒寫到該列），bump `updated_at` 後才推上去。正解：**content-hash-based**，任何 syncable 欄位變更都偵測，與 timestamp 脫鉤。

## 重構方案

### Refactor A — Pre-publish content-vs-source gate（headline fix，根因 A）
新增 `src/volpred/publisher/prepublish_audit.py`：

- **Tier 1（deterministic，~ms）— numeric provenance**：
  - 從文章 content 抽出所有數值 token（百分比 / 小數 / 整數，含千分位）。
  - 從 cited K-id（tags 的 `K\d+` + content/details.experiment_refs）載入 `experiments/<k>/<k>_results.json`，遞迴攤平所有數值。
  - 對每個「**帶統計語境**」的文章數值（鄰近 Sharpe/t/p/波動率/相關/勝率/% 等關鍵詞），檢查是否在 source 數值集合內（相對容差 + 常見單位換算 0.42↔42%）。
  - **找不到對應 source 數字** → finding（A1：fabrication / stale，如 K562）。
- **Tier 2（fast LLM，~秒）— conclusion consistency**：
  - 用 `agy -p`（gemini-flash，免費、快）餵「文章關鍵結論句 + source 攤平摘要」，問「是否有結論與 source 衝突 / 遺漏更高值導致 superlative 錯誤 / 混用不同 spec」。
  - 捕捉 A2（K1413 現況最抖判斷錯）/ A3（mile_7ba7ee54 策略混用）。
  - agy 不可用 → degrade 成 warn-only，不阻塞（但記 log）。
- **Wiring（`publisher.publish_milestone`）**：在 dedup 之後、`status` flip 之前呼叫 `audit_content_provenance()`。
  - Tier-1 hard finding（cited 數字不在 source）→ 預設 **raise / block**（與 `audit_strict` 一致；trending 立即發亦 block，因為這是 fabrication 等級）。
  - Tier-2 finding → **warn + `content_audit_flagged=True` stamp + send_alert**，不硬擋（避免 LLM false-positive 卡住時效文），但主線程 / boss inbox 立即可見。
  - 無 cited K-id（純市場觀察、無實驗數字）→ skip Tier-1，仍可跑 Tier-2。

### Refactor B — content-hash-based incremental sync（根因 B）
改 `supabase_sync.py` incremental：

- sync state 額外存 per-slug `content_hash`（hash 全部 syncable 欄位：content/title/excerpt/status/audience/category/details）。
- 選變更條件改為：`hash != state[slug]` **OR** 既有 timestamp 條件（向後相容，第一次 fallback full）。
- 任何 content 變更（即使沒 bump timestamp）都會被偵測 → 消滅整類 silent-skip。

## 廢棄面（不留兩套並行）
- **不廢** `live_verify.py`（liveness）與 24h Codex review（最後防線 backstop）；它們與 pre-publish gate 是縱深防禦不同層，保留。
- **廢棄**「靠更嚴格執行 24h-rule 來防 content FAIL」這個**唯一 reliance**：pre-publish gate 成為 primary，24h-rule 降為 backstop。
- supabase_sync incremental 的「純 timestamp 篩變更」邏輯由 hash-based 取代（timestamp 僅作 fallback / first-run 全量）。

## 驗證 gate（regression 必覆蓋四次 incident 觸發條件）
- `tests/test_prepublish_audit.py`：
  - K562 case：headline 數字不在 source → Tier-1 block。
  - K1413 case：數字都在 source 但結論挑錯最大值 → Tier-2 flag（mock LLM）。
  - 無 cited K-id 純觀察文 → 不誤擋。
  - 數字單位換算 0.42↔42% 不誤報。
- `tests/test_supabase_sync_hash.py`：
  - content 改但 timestamp 不變 → hash-based 偵測為 changed（舊 timestamp 邏輯會漏）。
  - 無變更 → 不重推（idempotent）。
- production-path：本次 mile_31b2b0bb 更正已端到端驗證（feed → DB → 線上 60s cache 自癒）。

## Commit 慣例
重構 commit 開頭 `refactor(3-strike): prepublish content gate + hash sync`，便於日後 grep。
