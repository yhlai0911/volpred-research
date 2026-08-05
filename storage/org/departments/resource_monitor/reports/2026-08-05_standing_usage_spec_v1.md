# 常設 token 分析規格 v1 ＋ 今日首份報表（2026-08-05）

工作項 `item_20260805T140751887775Z`（P1, manager）｜資源監控部
工具：`tools/usage_breakdown.py`（本部門，常設）｜資料：`reports/data/2026-08-05_usage_breakdown.json`

---

## 0. 先更正：本部門今天所有數字都低估約 10 倍

**做這份規格的第一件事是發現我自己的量測是錯的。**

`_billable_total()` 讀的是**正規化後**的鍵 `cache_create_tokens`；raw turn 的 usage 用的是
API 原始鍵 `cache_creation_input_tokens`。平台自己每一處都先呼叫 `_usage_breakdown()` 正規化
再算——**我的四支工具全部跳過了那一步**，於是整個 cache creation 被算成 0。

決定性對照（2026-08-04）：

| 來源 | billable |
|---|---|
| canonical `daily_2026-08-04.json` | **24,178,959** |
| 我原本的算法 | 2,360,848（**低估 9.8 倍**） |
| 補上正規化後 | 23,202,174（與 canonical 差 4%，餘差來自 UTC 日界與去重邊界） |

**受影響且已作廢的說法**（今天稍早我交給經理的）：
- 「今天 Claude 側 4,734,619」→ 正確值 **46,951,901**
- 「停擺窗 2,416,531 / 52.1%」→ 絕對值作廢；**佔比另行重算**（見 §4）
- 「平台總量 4.7M 只有 08-02 的 11%」→ **整句作廢**，結論方向可能相反
- 「並行部門制倍數 2.14x／3.77x」→ 重算中（Claude 側基線已重跑）
- 昨天那句「Codex 側今天零記錄」不受影響（0 就是 0），但 **Codex 側的歷史金額尚未複驗**

**這正是我自己 skill 規則 3 講的那一類**：不是顯眼的 0，是**看起來完全合理的錯值**——
4.7M 跟前幾天的 1-2M 同量級，沒有任何一處看起來不對，所以它被引用了一整天。
真正該問的問題我沒問：**「我算的跟 canonical 日報對得上嗎？」** 對一次就會抓到。

已修：`usage_breakdown.py`／`today_burn.py`／`hourly_baseline.py`／`token_breakdown.py`
四支全部改成先 `_usage_breakdown()`。**修法是用平台既有的正規化函式，不是自己寫第二套。**

---

## 1. 規格：四個維度，每個都標明是量測還是推斷

| 維度 | 內容 | 品質 |
|---|---|---|
| 角色 | 7 部門＋經理＋主線程＋dispatch worker＋subagent | 目錄類別**量測**；部門身分**推斷** |
| 固定 vs 變動 | fixed（脈絡載入與續建）／variable（實際做事）／standing_repaid（cache_read） | **量測** |
| 耗 token vs 不耗 token | compute queue／回測／模擬獨立成區塊，**永不進可節省項目** | **量測** |
| 節流分層對照 | `config/token_conservation.json` 的 exempt／overrides／deferred 逐項 | **量測** |

---

## 2. 今日首份報表：46,951,901 billable / 7,333 turns

### 2.1 最重要的一個數字：**88.2% 是脈絡成本，只有 11.8% 在做事**

| 成本類型 | tokens | 佔比 | 這是什麼 | 怎麼省 |
|---|---|---|---|---|
| fixed（脈絡） | **41,433,974** | **88.2%** | system prompt＋brief＋工具定義＋每輪 cache 續建 | **瘦 brief、砍工具定義、減少 session 重啟** |
| variable（做事） | 5,517,927 | 11.8% | 真正的推理與工具呼叫 | 降檔模型、少做任務 |
| standing_repaid | 1,730,202,510 | （不計費） | 每輪重讀的常駐脈絡（cache_read） | 同上，瘦脈絡直接降它 |

**這一列直接回答老闆的問題「砍哪個最有效」：**
降檔模型與暫停任務動的是那 **11.8%**；瘦 brief 動的是 **88.2%**。
**同樣的努力，效果差 7.5 倍。**

### 2.2 逐角色（billable 由大到小）

| 角色 | billable | 佔比 | turns | 固定成本佔自身 |
|---|---|---|---|---|
| unattributed | 14,030,563 | 29.9% | 1,086 | 94% |
| platform_eng | 7,854,087 | 16.7% | 1,347 | 87% |
| content | 5,639,101 | 12.0% | 1,157 | 85% |
| research | 4,502,955 | 9.6% | 679 | 87% |
| resource_monitor | 3,063,106 | 6.5% | 577 | 84% |
| governance | 2,963,844 | 6.3% | 673 | 83% |
| member_success | 1,835,305 | 3.9% | 365 | 87% |
| publications | 1,830,748 | 3.9% | 379 | 80% |
| main_checkout:subagent | 1,023,884 | 2.2% | 122 | 97% |
| dispatch_worker | 970,575 | 2.1% | 344 | 74% |
| dispatch_worker:subagent | 545,208 | 1.2% | 117 | 97% |

**每一個角色的固定成本都在 74–97% 之間**——這不是某個部門浪費，是**組織形態本身的定價**。

**subagent 的 97% 特別值得看**：派一個 subagent 幾乎全部成本都花在「把脈絡講給它聽」，
它真正做事的部分不到 3%。緊縮期間「拆成多個 subagent 平行做」是**最貴的做法**。

