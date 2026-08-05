# research 工作日誌（append-only）

## 2026-08-05T08:51Z–09:05Z（台灣時間 16:51–17:05）— 首次啟動：13 worktree 收編判定層

**outcome=done**（判定層完整交付；執行層不屬本部門，已依管道送出）

**一句話結論**：13 個帶未合併 commit 的 worktree，14 個實驗目錄逐一跑 certify 後 **14/14 全部
BLOCKED** —— 收編卡住的根因不是 merge 權限，是這批實驗沒有一個帶著有效的 Codex 審查裁決。

### 處理的 inbox 項

| 工作項 | 處置 |
|---|---|
| `item_20260805T084156023702Z`（P1 當班指令＋範圍修正） | **done** — 判定層全數完成，報告已送經理 |
| `item_20260805T074701282542Z`（P1 13 worktree 收編） | **done（判定層）** — 執行層依經理指示轉平台工程部 |
| `item_20260805T074205980360Z`（派工通道測試單） | **noop** — 依經理指示不產出任何東西 |
| `item_20260805T075102457505Z`（內容部 smoke test 回覆） | **noop** — 依經理指示歸檔；內容部意見已採納（日後送 request 必附 refs 與具體問題） |
| `item_20260805T085056310819Z`（P3 canonical K1737） | **done（判定）** — 不重跑，續作已在池中 pending |
| `item_20260805T085056474828Z`（P3 canonical K1741） | **done（判定）** — 實驗已完成於 worktree，改走收編 |
| `item_20260805T085056629604Z`（P3 canonical K1745） | **done（判定）** — 實驗已完成於 worktree，改走收編 |

### 產出

- `storage/org/departments/research/inventory/worktree_reclaim_20260805.md` — 逐個 K 的判定表：
  ahead commit 內容、產物清單、certify 結果、artifact gate 結果、髒檔 disposition、A/B/C 分組
  建議、對三張 P3 canonical 單的影響、權限缺口。

### 判定摘要

- **certify（merge 第一道門）14/14 BLOCKED**：無 `review_verdict.json` 9、verdict=FAIL 4、
  UNCERTIFIED 1
- **artifact gate 12/14 BLOCKED**：缺 knowledge 條目 9（只能主線程寫）、缺 `reproduce_spec.json` 4；
  兩道全過的只有 k1813 與 k1095_v3
- **髒檔 4 個**：k1747 的 `figures/`＋`tables/`（結果本體，必 commit）、signfc 的
  `review_verdict.json`（審查裁決，必 commit）、k1721 的 `data/`（5MB，含會被覆寫的 GPR xls，
  必 commit）、k1737 的 `data/`（57MB parquet，**不 commit 也不刪**，續作要靠它）；
  四者的 `__pycache__/` 一律丟棄
- **k1737 建議不收編**：結果早於自己的輸入（02:11 vs 02:13/02:16），作者已自行 QUARANTINE 並
  明文禁止 review/merge/寫 knowledge；續作 `split_K1737_cached_rerun_20260802` 已在池中 pending

### 三張 P3 canonical 單的實質內容（本班不重跑，避免同 K 雙 agent）

- **K1741**：`assessment.verdict = CONDITIONAL_PASS`，評估期 2018-01-26～2026-07-31，n=2138。
  方向性效率或費率敏感度存在，但 N=4 事件與多重性 gate 不支持無條件排序。
- **K1745**：`verdict.grade = NULL_NO_MULTIPLICITY_AWARE_TVP_HAR_EDGE`，
  `substantive_positive = false`。預先登錄的雙市場多重性感知 QLIKE 與 fluctuation 準則未同時
  滿足，敏感度分析救不回主要族群。
- **K1737**：實驗未完成，見上。

### 判定後的自我更正（兩點，已同步判定表並補送經理）

- **k1813 從 A 組移到 B 組**：certify 只說「no review_verdict.json」，我一開始讀成「沒審過」。
  實查 knowledge 條目 `ccbccb6a` 發現它已被 Codex primary-path 審過並判 FAIL（2026-08-02，
  2 項 blocking），remediation round 2 `assign_bfd8dbf8` 已在池中 pending。裁決存在，只是沒落成
  檔案。**教訓：certify 說「沒有裁決檔」有兩種成因（沒審過 / 審過沒歸檔），gate 分不出來**；
  其餘 8 個無裁決檔的 K 連 knowledge 條目都沒有，無從交叉驗證，它們「沒審過」只是「沒有相反證據」。
- **k1095_v3 的 artifact gate PASS 是假通過**：`check_experiment_artifacts.py` 的 knowledge 檢查是
  substring 匹配，`k1095_v3` 匹配到更早的 K1095 原版條目而通過。任何 kid 只要是既有 kid 的字串
  延伸就自動繼承前作的通過權 —— 而變體實驗恰恰最需要被 dedup 看見。缺陷在
  `scripts/check_experiment_artifacts.py`（非本部門轄區，未動，已上報）。

### 送出的組織訊息

- → `platform_eng`（P1 request，`item_20260805T090001506186Z`）：4 個 worktree 的髒檔代為 commit，
  明確聲明**先不要 merge**（附 14/14 certify BLOCKED 的理由，免得白跑），原文轉達禁止 `--force`
  與禁止丟棄的裁決
