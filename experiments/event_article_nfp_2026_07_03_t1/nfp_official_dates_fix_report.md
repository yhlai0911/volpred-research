# NFP 官方發布日修正報告

**日期**：2026-07-19｜**Branch**：`task/nfp-official-dates`｜**Task**：`assign_358decfa`
**稽核來源**：`experiments/k1442/related_event_date_audit.md`

---

## 摘要

`experiments/event_article_nfp_2026_07_03_t1` 原本用「當月第一個週五」proxy 推 NFP 發布日。
對照官方行事曆，**13 個歷史樣本錯 7 個**，其中一個是根本不存在的事件。改用
`volpred.data.event_dates.nfp_release_dates`（BLS/ALFRED release id 50，fail closed）後，
**8 個歷史統計量全部改變，兩個方向性結論翻轉**。

線上文章 `mile_35eef830` 的 `details.event` 已透過正式 publisher 修正並完成 live verify。

**這次修正最值得記的一點**：proxy 不會噴錯、不會產生 NaN、圖照樣畫得出來。它安靜地產出一組
方向相反但一樣可信的數字。勝率 53.8%（多數上漲）其實是 46.2%（多數下跌）——沒有任何一個
自動檢查會抓到這件事，只有拿官方日曆對過才知道。

---

## 1. 改了什麼

| 檔案 | 改動 |
|---|---|
| `event_article_nfp_2026_07_03_t1.py` | 刪除 `first_friday()` / proxy 版 `build_nfp_dates()`；改呼叫 `nfp_release_dates()`。`RELEASE_DATE` 常數 = `2026-07-02`。yfinance 下載窗 `end` 改成 exclusive 於發布日 → **無 lookahead 變成結構性保證**，不再靠事後 `.loc[:AS_OF]` 切片。欄位 `nfp_date_proxy` → `nfp_release_date`。新增 `event_date_source` 欄位。 |
| `README.md` | 頂部加更正聲明；資料來源改官方行事曆；補 proxy vs 官方對照表；主要數字表加「舊值」欄；結論段改寫。 |
| `render_lazypack.py` | 第 2 張的「中位數 +0.10%」是**寫死的**（資料一改就過期）→ 改成綁 `spy_ret_day0_median_pct`。第 3 張「NFP 日期用第一個週五近似」→ 改成官方行事曆。VIX9D 落後天數 = 0 時不再印「落後 0 天」。 |
| `src/volpred/publisher/article_correction.py` | **新增**。已發佈文章的 in-place 更正唯一入口（見 §5）。 |
| `tests/test_nfp_official_release_dates.py` | **新增**，25 tests。 |
| `tests/test_article_correction.py` | **新增**，10 tests。 |

`AS_OF=2026-07-01` 的 T-1 快照定位**未改**——2026-07-01 本來就是 07-02 發布的前一個交易日，
日期修正後這個定位反而更精確（原本被描述成 07-03 的前一日，中間隔了 07-02）。

---

## 2. 七筆錯誤樣本前後對照

| # | proxy 日期 | 官方日期 | proxy 當日 SPY | 官方當日 SPY | proxy VIX 變化 | 官方 VIX 變化 |
|---|---|---|---|---|---|---|
| 1 | 2025-07-04 | 2025-07-03 | -0.745% | **+0.788%** | +1.41 | **-0.26** |
| 2 | 2025-10-03 | **（無發布）** | -0.001% | **（幻影事件）** | +0.02 | **（幻影事件）** |
| 3 | 2025-11-07 | 2025-11-20 | +0.098% | **-1.524%** | -0.42 | **+2.76** |
| 4 | 2025-12-05 | 2025-12-16 | +0.190% | **-0.273%** | -0.37 | **-0.02** |
| 5 | 2026-01-02 | 2026-01-09 | +0.183% | **+0.661%** | -0.44 | **-0.96** |
| 6 | 2026-02-06 | 2026-02-11 | +1.918% | **-0.023%** | -1.40 | **-0.14** |
| 7 | 2026-05-01 | 2026-05-08 | +0.277% | **+0.826%** | +0.10 | **+0.11** |

