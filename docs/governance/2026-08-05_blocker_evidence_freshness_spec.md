# 規格：`blocker_evidence: fresh|stale` — blocker_verified_at 判準的機械化

- 立案：運營經理 D38 §3（`item_20260805T111716619606Z`）
- 執行：治理部，2026-08-05T11:35Z
- **收編對象：`paper-submission-pipeline` 既有讀取路徑。不開新 checker、不加 cron、不加 CI job。**

---

## 0. 這個規格解決什麼

`paper_pipeline_status.json` 的 `blocker` 是**敘事欄位**：有人寫過一次，之後沒有任何動作會讓它更新。
2026-08-05 實例：論文部引用 `taiwan-vt.blocker` 下裁決，三項理由有兩項在一個月前就已被做完
（`blocker_verified_at` 停在 07-05，followup 07-06 與 07-13 落地）。**結論方向仍正確，但理由過期。**

規格的目的**不是擋人**，是讓讀者知道自己拿的是證據還是留言。

---

## 1. 判定規則（v4，依序求值，先命中先決定）

輸出欄位 `blocker_evidence ∈ {fresh, stale}`，掛在既有 pipeline 讀取路徑的輸出上。

**規則 1（事件式主判準）**
`blocker_verified_at` 早於下列任一檔的最後 commit → `stale`：

```
paper/<name>/main*.tex        (canonical manuscript)
paper/<name>/reproduce.py
paper/<name>/reproduce_report.json
paper/<name>/experiments.md
paper/<name>/data_sources.md
paper/<name>/review_history*   (round 記錄)
```

**只比這六類，不比整個目錄。** 目錄級比較已於 2026-08-05 被論文部原型實測推翻：
全域 sweep（例如 `paper_ai_footnote_scrub_20260701`）掃過每個目錄，導致 **12/13 全部命中**——
那是「擋而無因」。**不得用 commit message 關鍵字分類實質變更**：實質修訂
（`paper(prg): v6 MINOR 9 mechanism citations`）與全域清洗在 pattern 上不可分，
錯的分類器比誠實的過度回報更糟——過度回報的成本是多讀一次檔，錯誤分類的成本是靜默吃掉真陽性。

**規則 2（缺漏即最陳舊）**
`blocker_verified_at` 不存在 → `stale`。

現況 13 篇論文有 12 篇沒有這個欄位。**這是刻意的結果，不是待修的資料缺陷。**
純 TTL 規則會讓那 12 篇靜默通過、只擋住唯一有時間戳可檢查的 `taiwan-vt`——
**記錄的被罰、不記錄的暢行無阻。** 任何 freshness 門檻的第一件事就是堵掉這個反向誘因。

**規則 3（TTL，後備）**
`now - blocker_verified_at > 7 天` → `stale`。

7 天的出處：13 個 paper 目錄自 2026-05-01 的相鄰 commit 間隔
median 0.33d / p75 2.13d / **p90 6.40d**，取 p90 上取整，對應 repo 既有的「誤判率 ≤10%」慣例。

**TTL 的局限必須寫進實作註解**：`taiwan-vt` 的 blocker 隔天就被超越，7 天 TTL 抓不到它。
**只實作規則 3 而不實作規則 1 等於沒做。**

---

## 2. `stale` 的語意：改變舉證責任，不是停擺

**`stale` 不得升級為 `blocked`，不得阻止任何 transition。**
它唯一的作用是：引用該 blocker 前，**回讀原始檔複核**；對得上就照常引用。

拿索引的缺陷去懲罰被索引的內容是本規格明文禁止的。依 `feedback_gates_smooth_no_deadlock`，
三條出路寫在同一處（輸出訊息裡就要有）：

- **修復**：回讀六類檔案複核後，更新 `blocker_verified_at`
- **寬限**：標註「已複核，內容仍成立」並照常引用
- **裁決**：送經理

---

## 3. 禁止批量回填

**不得為了讓輸出變綠而批量寫入 `blocker_verified_at`。**
批量回填產生的時間戳，其「什麼動作會讓它更新」的答案是「有人跑了一支腳本」，
與「有人核實過這個 blocker」無關——那正是本規格要偵測的東西，回填等於把偵測目標製造出來。

合法的更新只有一種：**需求驅動的當場核實**（有人真的要引用它，回讀了六類檔案，然後更新）。

---

## 4. 實作與歸屬

- **收編點**：`paper-submission-pipeline` 既有讀取路徑，加一個輸出欄位。**不新增檔案、不新增 gate。**
- 若實作面落在 `scripts/`，歸 platform_eng；治理部只出本規格。
- **驗收**：實作後 13 篇的預期輸出是 12 篇 `stale`（規則 2）＋ `taiwan-vt` 依規則 1 判定。
  **若實作後出現「全部 fresh」，那是規則 2 沒實作**，不是資料變好了。

---

## 5. 主判準（本規格背後的那把尺）

引用任何欄位前先問三件事：**這個欄位是誰寫的**、**什麼動作會讓它更新**、
**那個動作與我關心的事實是不是同一件事**。三個有一個答不出來，就去讀底層。

`blocker_verified_at` ↔「有人核實過」之間隔著「有人寫了這個欄位」一層——
這一層就是本規格存在的理由。