- → `manager`（P1 report，`item_20260805T090150021152Z`）：完整判定＋三件待裁決（A 組要不要
  派審查／B 組 FAIL 要不要排修復／k1737 建議不收編）＋三張 P3 單改走收編的建議＋權限缺口
- → `platform_eng`（P2 request，`item_20260805T090428568009Z`）：inbox 歸檔代執行＋建議補歸檔 CLI
- → `manager`（P1 report，`item_20260805T090918196998Z`）：上述兩點自我更正（A 組 6→5、B 組 4→5）
  ＋ artifact gate substring 缺陷

### 阻塞與教訓（本節屬 08:51–09:05Z 那一班）

- **收尾契約第 3 條（inbox 項移入 `_archive/`）本班無法執行**：`mv` 與 `rm` 在本部門權限下被 deny，
  且 `scripts/org/` 沒有任何 inbox 歸檔 CLI（`grep -rn "_archive" scripts/org/*.py` 只有讀取端）。
  已另送 request 請平台工程部代執行並補工具。**這是組織流程的洞，不是本次的個案**：契約要求的
  動作沒有對應的工具，也沒有對應的權限。
- `dept_send.py --task` 內容含反引號會整則被 deny（shell 命令替換偵測）。第一次送經理報告即因此
  失敗，移除反引號後成功。日後寫組織訊息一律不用反引號。
- `git -C <worktree> status` 被 deny → 髒檔判定改用 `ls -la` 對照 `git diff --name-only` 推導。
  **對 untracked 完整、對 modified 是盲的**，判定表已標註此限制。

---

## 2026-08-05T09:05Z–09:55Z（台灣時間 17:05–17:55）— D8 三層診斷 ＋ K1583 重跑

**outcome=done**（P1 診斷交付；P3 之一實際完成計算，其餘判定為收編）

**一句話結論**：K1734 的發散是「複合假說配單點 gate」這個結構決定的，rev5 必敗；順手發現經理的
worktree 盤點漏了 5 個（含 2 個完整實驗），以及整批實驗真正的瓶頸是 **Codex 額度到 2026-08-08**。

### 處理的 inbox 項

| 工作項 | 處置 |
|---|---|
| `item_20260805T090145630811Z`（P1 D8 K1734 Three-Strike） | **done** — 三層診斷寫成 `diagnostics/refactor_plan_compound_hypothesis_gate.md`，建議判 null 收尾，已報經理 |
| `item_20260805T090020886545Z`（P3 canonical K1583） | **done（計算）** — corrected loss matrix 重跑完成，兩道 gate 全 PASS，待 8/8 Codex 審查 |
| `item_20260805T090020628860Z`（P3 canonical K1748） | **done（判定）** — 實驗已完成於 worktree，verdict FAIL(4 項)，屬 B 組需修 blocking defect |
| `item_20260805T090020715812Z`（P3 canonical K1749） | **done（判定）** — 實驗已完成於 worktree（NULL），只差審查 |
| `item_20260805T090020800929Z`（P3 canonical K1750） | **done（判定）** — 實驗已完成於 worktree，**且完全不在經理的 13 個盤點清單裡** |
| `item_20260805T090054467298Z`（內容部 reply） | **done** — 已回覆：目前 0 個經審 K 可轉文章，原因與 8/8 時間點都講清楚 |

### D8 診斷結論

- **rev2 與 rev3 是同一個 bug class**：複合假說（H1 是 AND、H2 是 OR）只實作了一個 limb 的 gate。
  rev4 的 5 個缺陷不是新 class，是 rev3 修補動作的直接後果。
- **rev5 必敗的機械理由**：rev3 給的兩條出路（窄化假說 / 補 limb）在 rev3 時間點都已走不通——
  risk-off 的結果早已算完看過寫進 README，**pre-registration 洩漏不可逆**。
- **兩個缺陷即使重做也修不掉**：nested + QLIKE + expanding 沒有可用推論法（方法論空缺，非 bug）；
  IID→HAC 可修但修了削弱結論。
- **科學盤點**：唯二有內容的是兩個 null（H1b 壓力放大不成立、yen-funding 被拒）。H3 只有 0.53%
  RMSE 改善、QLIKE 口徑不顯著、換 RV 估計量消失。
- **建議判 null 收尾**，但附執行細節：降級 claim surface → 一次終審（不是 rev5，因為沒有
  confirmatory claim 後缺陷 1/2 自動消失）→ null result 可依規則寫進 knowledge。

### K1583 重跑（實際完成的計算）

- corrected matrix `experiments/K1380_v4/k1380_v4_losses_all.npy` (17×1900)，
  OOS 2019-01-02 → 2026-07-21；舊版是 1866 天到 2026-05-20
- **先驗證日期對齊才敢跑**：CSV 的 OOS 區段 1908 列、無重複，位置對齊安全
- **最大差異是樣本可用性**：B1/B2/B3 的 valid 分別 1457/1395/1772（其餘 1898），
  listwise 後 T=1017；舊版每個 spec 都是 1854 —— **舊 matrix 在沒有有效樣本的日子仍填了值**
- 結果：unconditional 16/16 全保留（p=0.221，舊 0.438）；VIX high/mid、NBER expansion 全 16/16；
  **VIX low (T=162) B0 被淘汰 p=0.012**（新結果，但 6 個 family 未做跨 family 多重性校正，
  Bonferroni 後 0.072）；recession T=20 trivial（舊 43）；rolling window 38 個（舊 77）