**正確的 6 筆**（proxy 剛好對）：2025-06-06、2025-08-01、2025-09-05、2026-03-06、2026-04-03、2026-06-05。

**新增 1 筆**：`2025-05-02`（SPY +1.484%、VIX -1.92）。proxy 因為多塞了一個幻影的 2025-10 事件，
把這筆真實事件擠出 trailing-13 之外。

**兩種失效模式**（不是隨機分佈）：
- **假日提前**：2025-07-04 proxy 撞到休市的國慶日；官方其實是前一天 07-03 發布。
- **停擺延後**：2025-10 沒有發布、9 月報告延到 11-20、12 月延到 12-16，連錯三個月。

---

## 3. 哪些數字動了、哪些沒動

### 動了（全部因日期修正）

| 指標 | proxy | 官方 | |
|---|---|---|---|
| SPY 上漲機率 | 53.8% | **46.2%** | **方向翻轉**：多數上漲 → 多數下跌 |
| VIX 當日下降比例 | 46.2% | **53.8%** | **方向翻轉** |
| SPY 當日報酬中位數 | +0.098% | **-0.023%** | **變號** |
| VIX 當日變化中位數 | +0.02 | **-0.02** | **變號** |
| 隔日 SPY 平均報酬 | +0.411% | **+0.032%** | 縮到 1/13 |
| SPY 當日報酬平均 | -0.185% | -0.183% | 幾乎不變（巧合） |
| SPY 當日報酬標準差 | 1.168% | 1.236% | |
| VIX 當日變化平均 | +0.991 | +1.042 | |

平均值幾乎沒動純屬巧合——中位數與勝率才是真正被污染的量。**只看平均值會完全看不出這次污染。**

### 沒動（與事件日期無關，已逐一確認）

- VIX 最新收盤 16.59（2026-07-01）
- SPY 5 日已實現波動 14.41%、20 日 18.28%
- 2026-06-05 那筆（-2.58% / +6.11 點）仍是樣本內最大波動，懶人包第 2 張的 callout 文字仍成立

### 動了但**不是**本次修正造成的（資料商 vintage 回補）

發稿當下 yfinance 的 `^VIX9D` 停在 2026-06-26，比值只能用該日算（0.9125）並逐字揭露落後 5 日。
yfinance 事後回補了 06-29 ~ 07-01，所以現在是真正的同日 T-1 比值 **0.7920**（13.14 / 16.59）。

判定依據：**2026-06-26 那筆仍是 16.80，完全沒變**——所以是新資料補進來，不是舊資料被改。
也不是 lookahead：13.14 是 2026-07-01 的真實收盤，仍嚴格早於 07-02 發布。
兩個 vintage 都保留在 `_results.json.vix9d_vintage_note`，發稿當時的宣稱維持可稽核。
**線上文章從未引用 VIX9D 比值（grep 0 命中），不影響任何已發佈數字。**

### 圖表

| 圖 | 狀態 | 原因 |
|---|---|---|
| `fig2_nfp_day_spy_return.png` | 重繪 | 事件日期改變（x 軸 13 個日期 + 平均線） |
| `fig1_vix_vix9d_term_structure.png` | 重繪 | **VIX9D 回補**，非日期修正 |
| `nfp_lazypack_2_results.png` | 重繪 | 統計量 + 最近 5 次表格 |
| `nfp_lazypack_3_takeaway.png` | 重繪 | 「第一個週五」免責聲明改成官方行事曆 |
| `nfp_lazypack_1_framework.png` | 重繪 | **VIX9D 回補**，非日期修正 |

三張懶人包已目視確認（不只確認檔案有產生）：數字正確、無跨行斷字。第 2 張因中位數變負數
多一個字元導致「−0.0 / 2%」斷行，已縮短標題文字修掉。

---

