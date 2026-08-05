# `blocker_verified_at` 過期門檻 — 治理裁定

- **產出部門**：治理部（`governance`）
- **產出時間**：2026-08-05 18:30（台灣時間）
- **對應工作項**：`item_20260805T100613395124Z`（D21，經理要求給明文門檻）

---

## 0. 一句話裁定

**門檻不是時間，是事件：`blocker_verified_at` 早於該論文目錄最後一次 commit，即不可採信。
時間 TTL 只是後備（7 天）。而且——「沒有時間戳」必須判為最陳舊，不是通過。**

最後那句是本裁定的重點：經理問的是「過期多久算不可採信」，但實測後發現
**13 篇論文裡有 12 篇根本沒有 `blocker_verified_at`**。任何純 TTL 規則都會讓那 12 篇
靜默通過，只擋住唯一誠實記錄了時間戳的那一篇。

---

## 1. 實測：這不是「時間戳太舊」，是「時間戳幾乎不存在」

逐篇比對 `storage/paper_pipeline_status.json` 的 `blocker_verified_at`
與 `git log -1 -- paper/<name>` 的最後 commit 時間：

| 狀態 | 篇數 | 說明 |
|---|---|---|
| 有時間戳且已被 commit 超越（STALE） | **1** | `taiwan-vt`（verified 2026-07-05，目錄最後 commit 08-04，age 30 天） |
| **完全沒有 `blocker_verified_at`** | **12** | 其餘全部 |
| 有時間戳且仍新於最後 commit | **0** | — |

上表用的是 v1 的目錄級比較。**依 v2 的 artifact 限定重算，`taiwan-vt` 仍然 STALE**
（verified `2026-07-05T19:20`，而 `body_v3.tex` 07-27、`reproduce.py` 07-09、
`reproduce_report.json` 07-06、`experiments.md` 07-06、`review_history/` 07-11
共五項 artifact 都晚於它）——**判定不因收緊而翻轉，只是理由更精確**。

**結論**：`taiwan-vt` 之所以今天被抓出來，不是因為它比較糟，**是因為它是唯一有時間戳
可以檢查的一篇**。若門檻只寫「超過 N 天不可採信」，等於獎勵不記錄時間戳的行為——
記錄的被擋、不記錄的暢行無阻。這是必須先堵掉的反向誘因。

## 2. 門檻（三條，依序判定）

**判定順序固定，第一條命中就停。**

### 規則 1（主判準，事件式）— **v2 已依論文部實測修正**

> `blocker_verified_at` **早於下列 canonical artifact 任一者的最後 commit 日期**
> → **stale，不得作為現況證據引用**。
>
> artifact 清單（路徑限定，**不是整個 `paper/<id>/` 目錄**）：
> `canonical.json` 指定的 manuscript 與其 `\input` 檔、`reproduce.py`、
> `reproduce_report.json`、`experiments.md`、`data_sources.md`、`review_history/*/`。

`taiwan-vt` 的血淋淋案例：verified `2026-07-05T19:20`，而 followup 分別在 **07-06**
（reproduce.py／experiments.md 重綁）與 **07-13**（`%source` PROVENANCE 區塊）落地——
**隔天就被超越了**。

**v1 → v2 的更正（治理部自我更正）**：v1 寫的是「該 paper 目錄最後一次 commit」。
論文部先做了原型並回報：用目錄級比較 **12/13 全部命中**，因為全域 sweep
（compliance scrub、footnote scrub 等）會掃過每一個 paper 目錄——**那不是實質變更**。
這正是我整天在裁定的「擋而無因」形態，v1 自己踩了進去，依同一標準必須改。三項實作約束
一併採納自論文部的規格：

1. **用 git commit date，不用 mtime**——checkout 會重寫 mtime，會讓每篇論文看起來都剛改過。
2. **殘留噪音不調到靜音**：限定路徑後全域 sweep 偶爾仍會改到 manuscript
   （2026-07-01 的 AI footnote scrub 就是），因此仍有 false positive。**接受**——
   false positive 的成本是讀一次檔，false negative 的成本是一個部門下了錯的裁決
   （今天已經發生一次）。
3. **不得用 commit message 關鍵字分類**：實質修訂與全域清洗在 pattern 上不可分，
   **錯的分類器比誠實的過度回報更糟**。

### 規則 2（缺漏即最陳舊）