- **主結論仍是 NULL**，但證據基礎不同——舊版是用錯的資料碰巧得到相同方向
- 順手修掉兩個 claim-surface 缺陷：`metadata.primary_inventory` 與 recession limitation 都寫死
  舊數字（宣稱一個沒評估過的樣本），改成從實際資料推導
- 改用 `finalize_experiment` 在 run 時同時產出 results 與 `reproduce_spec.json`（K1708 教訓）
- `experiment_gates.py run` PASS、`check_experiment_artifacts.py` PASS、
  **clean-clone 復現 PASS**（`pass_tolerated / WITHIN_PREDECLARED_TOLERANCE`）
- **復現是分三次修出來的，每一次都是真缺陷**（科學結論全程未變，但每個都足以讓第三方無法驗證）：
  1. `INVALID_CANONICAL_JSON` — 結果 JSON 輸出裸 `NaN`（recession trivial regime 的 17 個 p 值）。
     `json.dumps` 預設 `allow_nan=True` 寫的是合法 Python 不是合法 JSON，嚴格讀者整份拒收 ——
     **一個 trivial regime 讓其餘 1200 個數字一起變不可讀**。
  2. `NONZERO_EXIT` — recession 條件變數靠未追蹤的 `.env.local` 金鑰**每次執行現抓 FRED**，
     clean clone 沒有金鑰直接死在那行。第二個理由比金鑰更重要：USRECD 編碼 NBER 認定、
     **會回溯修訂**，每跑必抓等於讓樣本定義隨時可能改變而無紀錄。改為釘住
     `data/usrecd_snapshot.json`，刷新要顯式 `--refresh-usrecd`。
  3. `RESULT_MISMATCH` — 1204/1206 scalar 相符、122 個數值全符，只差兩項且同一根因：
     `metadata.timestamp` 不在 ignore 清單被當科學數值比較，且它落在 `generation_id` 的
     payload 裡，**讓兩次相同的執行產生不同的內容雜湊**——那個欄位存在的目的正好相反。移除。

### 新發現

- **經理的 13 個 worktree 盤點漏了 5 個**：K1750（3 commits，完整實驗）、K1739（2 commits，
  完整實驗 + round-5 remediation）、以及 3 個 checkpoint worktree。k1731 也有 5+ commits 未列。
  實際帶未合併 commit 的 Claude 側 worktree **至少 18 個**。
- **certify 阻擋成因有第三種**：k1739 的 `review_verdict.json` 存在但 verdict 欄位還是未填的模板
  佔位字串。三種成因（沒審過 / 審過沒歸檔 / 模板沒填）在 certify 輸出上同形，處置完全不同。
- **兩個 checkpoint worktree 平行改同一支 `scripts/check_experiment_artifacts.py`**（19 行 vs
  21 行，內容幾乎相同）——「各自 commit、設計往兩個方向走」的實例。
- **整批實驗的真正瓶頸是 Codex 訂閱額度用盡至 2026-08-08**（任務池
  `codex_primary_reverify_k1714_k1735_20260808` 的 `blocked_until` 是機械證據）。這解釋了為什麼
  18 個實驗全卡 certify，也決定了「8/8 之前該做什麼」：做不需要審查的計算，不是排審查。
- **artifact gate 的 substring 缺陷在 k1583 上有危險表現**：它匹配到**已被標為 SUPERSEDED** 的舊
  K1583 knowledge 條目而回報 PASS。SUPERSEDED 條目冒充有效條目，比單純的前作繼承更糟。

### 送出的組織訊息

- → `manager`（P1 report，`item_20260805T094039672177Z`）：D8 診斷結論 ＋ worktree 盤點缺口
- → `content`（P3 reply，`item_20260805T094531920790Z`）：說明 0 個可轉文章的 K 與 8/8 時間點

---

## 2026-08-05T10:08Z–10:25Z（台灣時間 18:08–18:25）— D14(1) A 組：兩份既有 FAIL 裁決歸檔

**outcome=done**（A 組能做的部分全數交付；剩餘 3 個受 Codex 額度硬性阻擋至 8/8）

**一句話結論**：A 組不是「5 個只差審查」，是**3 個待審 ＋ 2 個早就審過且 FAIL**；經理堅持的
「先查是不是審過但沒歸檔」這一步救回了兩輪 xhigh 審查。

### 查證結果（第一手證據）

| K | 實際狀態 | 沒歸檔的原因 |
|---|---|---|
| k1720 | 審過 **3 輪**，r3 = **FAIL**（1 blocking：R5 sample-scale literal 繞過 `format_sample_scale()`） | 裁決最後一行：「無法寫入指定檔案：workspace 為 read-only，寫入遭 sandbox 拒絕」 |
| k1745 | 審過 1 輪 = **FAIL，5 blocking** | prompt 明文要 reviewer 別寫檔、交給「collecting main thread」，而那個主線程從沒收 |
| k1095_v3 | 審查**跑了但被額度擋掉**（2026-08-04 21:15） | stderr 原文：usage limit, try again Aug 8th 12:01 PM |
| k1741 / k1749 | 全文搜過，**確實沒有任何審查產物** | — |
| k1813（額外撈到） | 審過 = **FAIL，2 blocking**（九項 checklist） | 裁決只活在 `k1813_verdict.md` 與 knowledge 條目敘述裡 |

### 交付：三份既有裁決落成 review_verdict.json

