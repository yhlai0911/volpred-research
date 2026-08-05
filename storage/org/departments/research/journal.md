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