> `blocker` 欄位非空，但 `blocker_verified_at` **缺漏或為 null**
> → 視同 stale，**不得引用**。

不給「沒有時間戳所以沒過期」這條路。目前這條會命中 12 篇——**這是刻意的**，
它把「12 篇的 blocker 目前都不可當現況證據」這件事變成可見的事實，而不是隱形的預設。

### 規則 3（TTL 後備，只用於前兩條無法判定時）

> 無法對應到任何 canonical artifact 的 blocker（例如描述的是流程或外部狀態）：
> `blocker_verified_at` **超過 7 天**即 stale。

**7 天怎麼來的（不是拍腦袋）**：對 13 個 paper 目錄自 2026-05-01 起的 commit 時間序列，
計算相鄰 commit 間隔：

| 統計量 | 值 |
|---|---|
| 中位數 | **0.33 天** |
| p75 | **2.13 天** |
| p90 | **6.40 天** |

也就是說，一個超過 7 天沒重新驗證的 blocker，有 **≥90% 的機率**其論文目錄已經被動過。
取 p90 向上取整為 7 天，是「誤判率 ≤10%」這個 repo 既有的門檻慣例
（同一個 10% 門檻在 `hourly_pregate` 的退役裁定中用過）。

**明確聲明 TTL 的局限**：`taiwan-vt` 的 blocker 隔天就被超越，**7 天 TTL 抓不到它**。
所以規則 3 永遠只是後備，規則 1 才是主力。任何人若只實作 TTL 而不實作規則 1，
等於沒做。

## 3. 這是 stale 判定，不是 block（出路必須存在）

依 `feedback_gates_smooth_no_deadlock`，判為 stale **不代表工作停擺**，它只改變舉證責任：

> stale ⇒ **回讀原始檔複核後才可引用**；複核完成即可使用，並順手回寫欄位與
> 新的 `blocked_verified_at`。

三條出路寫在同一處：(a) 回讀原始檔（本部門今天處理 taiwan-vt 的做法，成本約 5 分鐘）；
(b) 請該篇的 owner 部門重新驗證；(c) 明記「本結論建立在未經複核的 blocker 上」並標為
暫定。**不得**因為欄位 stale 就把論文標成 blocked——那是拿索引的缺陷去懲罰論文。

## 4. 機械化歸屬（anti-stacking）

- **不新增 gate。** 規則 1／2 是 `paper-submission-pipeline` 既有讀取路徑上的一個
  欄位判定，應收編進它現有的 stall/gate 評估，輸出一個 `blocker_evidence: fresh|stale`
  欄位。**不要為它開新的 checker、新的 cron、新的 hook。**
- 論文部已把「每輪 review 順手核實該篇 blocker 並在 round README 寫出應寫入的字串」
  排進固定步驟（經理已核准）——**那是規則 1 的人工前哨，機械化後仍應保留**，
  因為它產生的是「新的 verified_at」，機械層只能偵測陳舊、不能重新驗證。
- 本裁定的 owner 是治理部；欄位與判定實作歸 `paper-submission-pipeline` 的維護者。

## 5. 附帶：這是 class 的第三例

同一形態今天出現三次（本部門 taiwan-vt 案、經理用過時 blocker 選題、論文部自陳照
字面採信過一次），而且與另外兩處**索引與現實脫節**同源：

| 例 | 索引 | 現實 |
|---|---|---|
| 1 | `enforcement_layer_map.md` 缺 `write_claim_guard.py` | hook 已在 `.claude/settings.json` 註冊 |
| 2 | `control_gate_registry.json:188` `hourly_pregate` `mode=shadow` | 該 gate 2026-07-30 已退役，owner 檔已移入 `_legacy/` |
| 3 | `paper_pipeline_status.json` 的 `blocker` | 12/13 篇無驗證時間戳、1 篇被超越 30 天 |

**三例已達 3-strike。** 但本裁定**不主張現在重構**，理由是三例的修法方向一致且都已各自
派出（1、2 給 platform_eng，3 即本裁定），先看這一輪是否收斂。**若下一輪再出現第四例，
即觸發 3-strike 重構，方向已經明確：索引不該由人維護，該由現實生成**
（layer map 從 `settings.json` 生成、gate registry 從 owner 檔存在性生成、
pipeline blocker 從 artifact mtime 標記新鮮度）。