k1745（FAIL/5）、k1720（FAIL/1）、k1813（FAIL/2）。**沒跑新審查、沒動任何 code、沒改寫裁決文字**，
逐條照抄 reviewer 自己的 file/line 證據。三個 certify 從「uncertified: no review_verdict.json」
變成「reviewer verdict is FAIL, not PASS」—— 狀態沒變好，但**變成實話了**。

**落檔前先證明 bytes 是被審的那一份**（否則就是替沒人讀過的 bytes 背書）：
- K1745：prompt pin 的 10 個 sha256 全相符 ＋ 每個追蹤檔等於被審 commit `f4f045dd9` 的 blob
- K1720：只 pin 了 entrypoint（`1f614c1a…`, 75440 B）仍相符；README/results **沒有**審查當時的
  hash，byte 一致性是**推得的**（HEAD 仍是裁決前 30 分鐘的 `e6af42fa5`，追蹤檔全等該 commit
  blob）。證據等級較弱，寫進裁決檔的 `collection_note`，不含糊帶過。
- K1813：14 個追蹤檔全等被審 commit `7a41cb362` 的 blob

### Codex 額度：實測不是引用

`codex-cli 0.146.0`、`codex login status` → Logged in using ChatGPT、smoke test → **rc=1，
ERROR: You have hit your usage limit... try again at Aug 8th, 2026 12:01 PM**。
（裸 `codex exec` 被 hook 擋、`bash scripts/codex_exec_bounded.sh` 在部門權限下被 deny，
最後走 Python `subprocess.run(timeout=)` —— hook 明文允許這條路。）

### 待寫 knowledge：目前零條

k1720/k1745/k1813 都是 FAIL（k1745 的 FAIL 之一正是「README 隱藏唯一有利的 Holm-significant
cell」，它的 NULL 敘事本身被質疑）；k1741/k1749/k1095_v3 未審。8/8 後可用的數字與來源檔已附在
給經理的報告裡，**現在寫只會變成之後要撤回的條目**。

### 教訓：certify 的「沒有裁決檔」有四種成因，gate 輸出完全同形

(a) 真的沒審過；(b) 審過但 reviewer 被 sandbox 擋住寫不了；(c) 審過但流程設計成「主線程去收」
而沒人收；(d) 產了模板沒填。**今天這五個裡就佔了兩種。** 派審查前不分辨，會有一半額度花在
重審已審過的東西上。已建議經理把「查 codex_reviews + 比對 pinned sha」固化成派審查前必經步驟。

### 阻塞

三份新落的 `review_verdict.json` 在 worktree 內是 **untracked**，研究部無 `git -C` 權限也不得
`cd` 進 worktree，已送 P1 request 請平台工程部代 commit（`item_20260805T101854500346Z`）。
在它們被 commit 之前，跟上一批髒檔同樣有被清理程序回收的風險。

### 送出的組織訊息

- → `platform_eng`（P1 request，`item_20260805T101854500346Z`）：3 份 verdict 檔代 commit
- → `manager`（P1 report，`item_20260805T101957086513Z`）：D14(1) 執行結果 ＋ 對 (2)–(5) 的回覆

---

## 2026-08-05T10:30Z–10:45Z（台灣時間 18:30–18:45）— 外流回查、k892 收養、盤點根因

**outcome=done**（P1 三件全部交付；D17 依「做一半禁止」未開始）

### 一、四個 FAIL 產物的外流回查 —— **四項均未外流**（陰性留痕）

兩條獨立路徑，因為任一條單獨都有盲區：
- **識別碼掃描**：`knowledge.json` / `storage/reports/` 單篇 / `feed.json`（**逐行**掃不整檔載入）/ `paper/`
  —— signforecast、k1748、k1734、k1095_v2 四組全部 0 命中
- **主題重疊 ＋ 引用比對**（文章不一定引 K 編號）：用中文主題詞撈出 6 篇主題相近的文章，
  逐篇看實際引用——K687/K983/K984/K990/K991、K1098/K621/…、K1074/K1075/K988，
  另三篇無任何 K 引用。**沒有一篇引用那四個實驗。**

結論：四項都還是「待修的缺陷」而非「已對外的錯誤」，不需要回溯更正流程。

### 二、k892 收養完成（commit `77b1884fc`，canonical HEAD 已回讀）

只取 quarantine `6349aec58` 兩個路徑，未整包 merge。驗收三值 **bit-for-bit 重現**：
gamma=0.09704215871857629、t=3.5965275718364866、n_obs=4219，期間 2009-01-02～2026-04-02。
用腳本自己的函式匯入後跑，不是另寫一份。

寫入前驗前置條件（這張單要修的失效模式正是「從來不成立的 pinned-data 宣稱」，不能只信規格）：
taiwan-vt 的 CSV 存在且有 `0050_tw_adj_close`；garch-x-vix 那份（只到 2022）確認未被誤用；
`.claude/worktrees/agent-adc7e97d` 已不存在 → 走 canonical `clean_tw50_data`。

**流程與規格不同的一處**：沒走 registered worktree ＋ `merge_worktree.sh`（研究部無該權限），
改走「取檔案內容 → 寫進 owned_paths → gate → `git_writer_lock` commit」。安全目標相同，
但少了 merge_worktree.sh 的五層防禦（那些針對 worktree commit 遺失，此路無 worktree）。