### 2.3 固定成本可以直接量：brief 檔案大小

`storage/org/runtime/<role>.brief.md` 就是實際交給該角色的文字，位元組數可直接量：

| 角色 | brief bytes | ≈tokens | 每次喚醒都付一次 |
|---|---|---|---|
| **manager** | **271,493** | **≈90,500** | ← 最大的單一可省項 |
| platform_eng | 118,169 | ≈39,400 | |
| content | 66,717 | ≈22,200 | |
| governance | 34,138 | ≈11,400 | |
| resource_monitor | 31,230 | ≈10,400 | |
| research | 25,250 | ≈8,400 | |
| publications | 25,249 | ≈8,400 | |
| member_success | 22,237 | ≈7,400 | |

（token 為換算估計；量測真值看 `by_role.fixed_first_load`。）

**經理的 brief 是第二名的 2.3 倍、最小部門的 12 倍**，而經理是**喚醒最頻繁**的角色
（每 10 分鐘的 tick 閘門）。你提到 platform_eng 從 38k 瘦到 5.9k——
**同樣的手術套在 manager 上，單位效益更高。**

### 2.4 不耗 token 的程式運算（緊縮時照跑，**不列入可節省項目**）

今日 compute queue job：**15 件**，billable **0**。
政策（老闆 2026-08-05）：暫停它只損失研究進度，省不到額度。
本報表把它獨立成 `non_token_compute` 區塊，**結構上不可能被算進節省項**——
不是靠讀報表的人自己記得。

### 2.5 節流分層現況對照

`config/token_conservation.json`：`active=true`、`expires_at=2026-08-09T08:00:00Z`、
reason 為 weekly allowance 89%。
- exempt（不降）7 個 task_type：daily_article／daily_digest／event_article／
  trending_repost／member_qa／email_reply／telegram_reply
- 降檔 13 個 task_type（含本部門 `resource_audit` → sonnet/medium）
- 暫緩部門：publications

---

## 3. 誠實邊界：逐角色是**推斷**，而且我知道怎麼讓它變成量測

**telemetry 沒有角色欄位。** 部門身分經 `--append-system-prompt` 傳入，
而 Claude Code **不把 system prompt 寫進 transcript**（我逐檔驗過前 60 行皆無）。
所以歸屬只能推斷。今日 95 個 session 的歸屬品質：

| 品質 | session 數 | 依據 |
|---|---|---|
| exact | 22 | 目錄類別（worktree／dispatch／subagent），Claude Code 以 cwd 決定 |
| strong | 15 | 第一則 user 訊息裡 `departments/<x>` 路徑唯一 |
| weak | 44 | 全文 `departments/<x>` 路徑的眾數 |
| unknown | 14 | 兩者皆無 → `unattributed`（29.9% 的量在這裡） |

**踩過的坑寫下來**：第一版用「部門名字詞計數」當 fallback，`research` 命中了 repo 路徑
`volpred-research`，於是研究部被算成 65.6%。已改成只認 `departments/<x>` 路徑。
**看起來合理的錯值第二次出現在同一天。**

### 讓它變成量測的最小修法（一行，屬 platform_eng）

`scripts/org/org_attach.py` 產 `runtime/<dept>.lease.json` 時已寫入 `pane_id`／`since`，
**只差 session_id**。attach 後把 Claude session id 記進 lease（或另寫
`runtime/<dept>.sessions.jsonl`），本報表即可用 join 取代推斷，
`unattributed` 的 29.9% 會歸零。已隨本報告送 request。

---

## 4. 尚未完成的部分（不假裝做完）

- ~~並行倍數待重算~~ → **已重算完成，見下表**。停擺窗的佔比仍待下一班重做。

### 並行部門制倍數（修正後，Claude 側）

| 指標 | 08-05 | 前 7 日 | 修正後倍數 | 舊值（作廢） |
|---|---|---|---|---|
| 每活躍小時 | 2,471,332 | 589,340（均值） | **4.19x** | 2.14x |
| 尖峰小時 | 8,668,908（18時） | 1,309,973（各日尖峰均值） | **6.62x** | 3.77x |
| 尖峰小時 | 8,668,908 | 3,521,413（前 7 日單日最高，08-04） | 2.46x | 1.86x |
| 最高併發 session | 28（16時） | 10（08-02） | 2.8x | 2.8x（不變） |
| 單 session 每小時 | 412,805 | 503,059（08-04）／229,324（08-02） | ≈1.0x | ≈1.0x（不變） |

**結論的方向沒變，量級變了**：倍數仍來自「同時開幾個」而非「每個變貴」，
但實際倍數是我原本報的 **約 1.8 倍**。給老闆談組織形態時請用這一版。

**修法的獨立驗證**：修好的工具重算 08-04 得 **23,655,800**，canonical 日報是
**24,178,959**，差 2%（來自 UTC 日界 vs 台灣日界）。兩條路徑對得上。
- **Codex 側**：`_iter_codex_session_records` 的 usage 是否同樣需要正規化，**尚未查**。
  今日 Codex 為 0 不受影響，歷史金額待複驗。
- **逐 task_type**：dispatch worker 那 344 個 turn 可經 receipts join 出 task_type，
  但部門 session 沒有 task_type（它們處理的是 inbox 工作項不是任務池條目）。
  本版先給逐角色；task_type 維度需與經理確認「部門工作項要不要也帶 task_type」才有意義。