## 4. 線上文章 `mile_35eef830` 核對結果

### 4.1 正文數字污染核對 —— 結論：**本實驗的 proxy 數字沒有進入正文**

已逐行核對全文 70 行。文章的統計量全部來自 **k528**（254 次 NFP，2005-02 ~ 2026-03）+ 7/2 當天
實際行情，**本實驗那 13 筆 proxy 統計量（-0.185% / 53.8% / +0.991 等）一個都沒出現在正文**。

### 4.2 但核對過程抓到另一個問題（已一併修正）

正文寫「公布前一個交易日（7/1）……近 20 日 SPY 已實現波動年化 **18.1%**、近 5 日壓到 **14.0%**」。
這兩個數字**對不上任何實驗產物**。實測 12 種變體（as-of 7/1 與 7/2 × pct/log 報酬 × ddof=1/ddof=0/RMS）：

- 本實驗 canonical 值（as-of 7/1、pct、ddof=1）= **18.28% / 14.41%**
- 唯一能重現 18.1% 的是 **as-of 7/2、含發布日當天**（18.13%）
- 14.0% 只有 RMS 估計式接近（13.98 ~ 13.99），與 18.1% 不同口徑

即：正文把這兩個數字說成「7/1 發布前」的狀態，但 18.1% 只有**把發布日算進去**才重現得出來，
且兩個數字疑似用了不同估計式。已透過 publisher 改成經過驗證的 **18.28% / 14.41%**。

**這與 proxy 污染是不同的缺陷**，是核對過程順帶抓到的。

### 4.3 metadata 修正

| 欄位 | 修正前 | 修正後 |
|---|---|---|
| `details.event` | `NFP_US_2026_07_03` | `NFP_US_2026_07_02` |
| `details.as_of` | `2026-07-01 close` | `2026-07-02 close` |
| `details.event_date` | （無） | `2026-07-02` |
| `details.event_phase` | （無） | `T+0` |

`as_of` / `event_phase` 是「phase metadata」的實質問題：這篇掛著 T-1（發布前）的 metadata，
但正文報的是**發布後**的結果（7/2 收盤 SPY 0.13%、VIX 16.15）。它其實是 T+0 文章。

**未發第二篇更正文**（依任務要求）。`published_at` 未動，feed 排序不受影響；改動記在
`errata.update_history`。

### 4.4 metadata 層 class sweep（同類問題還有沒有別的？）

掃過整個 `feed.json`，帶結構化 NFP/CPI 事件 metadata 的文章**只有 `mile_35eef830` 一篇**：

```
$ jq -r '.[] | select(.details.event != null)
         | select(.details.event | test("NFP|CPI|nfp|cpi"))
         | "\(.id)\t\(.status)\t\(.details.event)"' storage/reports/feed.json
mile_35eef830   published   NFP_US_2026_07_02      ← 已修正
```

即**線上 metadata 層這一類問題已清空**。注意這只涵蓋 `details.event` 這個欄位；
正文內容層的污染（§7 的 k528）不在這個 sweep 的範圍內。

### 4.5 Live verify 實證

```
$ curl -s -o /dev/null -w "HTTP %{http_code}" https://volpred.zeabur.app/v3/reports/mile_35eef830
HTTP 200

$ curl "$SUPABASE_URL/rest/v1/articles?slug=eq.mile_35eef830&select=content,details,status"
status          : published
event           : NFP_US_2026_07_02      ← 修正後
event_date      : 2026-07-02
event_phase     : T+0
as_of           : 2026-07-02 close
last_updated_at : 2026-07-18T19:00:27.893564+00:00

LIVE CONTENT CHECK
  18.28%     present=True  expected=True  OK      ← 新值已上線
  14.41%     present=True  expected=True  OK
  18.1%      present=False expected=False OK      ← 舊值已消失
  14.0%      present=False expected=False OK
```