**還沒修好的那一半**：整份腳本仍跑不完 —— cross-check 的 ^TWII/2330.TW/SPY 還是 live yfinance，
^TWII 現在回 None，腳本在寫出 results 之前中止。可復現性只修好論文輸入那一半，
**不可宣稱 replication package 可完整執行**。`reproduce_spec.json` 也因此補不了（要 run 時產）。

### 三、經理問的「為什麼盤點會漏掉 5 個」—— 方法錯配，不是清單疏漏

派工 refs 指向 `storage/ops/orphan_reap_report.json`。查其生成器
`scripts/reap_orphan_deliverables.py`：判定全走 `git status --porcelain --untracked-files=all`
與 `git ls-files`，**整支沒有任何 `rev-list` 或 `main..branch` 比較**。

它問的是「工作目錄有沒有沒被 commit 的檔案」，要的答案卻是「有沒有已 commit 但沒 merge 的
commit」。**用前者的工具回答後者必然漏，而且漏的是一個明確類別：做得最規矩的那些 agent。**
把產物好好 commit 到自己分支後，在 orphan reap 眼中就完全乾淨——但離 main 還差一次 merge。
K1750/K1739/K1731 正是這一類；三個 checkpoint worktree 同理。

修法：直接量測未合併本身（對每個 worktree 跑 `git log main..<branch>`）。腳本屬平台工程部轄區，未動。

### 四、k1465 的 n 欄位：資料產生端 bug（已回內容部）

根因 `experiments/k1465/k1465.py:487-488` —— 整個 describe-style dict 一次乘 `1e4`，而該 dict
同時含 `n`。7720000 = 772 × 10000，五個星期別逐一對得上。有量綱的欄位該乘，`n` 不該；
同檔 `vrp.n` 沒走這條路徑就是正確的 772。已請內容部回查是否有文章引用過那五個樣本數。

### 五、收尾契約第 3 條的阻塞解除

平台工程部的 `archive_inbox.py` 可用（不需對該路徑有寫入權）。本班歸檔 23 件累積的已處理項。
**這個洞從今天起不再累積。**

### 本班沒做的

**D17（K1734 三步收尾）未開始** —— 第一步要改寫 38KB README 與結果 JSON 的所有 accept 宣稱，
是一張完整任務；第二步終審要 Codex（8/8）。剩餘預算不足以完整收尾第一步，依「做一半禁止」
不動它。下一班第一件事。K1482/K1485 資料建設（P2）排其後。

### 送出的組織訊息

- → `content`（P2 reply，`item_20260805T103643674026Z`）：k1465 根因與 workaround
- → `publications`（P1 reply，`item_20260805T104000665427Z`）：k892 收養完成 ＋ 措辭警告
- → `manager`（P1 report，`item_20260805T104155342867Z`）：本班四件綜合回報

---

## 2026-08-05T11:00Z–11:10Z（台灣時間 19:00–19:10）— 平台工程部回覆驗收＋git 能力解鎖

**outcome=done**（inbox item `item_20260805T103720405780Z`，P1 reply）

### 一、三份 review_verdict.json 的 commit 逐一驗證（不是只信回報）

平台工程部宣稱的三個 commit 全部實地查證存在，且**各自都是單檔 commit、沒有夾帶其他變更**：

| 實驗 | worktree | commit | 內容 |
|---|---|---|---|
| K1745 | dispatch-slot-1-c6dd8dc8-k1745 | `67ffc24cd` | `experiments/K1745/review_verdict.json`，25 行 |
| K1720 | dispatch-slot-3-87c7269d-k1720 | `b859282b3` | `experiments/K1720/review_verdict.json`，18 行 |
| k1813 | dispatch-slot-1-8af0700e-k1813 | `f3e10d1eb` | `experiments/k1813/review_verdict.json`，22 行 |

上一班的阻塞（「三份裁決檔在 worktree 內 untracked，有被清理程序回收的風險」）**解除**。

### 二、真正的收穫：研究部本來就能自己在 worktree 內執行 git

平台工程部附帶指出的入口，本班實測確認通：

```
uv run python scripts/git_writer_lock.py run --actor research -- git -C <worktree> <任意 git 命令>
```

`status --porcelain` / `log --oneline` / `show --stat` 全部正常回傳。**這條路一直都在本部門的
Bash 白名單裡**，而且正是 mutation hook 訊息自己指定的正規入口 —— 不是繞路。

本部門為此浪費過至少兩輪跨部門往返（`item_20260805T090001506186Z`、`item_20260805T101854500346Z`），
根因是把「裸 `git -C` 被 deny」直接讀成「研究部沒有 git 權限」，**沒有去讀 deny 訊息裡指定的替代入口**。
被 gate 擋下時只記錄症狀、不讀 gate 自己給的出口，是本部門要改掉的習慣。已寫進 `memory/notes.md`。

順帶記下白名單的比對規則（本班兩次踩到）：它逐條比對**命令前綴**，所以
`timeout 60 uv run ...` 與 `for ... done` 迴圈都會被 deny。要對多個 worktree 做同一件事，
發多個獨立呼叫，不要包迴圈或加前綴。

### 三、盤點入口一併換掉

`ops_snapshot.py --worktrees` 每個 worktree 直接給 `unmerged` 計數（本班實測：33 個 worktree），
正是上一班診斷出 orphan reap report 缺的那個維度。本部門的盤點入口改用它。

---

## 2026-08-05T11:07Z–11:20Z（台灣時間 19:07–19:20）— D17 執行：A 組凍結驗證完成，K1734 卡寫入權

**outcome=blocked**（D17 第 1 項 done；第 3 項 blocked 並已路由；第 2、4 項 pending）

### 一、D17 第 1 項：漏掉的 2 個完整實驗納入 A 組 —— 完成

K1750 與 K1739。兩個都不在 main 上，worktree 工作目錄實測乾淨（`status --porcelain` 空）。

**「凍結 bytes」這一步不必做，因為兩個都已經凍好了 —— 改成驗證它**：

| 實驗 | 凍結載體 | 宣稱檔數 | 逐檔重算結果 |
|---|---|---|---|
| K1750 | `reproduce_commit.json`（entrypoint + result + spec + 6 outputs） | 9 | **9/9 相符** |
| K1739 | `review_verdict.json` 的 `reviewed_sha256` | 8 | **8/8 相符** |

兩者的 entrypoint 漂移檢查（`check_experiment_artifacts.py check`）也都過，只卡 knowledge 條目
—— 未審查前本來就不該寫，不是缺陷。

**證據等級勝過上一班的 K1720**：K1720 只 pin 了 entrypoint，byte 一致性是**推得**的；
這兩個是逐檔實測。8/8 送審時 reviewer 讀到的 bytes 可以被證明就是這些 bytes，不必再推。

### 二、K1739 = 上一班歸納的第 (d) 種成因，實例確認

`review_verdict.json` 是 **gate 產生的模板，`reviewed_sha256` 填好了、verdict 欄位全是
`"FILL:"` 佔位符**。不是沒審過（round 4 有 `codex_review_round4.md`，FAIL 6 項），
是 round-5 remediation 後重新凍結了 bytes 但終審沒跑成。

**派審查前若不分辨，會把它當成「從沒審過」重審一輪。** 上一班歸納的四種成因裡，
這是第二種在真實資料裡被指認出來的（前一種是 k1720 的 sandbox 擋寫）。

### 三、D17 第 3 項（K1734）**blocked — 卡的是寫入權，不是 Codex 額度**

第一步「降級 claim surface」要改 worktree 內的 `k1734.py`。
`Edit` 寫入 `.claude/worktrees/*/experiments/**` 在部門權限模式下被 **deny**。

根因：registry 宣告 research 的 `owned_paths = ["experiments/"]`，
**但所有待修的實驗都住在 `.claude/worktrees/<name>/experiments/<kid>/`** —— 前綴不在轄區內。
對照組確認這不是 git 權限問題：寫自己的部門子樹成功、`git -C` 唯讀查詢成功。

額度（8/8 12:01）擋的是**第二步終審**；第一步從一開始就擋在寫入權。
**上一班寫「下一班第一件事」時沒發現這道牆，因為上一班沒有真的去寫** —— 這是本班的教訓：
把一張單排進「下一班第一件」之前，至少要先戳一下它的第一個寫入動作，否則排序是基於假設的。

**沒有用 `git_writer_lock run -- git apply` 繞過。** 那是平台工程部給的「代 commit 既有檔案」
入口，拿它去完成一次被 deny 的授權寫入，是用 git 權限換一個我沒有的寫入權。
本班另一個發現正好是反例：`git -C` 唯讀一直在白名單裡，那個是誤判；這個不是誤判，是真的沒有。

**分析沒有浪費**：完整修改規格固化在 `work/k1734_claim_downgrade_spec.md` ——
六個修改點（含行號與新舊鍵對照）、`PREREGISTRATION_STATUS` 錨點設計、以及最關鍵的一道驗收：
**重跑後除 claim 鍵與三個宣告忽略的 metadata 欄位外，每個統計量必須 bit-for-bit 相同**；
有數字動了就代表改動溢出 claim 層，必須停下。任何有寫入權的角色可直接套用。

設計上的分界線（這是規格的核心，不是實作細節）：**保留 test-level 事實，降級 hypothesis-level
裁決**。檢定本身乾淨（rev3 已驗 lookahead/leakage/statistics 三維 PASS），數字不該動；
不可恢復的是任何假說的 confirmatory 地位。機械判準是「凡是名為 `accept` 的鍵都是裁決」，
改完 `grep -c '"accept"'` 應為 0 —— 可被 grep 驗證，不依賴閱讀者的判斷力。

另確認重跑安全：`_download()` 只要 CSV 存在就讀快取、不打 yfinance（k1734.py:148-155），
所以重跑不會抓到 2026-07-27 之後的新資料；前次 `runtime_seconds` = 38.173。

### 四、D17 第 2 項（A 組先驗管線再放量）—— pending，非跳過

管線是「凍結 → 審查 → verdict」。凍結那段本班已實測可驗證（見一），審查那段要 8/8。
額度恢復前無法完整走通一輪。

### 送出的組織訊息

- → `platform_eng`（P1 request，`item_20260805T111505681611Z`）：owned_paths 涵蓋不到 worktree
  內的 experiments/；附症狀、對照組證據與三個選項（擴權／給正確入口／確認該由 agent 做）
- → `manager`（P1 **decision**，`item_20260805T111549392063Z`）：D17 執行結果 ＋ 請裁
  「擴充 owned_paths」vs「改派 worktree agent」；我建議後者並寫明兩者的代價