線上正文實際句子：
> 回到 7/2 這場提前登場的 NFP。公布前一個交易日（7/1）VIX 收在 16.59……近 20 日 SPY 已實現波動年化 **18.28%**、近 5 日壓到 **14.41%**

**說明前端驗證口徑**：`/v3/reports/<id>` 是 SPA，任何路徑都回同一份 31KB shell，內容由前端在
runtime 向 Supabase 取。所以「線上內容」的權威來源是上面的 Supabase projection 查詢，
頁面本身只驗到 HTTP 200。這是實際查證結果，不是假設。

另註：全文仍有一處「7/3」——`原本市場排定 7/3 公布的…改在 7/2`。這是**正確的敘事**
（說明 BLS 提前一天），已確認上下文後保留，不是殘留污染。

---

## 5. 為什麼新增 `article_correction.py`

任務要求「只透過正式 publisher 修正、禁手改 DB」。但 repo 裡**沒有**已發佈文章 in-place 更正的
正式入口：`publisher.py` 只有 `publish_*` 與 `unpublish`，errata 標記散在
`lazypack_install.py` / `backfill_feed_audience.py` / `publish_draft.py` 各自為政。

依「永遠修流程，不修資料」+ anti-stacking（一個 concern 一個 owner），新增
`src/volpred/publisher/article_correction.py` 作為唯一入口，而不是寫一次性 jq patch。

核心安全性質：**每個字串替換必須恰好命中一次，否則整批不寫入並 raise**。理由與這次的 bug
同源——一個「沒命中所以什麼都沒改」的更正，和 proxy 一樣是不噴錯的錯誤：errata 蓋章了、
流程跑完了、線上還是舊數字。10 個測試涵蓋：命中 0 次 / 命中 2 次 / 部分批次失敗全不寫入 /
no-op 拒絕蓋 errata / `published_at` 不被動 / sync 失敗必須往上拋。

**未重構既有的 errata 呼叫點**（`lazypack_install.py` 等）——那是另一個任務的範圍。

---

## 6. 測試

`tests/test_nfp_official_release_dates.py`（25 tests，全程 mock 網路）：

- 7 筆錯誤日期逐筆釘住：proxy 日期**不在**官方行事曆、對應官方日期**在**
- **fixture 自我校驗**：每個 proxy 日期必須真的是「當月第一個週五」——否則 fixture 打錯字會讓測試用一個 proxy 根本不會產生的日期矇混通過
- 2025-10 幻影月份：官方行事曆該月份必須是空的
- 6 筆本來就正確的日期也釘住（防止「修好」變成全部平移）
- 「7/13 錯誤」這個數字是**重算出來的**，不是抄稽核報告的
- trailing-13 完整清單、發布日自己不得進入自己的歷史
- fail closed：日曆太短 / 取不到 → raise，不得回退 proxy
- 原始碼層防呆：檔案內不得再出現 `def first_friday` 或 `(4 - d.weekday()) % 7`

**已做 mutation test 驗證測試真的會紅**：把 proxy 完整還原回腳本後重跑 → **5 個測試轉紅**
（release date、trailing-13、兩個 fail-closed、原始碼殘留防呆）。確認不是永遠綠的假測試，
之後已還原（`diff -q` 驗證與修正版一致）。

其他：`experiment_gates.py run` → **PASS**（4 gates）。
`test_event_dates.py` + `test_prepublish_audit_dates.py` 未受影響。

---

## 6b. Codex 獨立審查（round 1）→ 判 FIX-BEFORE-MERGE → 已全數修正

Codex 判定事件日期與下載邊界正確，但在**新寫的 canonical writer**
`article_correction.py` 上抓到三個高風險缺陷。**全部屬實，已修**：