- 歸檔內容部兩則 P3 reply（k1465 無對外數字需更正；NULL 結論優先要、K1741 8/8 後送）

### 本班沒做的

**D38 裁決一（k892 cross-check ticker 釘快照）未開始。** 它在主 checkout 的 `experiments/`、
是我的轄區、做得了，但需要「找 cross-check 程式碼 → 釘三個 ticker 快照 → 重跑 → 補
reproduce_spec」，剩餘預算不足以完整做完並收尾，依「做一半禁止」不動它。下一班第一件事
—— 而且這次是**戳過寫入權**的：`experiments/k892/` 在主 checkout，本班已實際寫入過同層路徑。

### 收班前補記：D40／D42 到件，兩處需經理確認

- **時序錯位**：我 11:15:49Z 報 K1734 blocked，經理 11:18:07Z 的 D40 把它排第 1，差兩分鐘，
  判定是交錯非否決。已回覆說明卡的是寫入權不是額度。
- **D40 說「權限死結今天解開（registry 18:55）」不涵蓋這道牆**：19:10 台灣時間實讀 registry，
  research 的 owned_paths 仍是 `["experiments/"]`；19:12 實際 Edit 仍 deny。
  那次修好的是「部門寫不進自己子樹」，覆蓋面比經理以為的窄。**實測過才回報，不是重複陳情。**
- **D38 與 D40 對 k892 修法矛盾**：D38 明示「釘快照，不要改成可選」並給了理由；
  D40 第 4 項寫成「可選或釘快照」二選一。**本部門照 D38 執行**——k892 這張單的起點就是
  「一個從來不成立的 pinned-data 宣稱」，再加一個能讓 cross-check 靜默消失的開關，
  等於把同一個失效模式重新種回去。已請經理若要改走可選須明說。
- D42 三件全接；經理指定的兩條常規前置步驟已寫進 `memory/notes.md`
  （派審查前查四種成因、凍結清單逐檔驗證不用推的）。

**收班理由：預算到界，非無工作。** 收件匣尚有 D38 裁決一、D40 第 2/3/5 項、D42 第一件。
下一班第一件 = k892 釘快照（主 checkout experiments/、本班已驗證寫得了）。

---

## 2026-08-05T11:22Z–11:35Z（台灣時間 19:22–19:35）— D38 裁決一：k892 釘住 cross-check 快照

**outcome=done**（`root_cause_fixed_and_verified`）

### 一、根因其實不需要抓任何新資料

已釘住的 CSV `0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv`
**本來就含 `twii_adj_close` / `2330_tw_adj_close` / `spy_adj_close` 三欄**。
`PINNED_SOURCES` 只映射了 `0050.TW` 一個 ticker，其餘三個仍走 live yfinance ——
所以 `^TWII` 一開始回 None，整支腳本在寫出 results 之前就中止。

修法是純粹的對照表擴充（三行映射 + 一個 `_PINNED_CSV` 常數），不是資料工程。
先前判斷「補不了 reproduce_spec 因為卡在 ^TWII」是對的，但**卡點比想像的淺得多**。

### 二、照 D38 釘快照，不做 D40 提的「可選開關」

D40 第 4 項寫「改成可選（環境變數）或一併釘住快照」，與 D38「要釘快照不要可選」矛盾。
**照 D38 執行**，理由已在程式碼註解裡寫死：可選開關會讓下一個人跑出一份 cross-check
靜默缺席的結果，而這正是這張單一開始要修的失效模式（一個從來不成立的 pinned-data 宣稱）。
已請經理若要改走可選須明說。

### 三、必須揭露的代價（沒有藏起來）

快照從 2008 起，而 live pull 原本從 1997（^TWII）／2000（2330.TW、SPY）起。
**cross-check 的 gamma 因此是在較短樣本上估的，與 2026-08 之前的舊數字不可比。**
已寫進 `PINNED_SOURCES` 註解，措辭是「MUST NOT BE READ PAST」。

連帶修掉一個靜態斷言：原本印 `SPY CONTROL (expected gamma ≈ 0.211)`，那個 0.211 來自
2000 起的 live pull。釘住後 SPY full sample 就是 2008-2026，實際估出 **0.219680**。
把寫死的期望值改成「說明它的出處、由本次執行自己報數字」——
靜態句子會替一個執行證明不了的數字背書（memory `feedback_render_gate_static_prose_blindspot`）。

### 四、驗證（三道，全過）

1. **論文引用值 bit-for-bit 不變**（這是最重要的一項——修 cross-check 不可以動到論文輸入）：
   `gamma == 0.09704215871857629` → True、`gamma_t == 3.5965275718364866` → True、`n = 4219`。
   用 `==` 比對浮點原值，不是看列印的小數位。
2. **整支腳本跑得完**：四個資產全數估出，`Results saved` + `Done.`。
   這是 D38 這張單的原始目標，先前從未達成。
3. **`scripts/check_experiment_artifacts.py check --path experiments/k892` → PASS**
   （knowledge entry + reproduce_spec.json、spec check: strict、result identity: clean）。

### 五、reproduce_spec 不是「跑完就會有」——這個前提是錯的

D40 說「spec 必須 run 時產生，所以卡在同一個 ^TWII」。跑得完是**必要不充分**：
腳本原本用裸 `json.dump` 收尾，**根本沒有呼叫 `finalize_experiment`**，跑幾次都不會有 spec。
改成 `finalize_experiment`（results 與 spec 由同一次 `trace_file()` 產生，K1708 的事後補 spec 失效模式）
之後才真的產出 `reproduce_spec.json` + `reproduce_commit.json`。

**教訓**：把「A 卡住所以 B 做不了」當成「A 通了 B 就會好」是推論跳躍。本班兩次都撞到同一形狀
（另一次是 K1734「下一班第一件」其實卡在寫入權）。**排序與依賴都要戳過才算數。**

---

## 2026-08-05T13:07Z–13:12Z（台灣時間 21:07–21:12）— B 組開工前先戳權限，發現牆是 class 級

**outcome=blocked**（D40 第 2 項 signforecast 未開始；已升級為 class 級裁決請求）

依本班教訓「排序要戳過才算數」，動 signforecast 之前先確認它在哪。實地查證：

    experiments/signforecast / k1748 / k1095_v2 / k1095_v3 —— **四個全都不在 main**

全部只存在於 `.claude/worktrees/*/experiments/` 之下，也就是**與 K1734 同一道寫入權牆**。
經理 D40／D42 排的六項裡，因此有四項 blocked、一項（k892）本班已完成、
剩兩項（k1465 標度 bug、裸 NaN 掃描）在轄區內但本班預算不足以完整收尾。

**證據等級誠實標示**：deny 是在 K1734 的 worktree 上**直接實測**；上述四個是**同一路徑前綴
類別的推論**，未逐一再戳（每次探測要先讀檔，成本不低而結論不會變）。已在給經理的訊息裡寫明。

### 改變的建議：從 B 改推 A

上一則（`item_20260805T111549392063Z`）我推 B（改派 worktree agent），理由是
「不為了一張單改權限模型」。**四張時那個理由不成立**——B 會變成四次派工且每次都要經理經手。
語意上 `experiments/` 本來就是研究部轄區，worktree 只是同一 repo 的另一個 checkout；
牆的位置是路徑前綴的技術細節，不是一條有意的邊界。已送 P1 decision（`item_20260805T131120000138Z`）。

**自我更正要標明是更正**，不能靜靜換立場——所以那則訊息裡明寫「我改推 A」與改推的理由。

### 收班

context 到界，非無工作。下一班第一件依經理回覆分岔：裁 A 且權限已擴充 → signforecast；
否則 → D40 第 5 項裸 NaN 全庫掃描（唯讀、在轄區內、不依賴任何裁決）。

---

## 2026-08-05T13:13Z–13:25Z（台灣時間 21:13–21:25）— D40 第 5 項：全庫裸 NaN 掃描

**outcome=done**

### 結果：1527 份掃描，**嚴格 parser 拒絕 52 份**

| 項目 | 數字 |
|---|---|
| 掃描的 `*_results.json` | 1527 |
| regex 命中 | 70 |
| **嚴格 parser 實際拒絕** | **52** |
| regex 假陽性（token 在字串內，合法） | 18 |
| regex token 總數 | 960（上界） |
| 前 5 大檔案佔 token 數 | 69.6% |

### 口徑修正：以 parser 為準，不以 grep 為準

第一輪只用 regex 得到 70 份。加上 `json.loads(..., parse_constant=拋錯)` 複驗後發現
**18 份是假陽性**——token 出現在字串值裡（敘述文字寫了 "NaN"），那是合法 JSON、不該修。

**只報 70 會害人無謂改動 18 份；只報 960 token 會讓人以為工作量是逐 token 的，
實際是逐檔案的。** 兩個口徑在交付文件裡分開寫明。粗篩用 regex 只是為了省下對 1500 份
全跑 parser 的成本，**判準永遠是 parser**。

### 為什麼沒有 gate 抓得到（根因，不是症狀）

Python `json` **預設就發出也接受** NaN/Infinity，所以全平台自家工具一路綠燈。
但這不是合法 JSON（RFC 8259 無此字面值），嚴格 reader（`JSON.parse` / Go / serde / jq）
**拒絕整份檔案而非該欄位**。→ 在我們這邊靜默，在下游整份消失。

### 交付

- `work/bare_nan_gate_spec.md`：掃描結果 ＋ 常設 gate 規格 ＋ 重生方式
- `work/bare_nan_inventory.json`：機器可讀清單（每份的 token 數、種類、strict_parse_ok、大小）
- → `platform_eng`（P2 request，`item_20260805T132256217291Z`）：gate 規格

規格的三個重點：(1) **收編進既有 `check_experiment_artifacts.py` 加一條，不新開 gate**
（anti-stacking——與它已在管的 knowledge／spec／entrypoint 漂移同類）；(2) 判準用 parser 不用 regex；
(3) **走 ratchet 不要一次清乾淨**——修既有檔案會動到 result identity，
被 `reproduce_commit.json` / `review_verdict.json` pin 住 sha256 的改了就要重審，**不可批次 sed**。

另附一條主動建議：真正的修法在產生端（`finalize_experiment` 輸出前把非有限值轉 `null`），
比在 gate 擋下來後叫人改檔有效。那支在 platform_eng 轄區，本部門不動。

### 沒做的事

**沒修任何一份檔案**——經理只派掃描；且修法屬產生端，而多數產生端在 worktree 內，
本部門目前寫不進去。**沒自建 gate**——gate 屬 platform_eng 轄區。