| # | 嚴重度 | 缺陷 | 修正 |
|---|---|---|---|
| 1 | HIGH | **靜默同步失敗**。`sync_article()` 失敗時是 **return False**，不是丟例外。我的模組只處理了例外路徑，於是會正常返回 `{"synced": False}` —— feed.json 已改、Supabase 沒改、呼叫端以為成功。**這正好是本模組宣稱要杜絕的失效模式，卻自己犯了。** | 已驗證 `supabase_sync.py` 確有 6 條 `return False` 路徑。falsy 回傳改為 raise `CorrectionNotSynced`。新增測試。 |
| 2 | HIGH | **非原子覆寫**。`write_text()` 直接 truncate 15MB 的 canonical feed.json；磁碟滿／中斷會留下截斷 JSON，lock 擋不住。 | 改 `mkstemp` + `fsync` + `os.replace()`；失敗清掉暫存檔。新增「寫入失敗後原檔完好」測試。 |
| 3 | HIGH | **replacement 交互污染**。驗證在原文做、替換卻依序作用於已改內容：`[("A","B"),("B","C")]` 對 `"A B"` 會得到 `"C B"`（第二筆吃掉第一筆的產物）。所以我宣稱的 all-or-nothing **並不成立**。 | 改成在**原文**上解析所有 span、檢查不重疊、單次 splice 組回去。新增交互測試（斷言得 `"B C"`）與重疊拒絕測試。 |
| 4 | MEDIUM | sync 在 lock 外用舊 snapshot，並行 writer 會被舊內容蓋回。 | 已驗證 `sync_article` 不取同一把 lock（不會 deadlock）→ 移進 lock 內。 |
| 5 | MEDIUM | **SPY/VIX 各自獨立**取「事件日後第一筆」，未要求同一天；vendor gap 會把不同日期的兩個數字拼成一列。且事件被 `continue` 跳過後仍用較小的 n 產出看似合理的結果。 | VIX 改為**必須**落在與 SPY 相同的 session；任何事件無法測量 → 收集後 **raise**，不再讓樣本無聲縮水。 |
| 6 | MEDIUM | lookahead 只有實作、**沒有測試防線**——把 `end` 改回 `2026-07-03` 仍全綠。 | 新增 `TestNoLookahead`：攔截實際 `yf.download` 呼叫並斷言 `end == "2026-07-02"`。 |
| 7 | 測試品質 | `monkeypatch` 打在 `volpred.canonical_write.guard_canonical_write`，但模組已 `from ... import` 綁了自己的別名 → **這個 patch 根本沒生效**，只是看起來有保護。 | 改 patch `volpred.publisher.article_correction.guard_canonical_write`。 |

**#5 修正後統計量完全沒變**（13 列全數保留，8 個統計量 byte-identical）——證明這份資料本來就對齊，
該修正是防線而非數字變更。**沒有任何一個對外數字因為這輪 review 而改變。**

**兩次 mutation test 都確認測試會紅**：還原 proxy → 5 紅；把 `end` 改回 `2026-07-03` → lookahead 測試轉紅。

修正後 tests：`test_article_correction.py` **16 passed**、`test_nfp_official_release_dates.py` **32 passed**。

---

## 6c. Codex 複審（round 2）→ 判 FAIL → 兩個 blocking 已修

Round 2 確認 #1/#2/#3/#4/#7 修得完整（含逐項驗證 `_splice` 對相鄰 span 與
「`new` 內含自己的 `old`」都正確），但判定 **#5 與 #6 只做了一半**。兩個都屬實：

| # | blocking 缺陷 | 為什麼是真的 | 修正 |
|---|---|---|---|
| 5b | `after_idx` 為空時仍寫入該列、只把 next-day 存成 `None`，**沒進 `skipped`**。pandas `.mean()` 會靜默跳過 NaN → `spy_ret_next_day_mean_pct` 的分母比旁邊標的 n 小，而 fail-loud 不變式抓不到。 | 我上一輪宣稱「拒絕讓樣本無聲縮水」，但這條路徑正好繞過它 —— **同一個 bug class 在我自己的修正裡復發**。 | 無下一個 session → 整筆列入 `skipped` 並 raise，不再存 `None`。 |
| 6b | lookahead recorder **第一次呼叫就 raise**，所以只驗到 SPY；`^VIX` / `^VIX9D` 的 `end` 被改動仍會全綠。 | 三個序列共用同一個 cutoff，只驗一個等於沒驗。 | recorder 改成撐到第三次呼叫，斷言 ticker 序列 `[SPY, ^VIX, ^VIX9D]` 與三個 `end` 值；並補 call 數斷言，堵掉 `all([])` 的 vacuous 通過。 |

**mutation test 驗證新覆蓋確實有效**：單獨把 `^VIX` 的 `end` 改成 `2026-07-03`
（round 2 明確指出這個變異原本會存活）→ **測試轉紅**。已還原。

**兩個修正都沒有改變任何數字**：13 列與 8 個統計量重跑後 byte-identical
（`historical_nfp_table` 與 `historical_nfp_day_stats` 皆逐欄比對相同）。

### Round 2 提出但未修（非 blocking，已評估）

- **持鎖跨網路呼叫**：`shared_state_lock` 是無 timeout 的 blocking `flock`，而 sync 有 15 秒
  網路重試 —— 期間所有 feed writer 會被擋住。這是我為了修「lock 外用舊 snapshot」刻意換來的
  取捨。文章更正是**低頻手動操作**，正確性優先於可用性；但若未來要做批次更正，這個取捨要重審。
- **原子寫的成功路徑測試對 atomicity 而言是 vacuous**（拿掉 `fsync` 或改回 `write_text` 仍會過）。
  失敗路徑測試有抓到 `os.replace` 被移除。未補更深的 fault injection。
- **guard patch 目標改回舊值仍會綠**，因為測試的 feed 在 `tmp_path`，而 guard 本來就放行。
  patch 目標已是正確的那個，但這條測試不構成 guard 的迴歸防線。
- Round 2 環境唯讀、**沒有實跑測試**（`tmp_path` 無法寫入），所有 pass/fail 數字以本機實跑為準。

---

## 6d. Codex 複審（round 3）→ blocking 1 CLOSED、blocking 2 剩一個盲點 → 已補

- **Blocking 1（樣本無聲縮水）判定 CLOSED**。複審逐條確認：所有無法完整計算的路徑都在唯一的
  `rows.append` 之前 `skipped` + `continue`；成功列無條件寫滿五個欄位、不再有 `None` 分支；
  任何 skip 都在統計與 JSON 寫入前拋錯；8 個統計量全部用同一張完整表。
  （`std(ddof=1)` 的除數是 n-1 屬正確的樣本標準差定義，不是缺值造成的縮減。）
  **我自己另外驗過**：3 個數值欄位 usable 全部 = 13 = n，全表無 null/NaN。

- **Blocking 2 的四種變異，三種已被抓到**：`^VIX` end、`^VIX9D` end、ticker 順序皆 CAUGHT。
  剩一個盲點：recorder 在**第三次呼叫就中止 `main()`**，所以「日後新增的第 4 個下載」永遠不會
  執行，也就永遠不會被檢查 —— 那個 series 可以帶著沒人看過的 `end` 上線。

  **已補**：recorder 不再自己中止，改回傳一個 `_Tripwire`（`.columns` 被存取時才拋
  `_StopEarly`）。中止點因此移到整個下載區塊**之後**，第 4 個下載會照跑並被記錄，既有的
  ticker 序列與數量斷言就抓得到。

  **mutation test 實證**：臨時加入第 4 個下載 `^TNX`（`end="2026-07-31"`，明顯 lookahead）
  → **三個 lookahead 測試全紅**（修正前這個變異完全隱形）。已還原。

- 此輪為**測試層修正，未動實驗邏輯**：重跑後 `_results.json` 與前一版 byte-identical
  （整份 JSON `==` 比對相同），`experiment_gates.py` PASS，55 tests 全綠。

---

## 6e. Codex 複審（round 4）→ **PASS**，已產出合併裁決

複審逐行確認 tripwire 修正正確：`main()` 連續完成三次 `yf.download` 賦值期間**沒有讀取任何
回傳 frame**，第一個屬性存取確實是 `df.columns`（MultiIndex 攤平那一步），所以中止點確實
落在整個下載區塊之後；捕捉範圍只吞 `_StopEarly`，不會吞掉 `AttributeError` 之類的意外例外
而假裝成功。並確認 HEAD 與父 commit 的實驗程式與 results JSON **無 diff、git blob ID 相同**。

**FINAL VERDICT: PASS**，blocking defects = 0。

裁決檔：`review_verdict.json`（由 `experiment_gates.py verdict-template` 產生，**不是手抄**），
pin 住 9 個 claim-surface 檔的 sha256。`experiment_gates.py certify` → **PASS**，合併關卡已備妥。

### 四輪總結

| 輪次 | 判定 | 發現 |
|---|---|---|
| R1 | FIX-BEFORE-MERGE | 3 HIGH（sync 靜默失敗、非原子寫、replacement 交互污染）+ 4 MEDIUM |
| R2 | FAIL | 2 blocking（next-day 分母無聲縮水、lookahead 只驗 SPY）|
| R3 | FAIL | blocking 1 CLOSED；blocking 2 剩「第 4 個下載不可觀測」 |
| R4 | **PASS** | 盲點確實關上，無新缺陷 |

**R1 之後沒有任何一個修正改動過數字** —— 13 列表格與 8 個統計量在 R2/R3/R4 全部 byte-identical。
唯一改變對外數字的是**最初的日期修正本身**。

### 裁決的誠實 caveat（已寫進 `review_verdict.json`）

- R2/R3/R4 的審查環境是唯讀沙箱、**沒有可寫暫存目錄，跑不了 pytest**。裁決是基於逐行控制流
  分析、commit diff 與 git blob equality。**所有 55 passed 與四次 mutation test 都是我本機
  實跑的，不是審查者跑的** —— 這點必須寫明，否則會讓人誤以為 PASS 附帶了獨立的測試執行證據。
- **k528 完全不在審查範圍內**（§7）。這份 PASS 只認證本實驗的程式與產物，**不認證線上文章
  核心統計量的正確性**。

---

## 7. 尚未解決 / 需要另開任務的事

### 🔴 最重要：線上文章的核心統計量建立在**同一類污染**上（未修）

`mile_35eef830` 正文的所有主要數字——1.10 倍、1.17 倍、**2.17 倍體制差**、相關係數 0.45、
分界值 16.71、254 次樣本——全部出自 **k528**，而 `experiments/k528/k528_nfp_event_study.py`
**用的也是 `get_first_friday()` proxy**。

實測 k528 全樣本（2005-02 ~ 2026-03，254 筆，FRED 官方涵蓋範圍完整覆蓋、無外插）：

| | 數量 |
|---|---|
| 與官方日期相符 | 201 |
| **proxy 錯誤（該日無發布）** | **53（20.9%）** |
| 官方發布被完全漏掉 | 52 |
| 幻影月份 | 1（2025-10） |

即 **k528 樣本中每 5 個「NFP 日」就有 1 個不是 NFP 日**，且同樣數量的真實發布日被錯放進對照組。
偏誤不是隨機散布：**28 筆（53%）剛好早 7 天**（BLS 因參考週而改在第二個週五），
12 筆晚 3-4 天（假日提前）；整體系統性偏早（35 早 / 13 晚）。

**未修的理由**：修它要重跑 k528 全樣本並改寫線上文章的核心論點（2.17 倍體制差可能變動），
規模遠超本任務範圍（本任務 = T-1 實驗 + metadata），且任務明令不得發第二篇更正文。
**這需要獨立任務 + 完整審查。**

### 🟠 `event_dates.release_dates()` 的 `.max()` 取月份最後一筆，對 NFP 是錯的

已獨立驗證（非轉述）：6 個月份在 ALFRED 有兩筆，且**就業報告都是第一筆**：

```
(2006,5)  ['2006-05-05', '2006-05-08'] -> .max() 取到 2006-05-08
(2012,12) ['2012-12-07', '2012-12-12']
(2013,5)  ['2013-05-03', '2013-05-06']
(2020,5)  ['2020-05-08', '2020-05-11']
(2024,1)  ['2024-01-05', '2024-01-10']
(2024,8)  ['2024-08-02', '2024-08-21'] -> 08-02 才是就業報告，08-21 是基準修正
```

**對本任務無影響**：已驗證我這 13 筆（2025-05 ~ 2026-06）**沒有任何一個月份有重複條目**。

**未修的理由**：`release_dates()` 是 CPI 與 NFP 共用的。現有測試
`test_release_dates_uses_last_entry_when_release_has_same_month_revisions` **明確要求 CPI 取最後一筆**，
改成「取第一筆」會同時改動 K1442 剛修好的 CPI 結果。正確做法是 per-event 語意（NFP 取第一筆、
CPI 維持最後一筆），但那是共用模組的語意變更，應由獨立任務評估 + 審查，**不該由一個 NFP 任務
順手改掉 CPI 的行為**。

### 🟡 其他

- **全 repo 仍有 6 支腳本用 first-Friday proxy**（本任務只修 1 支）：`k528`、`k741`、`k661`、`k259`、`k904`、`paper/volatility-absorption/experiments/{k741,k904}`，另 `k1608` 用它當 calendar control。`k904` 在 `paper/` 底下——**可能影響論文**。未逐一評估影響。
- **未寫 `knowledge.json`**（依任務指示，屬主線程職責）。
- **未 merge 回 main**：全部 commit 在 `task/nfp-official-dates`，依規走 `scripts/merge_worktree.sh`。
- **FRED_API_KEY 不在 worktree**：`.env.local` 只在主 repo，worktree 內跑需自行 export。`_api_key()` 只找 `parents[3]`（worktree root），worktree 執行體驗不佳——未改（會動到共用模組）。
- **未跑 `anti_ai_gate.py` / `check_arc_dedup.py`**：本次是既有文章的數字更正，非新文章發佈。

---

## 8. 本任務未做的事

1. **沒有重跑 k528**，因此線上文章 `mile_35eef830` 的核心統計量（1.10/1.17/2.17 倍、0.45、16.71、254 筆）**仍建立在 20.9% 錯誤的日期上**。已量化並記錄於 §7，但未修正。
2. **沒有修 `event_dates.release_dates()` 的 `.max()` 缺陷**（§7），只驗證了對本任務無影響。
3. **沒有修其他 6 支仍在用 first-Friday proxy 的腳本**，也沒有評估 `k904` 對論文的影響。
4. **沒有發第二篇更正文**（依任務明確要求）。
5. **沒有寫 `knowledge.json` / `experiment_experiences.json`**（依任務指示）。
6. **沒有 merge 回 main**，也沒有跑 `merge_worktree.sh`。
7. **沒有重構既有的 errata 呼叫點**去用新的 `article_correction.py`。
8. **沒有重抓 T-1 快照以外的資料**；VIX9D 的變動是資料商回補，已如實記錄兩個 vintage 而非覆蓋。
9. **FB 端未同步更正**。已查：`fb_post_status = "success"`（確實發過），但
   `details.fb_post_url` 與 `fb_post_timestamp` **都是 null**——貼文存在卻沒留下位址，
   因此無法定位、無法核對它引用了哪個日期或哪組數字。且 Ivan Lai 個人帳號只能走
   CDP-attach Chrome（無 headless API），本次為背景執行，**FB 更正必須在 interactive
   session 補做**。

   附帶發現：`fb_post_status=success` 但 URL 為空，正是
   `.claude/rules/publishing.md` 警告過的狀態（會讓下游 audit 反覆判定「未發」而嘗試重發）。
   本次未修這個資料缺口——補寫 URL 需要先在 FB 上找到該貼文。
